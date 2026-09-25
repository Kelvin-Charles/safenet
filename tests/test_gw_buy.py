import os, sys, threading, time, urllib.request, urllib.parse, http.cookiejar, re
os.environ.update(LAN_ADDR='127.0.0.1', LAN_PREFIX='8', PORTAL_PORT='18080', RADIUS_SERVER='x', RADIUS_SECRET='s',
                  SAFENET_API_URL='http://cloud.test', SAFENET_API_KEY='k', STATE_DIRECTORY=sys.argv[1])
sys.path.insert(0, 'gateway')
import portal
portal.mac_for_ip = lambda ip: 'aa:bb:cc:00:00:01'
portal.firewall_allow = lambda *a: None
portal.firewall_deny = lambda *a: None
portal._set_elements = lambda name: {}
portal.radius_account = lambda *a, **k: None
portal.radius_authenticate = lambda u, p, m, i: (u == '55556666', {27: [(86400).to_bytes(4, 'big')]})
state = {'status': 'pending', 'calls': []}
def fake_api(method, path, body=None, timeout=25):
    state['calls'].append((method, path, body))
    if path == '/api/portal/packages':
        return {'payments_enabled': True, 'packages': [{'id': 7, 'name': '1 Day <b>', 'price': '1000', 'currency': 'TZS', 'validity': '1 day', 'description': ''}]}
    if path == '/api/portal/purchase':
        if body['phone'] in ('bad', ''): raise portal.ApiError('Enter a valid mobile number, e.g. 0712 345 678.')
        return {'reference': 'SNABC123', 'status': 'pending', 'amount': '1000', 'currency': 'TZS', 'phone': '255712345678', 'package': '1 Day'}
    if path == '/api/gateway/auth':
        return {'ok': body['username'] == '55556666', 'session_timeout': 86400}
    if path in ('/api/gateway/accounting', '/api/gateway/sessions/check'):
        return {}
    if path.startswith('/api/portal/purchase/'):
        d = {'status': state['status'], 'message': 'Insufficient balance' if state['status'] == 'failed' else ''}
        if state['status'] == 'paid': d['code'] = '55556666'
        return d
portal.safenet_api = fake_api
srv = portal.Server(('127.0.0.1', 18080), portal.PortalHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedirect)
def get(path):
    try: r = op.open('http://127.0.0.1:18080' + path); return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), e.headers
def post(path, data):
    try: r = op.open('http://127.0.0.1:18080' + path, urllib.parse.urlencode(data).encode()); return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), e.headers

s, body, _ = get('/')
assert 'Buy package' in body and '1 Day &lt;b&gt;' in body and 'TZS 1,000' in body, body[-1500:]
s, body, _ = post('/buy', {'package_id': '7', 'phone': 'bad', 'agree': '1'})
assert 'Enter a valid mobile number' in body
s, body, _ = post('/buy', {'package_id': '7', 'phone': '0712345678'})
assert 'accept the terms' in body
s, body, h = post('/buy', {'package_id': '7', 'phone': '0712345678', 'agree': '1'})
assert s == 302 and '/buy/wait?ref=SNABC123' in h['Location'], (s, h.get('Location'))
s, body, _ = get('/buy/wait?ref=SNABC123')
assert 'Check your phone' in body and 'http-equiv="refresh"' in body and '255712345678' in body
assert get('/buy/wait?ref=OTHER')[0] == 302   # unknown ref / other device
portal.purchases['SNABC123']['created'] -= 1000
s, body, _ = get('/buy/wait?ref=SNABC123'); assert 'Still waiting' in body and 'refresh' not in body
s, body, _ = get('/buy/wait?ref=SNABC123&again=1'); assert 'Check your phone' in body
state['status'] = 'paid'
s, body, _ = get('/buy/wait?ref=SNABC123')
assert "You're online" in body and '55556666' in body and 'Payment received' in body and ('1d 0h' in body or '23h 59m' in body), body[-800:]
assert 'aa:bb:cc:00:00:01' in portal.sessions
s, body, _ = get('/'); assert "You're online" in body     # status page on revisit
# failed payment path
portal.sessions.clear(); state['status'] = 'pending'
post('/buy', {'package_id': '7', 'phone': '0712345678', 'agree': '1'})
state['status'] = 'failed'
s, body, _ = get('/buy/wait?ref=SNABC123'); assert 'Payment not completed: Insufficient balance' in body
# rate limit: 3 per 10 min (2 used + 1 bad earlier = 3)
s, body, _ = post('/buy', {'package_id': '7', 'phone': '0712345678', 'agree': '1'}); assert 'Too many payment requests' in body
# no packages -> buy section hidden
portal._packages_cache.update(at=time.time(), items=[])
s, body, _ = get('/'); assert 'Buy one' not in body and 'Enter your voucher' in body
srv.shutdown(); print('GATEWAY BUY OK')
