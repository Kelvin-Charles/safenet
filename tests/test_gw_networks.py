import os, sys, threading, urllib.request, urllib.parse, urllib.error
os.environ.update(LAN_ADDR='127.0.0.1', LAN_PREFIX='8', PORTAL_PORT='18083', SAFENET_API_URL='https://x', SAFENET_API_KEY='k', STATE_DIRECTORY=sys.argv[1])
sys.path.insert(0, 'gateway')
import portal
portal.IMG_DIR = sys.argv[2]
portal.mac_for_ip = lambda ip: 'aa:bb:cc:00:00:09'
sent = []
def fake(method, path, body=None, timeout=25):
    if path == '/api/portal/packages':
        return {'payments_enabled': True, 'packages': [{'id': 1, 'name': '1 Day', 'price': '1000', 'currency': 'TZS', 'validity_minutes': 1440}],
                'networks': [{'id': 'mixx', 'name': 'Mixx by Yas', 'min_amount': 1000}, {'id': 'airtel', 'name': 'Airtel Money', 'min_amount': 0}]}
    if path == '/api/portal/purchase':
        sent.append(body); return {'reference': 'SNX', 'status': 'pending', 'amount': '1000', 'currency': 'TZS', 'phone': body['phone'], 'package': '1 Day'}
portal.safenet_api = fake
from http.server import ThreadingHTTPServer; portal.Server.server_bind = ThreadingHTTPServer.server_bind
srv = portal.Server(('127.0.0.1', 18083), portal.PortalHandler); threading.Thread(target=srv.serve_forever, daemon=True).start()
class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedir)
def req(path, data=None):
    try:
        r = op.open('http://127.0.0.1:18083' + path, urllib.parse.urlencode(data).encode() if data else None); return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e: return e.code, e.read(), e.headers
s, body, _ = req('/'); body = body.decode()
assert 'name="network" value="mixx"' in body and 'src="/img/airtel.png"' in body and 'M-Pesa' not in body
s, body, _ = req('/buy', {'package_id': '1', 'phone': '684123456', 'agree': '1'}); assert 'Choose your mobile-money network' in body.decode() and not sent
s, body, h = req('/buy', {'package_id': '1', 'phone': '684123456', 'agree': '1', 'network': 'airtel'})
assert s == 302 and sent[-1]['network'] == 'airtel' and sent[-1]['phone'] == '255684123456'
s, body, h = req('/img/airtel.png'); assert s == 200 and body[:4] == b'\x89PNG' and h['Content-Type'] == 'image/png'
assert req('/img/../../etc/passwd')[0] == 404 and req('/img/halopesa.png')[0] == 404 and req('/img/evil.png')[0] == 404
srv.shutdown(); print('GATEWAY NETWORKS OK')
