import os, re, sys, time
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Plan, RadUser, RadCheck, Voucher, Gateway, RadAcct, RadPostAuth, RadGroupReply, PlanAttribute
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    ta = Tenant(name='Cafe A', slug='cafe-a', status='active', hotspot_name='A WiFi', support_phone='0700'); tb = Tenant(name='B', slug='b', status='active')
    db.session.add_all([ta, tb]); db.session.flush()
    pa = Plan(tenant_id=ta.id, name='Fast', group_name='t-a-fast', upload_speed='2M', download_speed='10M')
    db.session.add(pa); db.session.flush()
    now = datetime.utcnow()
    db.session.add_all([
        Voucher(tenant_id=ta.id, code='11110001', plan_id=pa.id, validity_minutes=60, batch='x', status='unused'),
        Voucher(tenant_id=ta.id, code='11110002', validity_minutes=60, batch='x', status='active', first_used_at=now - timedelta(hours=2), expires_at=now - timedelta(hours=1)),
        Voucher(tenant_id=tb.id, code='22220001', validity_minutes=60, batch='y', status='unused'),
        RadUser(tenant_id=ta.id, username='alice', plan_id=pa.id, is_active=True, download_speed='20M'),
        RadUser(tenant_id=ta.id, username='bob', is_active=False),
    ])
    for u in ('11110001', '11110002', '22220001', 'alice', 'bob'):
        db.session.add(RadCheck(username=u, attribute='Cleartext-Password', op=':=', value=u if u[0].isdigit() else 'pw'))
    db.session.add(Gateway(tenant_id=ta.id, name='Cafe box', key_prefix='sgw_aaaa', key_hash=_hash_key('sgw_akey')))
    admin = Admin(username='owner', email='o@a.tz', tenant_id=ta.id, role='owner', email_verified_at=now); admin.set_password('pw123456')
    db.session.add(admin); db.session.commit()
    A = ta.id

c = app.test_client(); H = {'X-SafeNet-Key': 'sgw_akey'}
auth = lambda u, p: c.post('/api/gateway/auth', headers=H, json={'username': u, 'password': p, 'mac': 'aa:bb:cc:dd:ee:01', 'ip': '10.10.0.60'}).get_json()
assert c.post('/api/gateway/auth', json={'username': 'x'}).status_code == 401
d = auth('11110001', '11110001')
assert d['ok'] and 3500 <= d['session_timeout'] <= 3600 and d['upload'] == '2M' and d['download'] == '10M', d
with app.app_context():
    v = Voucher.query.filter_by(code='11110001').one(); assert v.status == 'active' and v.expires_at
    first_exp = v.expires_at
d = auth('11110001', '11110001'); assert d['ok'] and d['session_timeout'] <= 3600   # second login: clock not restarted
with app.app_context(): assert Voucher.query.filter_by(code='11110001').one().expires_at == first_exp
assert auth('11110001', 'wrong')['ok'] is False
assert auth('22220001', '22220001')['ok'] is False            # tenant B's voucher on A's gateway
d = auth('11110002', '11110002'); assert not d['ok'] and 'expired' in d['message']
d = auth('alice', 'pw'); assert d['ok'] and d['session_timeout'] is None and d['upload'] == '2M' and d['download'] == '20M', d
d = auth('bob', 'pw'); assert not d['ok'] and 'disabled' in d['message']
with app.app_context():
    assert RadPostAuth.query.filter_by(reply='Access-Accept').count() == 3 and RadPostAuth.query.filter_by(reply='Access-Reject').count() == 4

cfg = c.get('/api/gateway/config', headers=H).get_json()
assert cfg['hotspot_name'] == 'A WiFi' and cfg['support'] == '0700' and cfg['gateway'] == 'Cafe box'

t0 = int(time.time())
ev = lambda kind, **kw: {'type': kind, 'session_id': 'sess1', 'username': 'alice', 'mac': 'aa:bb:cc:dd:ee:01', 'ip': '10.10.0.60', 'time': t0, **kw}
r = c.post('/api/gateway/accounting', headers=H, json={'events': [ev('start'), {**ev('start'), 'username': '22220001', 'session_id': 'evil'}]}).get_json()
assert r['stored'] == 1                                        # B's username ignored
c.post('/api/gateway/accounting', headers=H, json={'events': [ev('interim', input_octets=1000, output_octets=50000, session_time=60, time=t0 + 60)]})
with app.app_context():
    row = RadAcct.query.one(); assert row.acctoutputoctets == 50000 and row.acctstoptime is None and row.calledstationid == 'Cafe box'
c.post('/api/gateway/accounting', headers=H, json={'events': [ev('stop', input_octets=2000, output_octets=90000, session_time=120, time=t0 + 120, terminate_cause='Session-Timeout')]})
with app.app_context():
    row = RadAcct.query.one(); assert row.acctstoptime and row.acctinputoctets == 2000 and row.acctsessiontime == 120 and row.acctterminatecause == 'Session-Timeout'
# interim without start (start lost) creates the row
c.post('/api/gateway/accounting', headers=H, json={'events': [{**ev('interim', output_octets=5, session_time=30), 'session_id': 'sess2'}]})
with app.app_context(): assert RadAcct.query.count() == 2

# plan speeds -> Mikrotik-Rate-Limit (and a manual attribute wins)
wc = app.test_client(); r = wc.get('/login'); wc.post('/login', data={'username': 'owner', 'password': 'pw123456', 'csrf_token': tok(r.text)})
r = wc.get('/plans/add'); wc.post('/plans/add', data={'csrf_token': tok(r.text), 'name': 'Slow', 'vendor': 'mikrotik', 'is_active': 'y', 'upload_speed': '1M', 'download_speed': '3M'})
with app.app_context():
    slow = Plan.query.filter_by(name='Slow').one()
    assert RadGroupReply.query.filter_by(groupname=slow.group_name, attribute='Mikrotik-Rate-Limit').one().value == '1M/3M'
    sid = slow.id
r = wc.get(f'/plans/edit/{sid}'); wc.post(f'/plans/edit/{sid}', data={'csrf_token': tok(r.text), 'name': 'Slow', 'vendor': 'mikrotik', 'is_active': 'y', 'upload_speed': '', 'download_speed': ''})
with app.app_context(): assert RadGroupReply.query.filter_by(groupname=slow.group_name, attribute='Mikrotik-Rate-Limit').count() == 0
print('PHASE2 CLOUD OK')
