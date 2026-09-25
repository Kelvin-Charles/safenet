import os, sys, time, json
state = sys.argv[1]
leases = os.path.join(state, 'leases')
os.environ.update(LAN_ADDR='127.0.0.1', LAN_PREFIX='8', SAFENET_API_URL='https://cloud.test', SAFENET_API_KEY='k',
                  STATE_DIRECTORY=state, LEASE_FILE=leases)
sys.path.insert(0, 'gateway')
import portal

REPEATER = '8e:d7:33:15:fb:52'
with open(leases, 'w') as f:
    f.write(f'1790211139 56:9b:d6:4e:39:f6 10.10.0.166 phone-a 01:56:9b:d6:4e:39:f6\n'
            f'1790211002 50:0f:f5:e7:9e:68 10.10.0.118 * 01:50:0f:f5:e7:9e:68\n')
arp = {'10.10.0.166': REPEATER, '10.10.0.118': REPEATER, '10.10.0.200': 'aa:aa:aa:aa:aa:aa'}
portal.wire_mac_for_ip = lambda ip: arp.get(ip)
nft = []
portal._nft = lambda script: nft.append(script)
portal._background = lambda fn, *a: None
portal.authenticate = lambda u, p, mac, ip: (True, '', 600, None, None)

# The device's real MAC comes from the DHCP lease, not the repeater's MAC on the wire
assert portal.mac_for_ip('10.10.0.166') == '56:9b:d6:4e:39:f6'
assert portal.mac_for_ip('10.10.0.118') == '50:0f:f5:e7:9e:68'
assert portal.mac_for_ip('10.10.0.200') == 'aa:aa:aa:aa:aa:aa'      # no lease: fall back to ARP

# Phone A behind the repeater logs in: access is for repeater MAC + A's IP only
s, err = portal.login('56:9b:d6:4e:39:f6', '10.10.0.166', 'CODE1', 'CODE1')
assert not err and s['wire'] == REPEATER and s['mac'] == '56:9b:d6:4e:39:f6'
assert f'allowed {{ {REPEATER} . 10.10.0.166 timeout' in nft[-1], nft[-1]
assert '10.10.0.118' not in ''.join(nft)                              # phone B is not let in
# Phone B's own login is a separate session (no collision on the shared MAC)
s2, err = portal.login('50:0f:f5:e7:9e:68', '10.10.0.118', 'CODE2', 'CODE2')
assert not err and len(portal.sessions) == 2 and portal.sessions['56:9b:d6:4e:39:f6']['user'] == 'CODE1'

# Accounting sees the concatenated set elements and keeps both sessions
portal._set_elements = lambda name: ({f'{REPEATER} . 10.10.0.166': 0, f'{REPEATER} . 10.10.0.118': 0}
                                     if name == 'allowed' else {})
now = time.time()
alive = {f'{REPEATER} . 10.10.0.166', f'{REPEATER} . 10.10.0.118'}
for mac, sess in list(portal.sessions.items()):
    assert f"{portal.wire_of(sess)} . {sess['ip']}" in alive

# Phone A walks to the main access point: same IP, its own MAC on the wire -> access follows
arp['10.10.0.166'] = '56:9b:d6:4e:39:f6'
nft.clear()
portal.follow_device(portal.sessions['56:9b:d6:4e:39:f6'])
assert f'delete element inet safenet_gw allowed {{ {REPEATER} . 10.10.0.166 }}' in nft[0]
assert 'allowed { 56:9b:d6:4e:39:f6 . 10.10.0.166 timeout' in nft[0]
assert portal.sessions['56:9b:d6:4e:39:f6']['wire'] == '56:9b:d6:4e:39:f6'
nft.clear(); portal.follow_device(portal.sessions['56:9b:d6:4e:39:f6']); assert not nft   # nothing to move

# Ending a session removes exactly that MAC+IP pair
portal.end_session('50:0f:f5:e7:9e:68', portal.TERM_USER_REQUEST)
assert f'delete element inet safenet_gw allowed {{ {REPEATER} . 10.10.0.118 }}' in nft[-1]

# Sessions saved by the previous version (no 'wire') restore with their MAC as the wire MAC
with open(portal.STATE_FILE, 'w') as f:
    json.dump({'8e:d7:33:15:fb:52': {'mac': REPEATER, 'ip': '10.10.0.145', 'user': 'OLD', 'sid': 'x',
                                     'start': now, 'expires': now + 600, 'up': 0, 'down': 0}}, f)
portal.sessions.clear(); nft.clear()
portal.load_sessions()
assert f'allowed {{ {REPEATER} . 10.10.0.145 timeout' in nft[0]

# _set_elements parses nft's JSON for concatenated keys
portal._set_elements = portal.__dict__['_set_elements']
import subprocess
out = json.dumps({'nftables': [{'set': {'elem': [{'elem': {'val': {'concat': ['8E:D7:33:15:FB:52', '10.10.0.166']}, 'timeout': 60}}]}}]})
real_run = subprocess.run
subprocess.run = lambda *a, **k: type('R', (), {'stdout': out})()
import importlib; importlib.reload(portal)
subprocess.run = lambda *a, **k: type('R', (), {'stdout': out})()
assert portal._set_elements('allowed') == {'8e:d7:33:15:fb:52 . 10.10.0.166': 0}
subprocess.run = real_run
print('repeater OK')
