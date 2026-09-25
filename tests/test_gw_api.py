import os, sys, threading, time, urllib.request, urllib.parse
os.environ.update(LAN_ADDR='127.0.0.1', LAN_PREFIX='8', PORTAL_PORT='18081', SAFENET_API_URL='https://cloud.test',
                  SAFENET_API_KEY='sgw_k', STATE_DIRECTORY=sys.argv[1], HOTSPOT_NAME='Env Name')
sys.path.insert(0, 'gateway')
import portal
assert portal.API_MODE
assert portal.speed_kbytes('10M') == 1250 and portal.speed_kbytes('512k') == 64 and portal.speed_kbytes('1G') == 125000
assert portal.speed_kbytes('') is None and portal.speed_kbytes('abc') is None and portal.speed_kbytes('0') is None and portal.speed_kbytes('5') == 625
nft_scripts, calls = [], []
portal._nft = lambda script: nft_scripts.append(script)
portal.mac_for_ip = lambda ip: 'aa:bb:cc:00:00:02'
portal._set_elements = lambda name: {}
def fake_api(method, path, body=None, timeout=25):
    calls.append((path, body))
    if path == '/api/gateway/config':
        return {'hotspot_name': 'Tenant WiFi', 'support': '0755', 'terms': 'Be nice'}
    if path == '/api/gateway/auth':
        if body['password'] == '44445555':
            return {'ok': True, 'message': '', 'session_timeout': 1800, 'upload': '2M', 'download': '10M'}
        return {'ok': False, 'message': 'Voucher expired or disabled'}
    if path == '/api/gateway/accounting':
        return {'stored': 1}
    if path == '/api/portal/packages':
        return {'payments_enabled': False, 'packages': []}
portal.safenet_api = fake_api
def no_radius(*a): raise AssertionError('RADIUS must not be used in API mode')
portal.radius_authenticate = no_radius
portal.refresh_branding()
assert portal.branding == {'name': 'Tenant WiFi', 'support': '0755', 'terms': 'Be nice'}
from http.server import ThreadingHTTPServer; portal.Server.server_bind = ThreadingHTTPServer.server_bind
srv = portal.Server(('127.0.0.1', 18081), portal.PortalHandler); threading.Thread(target=srv.serve_forever, daemon=True).start()
def post(path, data):
    return urllib.request.urlopen('http://127.0.0.1:18081' + path, urllib.parse.urlencode(data).encode()).read().decode()
body = urllib.request.urlopen('http://127.0.0.1:18081/').read().decode()
assert 'Tenant WiFi' in body and 'Need help?' in body and '>0755<' in body and 'Be nice' in body and 'Env Name' not in body
body = post('/login', {'code': '99999999', 'agree': '1'}); assert 'Voucher expired or disabled' in body
body = post('/login', {'code': '44445555', 'agree': '1'}); assert "You're online" in body and ('30 min' in body or '29 min' in body), body[-500:]
s = portal.sessions['aa:bb:cc:00:00:02']; assert s['up_limit'] == '2M' and s['down_limit'] == '10M'
rl = [x for x in nft_scripts if 'ratelimit' in x][-1]
assert 'ip saddr 127.0.0.1 limit rate over 250 kbytes/second' in rl and 'ip daddr 127.0.0.1 limit rate over 1250 kbytes/second' in rl, rl
time.sleep(0.5)
starts = [b['events'][0] for p, b in calls if p == '/api/gateway/accounting' and b['events'][0]['type'] == 'start']
assert starts and starts[0]['username'] == '44445555'
post('/logout', {})
time.sleep(0.5)
stops = [b['events'][0] for p, b in calls if p == '/api/gateway/accounting' and b['events'][0]['type'] == 'stop']
assert stops and stops[0]['terminate_cause'] == 'User-Request'
assert 'limit rate' not in [x for x in nft_scripts if 'ratelimit' in x][-1]   # limits removed with the session
srv.shutdown(); print('GATEWAY API OK')
