"""Gateway box: a phone that already paid and reconnects (new address) is let back in without the code."""
import os, sys, threading, time, urllib.request
os.environ.update(LAN_ADDR='127.0.0.1', LAN_PREFIX='8', PORTAL_PORT='18086', SAFENET_API_URL='https://cloud.test', SAFENET_API_KEY='k',
                  STATE_DIRECTORY=sys.argv[1])
sys.path.insert(0, 'gateway')
import portal
portal.mac_for_ip = lambda ip: 'aa:bb:cc:00:00:07'
portal.wire_mac_for_ip = lambda ip: 'aa:bb:cc:00:00:07'
portal._nft = lambda script: None
portal._background = lambda fn, *a: None
calls = []
state = {'code': '12341234'}
def fake_api(method, path, body=None, timeout=25):
    calls.append(path)
    if path == '/api/gateway/returning':
        return {'code': state['code']} if state['code'] else {}
    if path == '/api/gateway/auth':
        return {'ok': body['username'] == '12341234', 'session_timeout': 3000}
    if path == '/api/portal/packages':
        return {'packages': [], 'payments_enabled': False}
    return {}
portal.safenet_api = fake_api
srv = portal.Server(('127.0.0.1', 18086), portal.PortalHandler); threading.Thread(target=srv.serve_forever, daemon=True).start()
get = lambda: urllib.request.urlopen('http://127.0.0.1:18086/').read().decode()

body = get()
assert "You're online" in body and '12341234' in body, body[-800:]
assert 'aa:bb:cc:00:00:07' in portal.sessions and portal.sessions['aa:bb:cc:00:00:07']['user'] == '12341234'
assert 2900 < portal.sessions['aa:bb:cc:00:00:07']['expires'] - time.time() <= 3000
# already online: no more questions to SafeNet
n = len(calls); get(); assert len(calls) == n
# nothing paid: login page, and SafeNet is not asked again for a minute
portal.sessions.clear(); state['code'] = None; portal._not_returning.clear()
assert "You're online" not in get()
n = len(calls); get(); assert calls[n:].count('/api/gateway/returning') == 0
srv.shutdown()
print('GATEWAY RETURNING OK')
