import os, sys, time
os.environ.update(LAN_ADDR='127.0.0.1', LAN_PREFIX='8', SAFENET_API_URL='https://cloud.test', SAFENET_API_KEY='k', STATE_DIRECTORY=sys.argv[1])
sys.path.insert(0, 'gateway')
import portal
denied, accounted = [], []
portal.firewall_deny = lambda mac, ip: denied.append(mac)
portal._set_elements = lambda name: {}
portal._nft = lambda s: None
portal.account = lambda status, s, cause=None: accounted.append((status, s['user'], cause))
answer = {'disconnect': ['v1']}
def fake_api(method, path, body=None, timeout=25):
    assert path == '/api/gateway/sessions/check'
    if answer == 'suspended': raise portal.ApiError('This network is suspended.')
    if answer == 'down': raise portal.ApiError('SafeNet unreachable: timeout')
    assert sorted(body['usernames']) == sorted({s['user'] for s in portal.sessions.values()})
    return answer
portal.safenet_api = fake_api
now = time.time()
def add(mac, user):
    portal.sessions[mac] = {'mac': mac, 'ip': '10.10.0.' + mac[-1], 'user': user, 'sid': mac, 'start': now, 'expires': now + 600, 'up': 0, 'down': 0}
add('aa:01', 'v1'); add('aa:02', 'v1'); add('aa:03', 'v2')
assert portal.check_revocations() == 2 and set(denied) == {'aa:01', 'aa:02'} and set(portal.sessions) == {'aa:03'}
time.sleep(0.2); assert all(a[0] == portal.ACCT_STOP and a[2] == portal.TERM_ADMIN_RESET for a in accounted)
answer = 'down'; assert portal.check_revocations() == 0 and 'aa:03' in portal.sessions      # cloud unreachable: keep guests online
answer = 'suspended'; assert portal.check_revocations() == 1 and not portal.sessions
answer = {'disconnect': []}; assert portal.check_revocations() == 0                          # nobody online: no call needed
print('GATEWAY REVOKE OK')
