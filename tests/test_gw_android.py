"""Gateway box: keeps its own copy of the Android app (unpaid guests can't reach the internet) and offers it on the login page."""
import os, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
os.environ.update(LAN_ADDR='127.0.0.1', LAN_PREFIX='8', PORTAL_PORT='18087', SAFENET_API_URL='https://cloud.test', SAFENET_API_KEY='k',
                  STATE_DIRECTORY=sys.argv[1])
sys.path.insert(0, 'gateway')
import portal
portal.mac_for_ip = portal.wire_mac_for_ip = lambda ip: 'aa:bb:cc:00:00:08'
portal._nft = lambda script: None
portal._background = lambda fn, *a: None
portal.safenet_api = lambda method, path, body=None, timeout=25: {'packages': [], 'payments_enabled': False} if 'packages' in path else {}
files = {'/one': b'PK\x03\x04' + b'1' * 3000000, '/two': b'PK\x03\x04' + b'2' * 500, '/bad': b'<html>wifi login</html>'}
class Cloud(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = files.get(self.path)
        self.send_response(200 if body else 500); self.send_header('Content-Length', str(len(body or b''))); self.end_headers(); self.wfile.write(body or b'')
cloud = ThreadingHTTPServer(('127.0.0.1', 0), Cloud); threading.Thread(target=cloud.serve_forever, daemon=True).start()
URL = f'http://127.0.0.1:{cloud.server_address[1]}'
srv = portal.Server(('127.0.0.1', 18087), portal.PortalHandler); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18087'
page = lambda: urllib.request.urlopen(BASE + '/').read().decode()
def sync(path):
    portal.sync_android_app(URL + path if path else None)
    for _ in range(100):
        if not portal._apk_fetching.locked(): return
        time.sleep(.05)
    raise AssertionError('still fetching')
def status():
    try: return urllib.request.urlopen(BASE + '/app/android').status
    except urllib.error.HTTPError as e: return e.code

# no app yet: no card, nothing to download
assert 'appcard android-app' not in page() and status() == 404
# a failed fetch or a wrong file offers nothing
sync('/missing'); assert status() == 404 and 'appcard android-app' not in page()
sync('/bad'); assert status() == 404 and 'appcard android-app' not in page()
# fetched: served from the box itself, with a link on the box, not on the (blocked) internet
sync('/one')
assert '<a class="appcard android-app" href="/app/android" download hidden>' in page()
r = urllib.request.urlopen(BASE + '/app/android')
assert r.read() == files['/one'] and r.headers['Content-Type'] == 'application/vnd.android.package-archive' and 'SafeNet.apk' in r.headers['Content-Disposition']
head = urllib.request.urlopen(urllib.request.Request(BASE + '/app/android', method='HEAD'))
assert head.status == 200 and head.read() == b'' and int(head.headers['Content-Length']) == len(files['/one'])
# same link: not downloaded again
stamp = os.stat(portal.APK_FILE).st_mtime_ns; sync('/one'); assert os.stat(portal.APK_FILE).st_mtime_ns == stamp
# a failed update keeps the copy guests already get
sync('/bad'); assert urllib.request.urlopen(BASE + '/app/android').read() == files['/one']
# a new upload replaces it
sync('/two'); assert urllib.request.urlopen(BASE + '/app/android').read() == files['/two']
# removed in the cloud: gone here too
sync(None); assert status() == 404 and 'appcard android-app' not in page()
# the config from SafeNet drives it
portal.API_MODE = True
portal.safenet_api = lambda method, path, body=None, timeout=25: {'android_app': URL + '/two', 'tenant': 't', 'portal': {}}
portal.refresh_branding()
for _ in range(100):
    if os.path.isfile(portal.APK_FILE): break
    time.sleep(.05)
assert status() == 200
srv.shutdown(); cloud.shutdown()
print('GATEWAY ANDROID OK')
