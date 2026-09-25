import os, re, sys, time
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS'}
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Voucher, RadCheck, Gateway, RadAcct, Package
app.config.update(TESTING=True)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='A', slug='a', status='active'); db.session.add(t); db.session.flush()
    db.session.add_all([Voucher(tenant_id=t.id, code='11112222', validity_minutes=60, batch='x', status='unused'),
                        RadCheck(username='11112222', attribute='Cleartext-Password', op=':=', value='11112222'),
                        Gateway(tenant_id=t.id, name='gw', key_prefix='sgw_a', key_hash=_hash_key('sgw_a')),
                        Package(tenant_id=t.id, name='Family', price=Decimal(3000), validity_minutes=1440, max_devices=2)])
    a = Admin(username='owner1', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    db.session.commit(); A = t.id; fam = Package.query.one().id
api = app.test_client(); H = {'X-SafeNet-Key': 'sgw_a'}
auth = lambda mac: api.post('/api/gateway/auth', headers=H, json={'username': '11112222', 'password': '11112222', 'mac': mac, 'ip': '10.10.0.9'}).get_json()
start = lambda mac, sid: api.post('/api/gateway/accounting', headers=H, json={'events': [{'type': 'start', 'session_id': sid, 'username': '11112222', 'mac': mac, 'ip': '10.10.0.9', 'time': int(time.time())}]})
assert auth('aa:aa:aa:aa:aa:01')['ok']; start('aa:aa:aa:aa:aa:01', 's1')
d = auth('aa:aa:aa:aa:aa:02'); assert not d['ok'] and 'another device' in d['message'], d        # second phone refused
assert auth('aa:aa:aa:aa:aa:01')['ok']                                                           # same phone can log in again
with app.app_context():                                                                         # stale session (>10 min) no longer blocks
    r = RadAcct.query.one(); r.acctupdatetime = r.acctstarttime = datetime.utcnow() - timedelta(minutes=11); db.session.commit()
assert auth('aa:aa:aa:aa:aa:02')['ok']
api.post('/api/gateway/accounting', headers=H, json={'events': [{'type': 'stop', 'session_id': 's1', 'username': '11112222', 'mac': 'aa:aa:aa:aa:aa:01', 'time': int(time.time())}]})
# package with 2 devices -> payment -> voucher allows 2
ref = api.post('/api/portal/purchase', headers=H, json={'package_id': fam, 'phone': '0684000111', 'network': 'airtel'}).get_json()['reference']
code = api.get(f'/api/portal/purchase/{ref}', headers=H).get_json()['code']
with app.app_context(): assert Voucher.query.filter_by(code=code).one().max_devices == 2
a2 = lambda mac: api.post('/api/gateway/auth', headers=H, json={'username': code, 'password': code, 'mac': mac}).get_json()
ev = lambda mac, sid: api.post('/api/gateway/accounting', headers=H, json={'events': [{'type': 'start', 'session_id': sid, 'username': code, 'mac': mac, 'time': int(time.time())}]})
assert a2('bb:00:00:00:00:01')['ok']; ev('bb:00:00:00:00:01', 'f1')
assert a2('bb:00:00:00:00:02')['ok']; ev('bb:00:00:00:00:02', 'f2')
assert not a2('bb:00:00:00:00:03')['ok']
# settings toggle reaches the gateway; forms carry devices
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner1', 'password': 'password1', 'csrf_token': tok(r.text)})
assert api.get('/api/gateway/config', headers=H).get_json()['block_tethering'] is True
r = c.get('/settings'); assert 'Block hotspot sharing' in r.text
c.post('/settings', data={'csrf_token': tok(r.text), 'name': 'A', 'currency': 'TZS'})
assert api.get('/api/gateway/config', headers=H).get_json()['block_tethering'] is False
r = c.get('/vouchers/generate'); assert 'Devices per voucher' in r.text
c.post('/vouchers/generate', data={'csrf_token': tok(r.text), 'plan_id': 0, 'count': 2, 'validity_value': 1, 'validity_unit': 'days', 'batch': 'fam', 'max_devices': 3})
with app.app_context(): assert {v.max_devices for v in Voucher.query.filter_by(batch='fam')} == {3}
r = c.get('/packages/add'); assert 'Devices allowed' in r.text
print('SHARING CLOUD OK')

# gateway: firewall rule management
sys.path.insert(0, 'gateway')
os.environ.update(LAN_IFS='wlp3s0 gwtest0', STATE_DIRECTORY=sys.argv[1], SAFENET_API_URL='https://x', SAFENET_API_KEY='k')
import portal
scripts = []
portal._nft = lambda s: scripts.append(s)
portal.apply_antishare(True)
assert 'iifname { "wlp3s0", "gwtest0" } ip ttl { 63, 127 } counter drop' in scripts[-1] and scripts[-1].startswith('flush chain inet safenet_gw antishare')
n = len(scripts); portal.apply_antishare(True); assert len(scripts) == n                      # no churn when unchanged
portal.safenet_api = lambda m, p, body=None, timeout=25: {'hotspot_name': 'X', 'block_tethering': False, 'portal': {}}
portal.refresh_branding(); assert 'drop' not in scripts[-1] and portal._antishare['enabled'] is False
print('SHARING GATEWAY OK')
