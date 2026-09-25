import os, re, sys, json
os.environ.update(DB_PASSWORD='x', PORTAL_API_KEY='gw-secret', CLICKPESA_CLIENT_ID='cid', CLICKPESA_API_KEY='ckey')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
from app import app, db
from models import Admin, Plan, Package, Payment, Voucher, RadCheck, RadUserGroup

calls = {'push': [], 'query': []}
state = {'status': 'PROCESSING', 'amount': '1000'}
def fake_push(amount, phone, ref, creds=None):
    calls['push'].append((amount, phone, ref)); return {'id': 'TX1', 'status': 'PROCESSING', 'channel': 'M-PESA'}
def fake_query(ref, creds=None):
    calls['query'].append(ref); return {'status': state['status'], 'collectedAmount': state['amount'], 'channel': 'M-PESA', 'orderReference': ref}
clickpesa.initiate_ussd_push = fake_push
clickpesa.query_payment = fake_query
clickpesa.preview_ussd_push = lambda amount, phone, ref, creds=None: ['M-PESA']

app.config.update(TESTING=True)
c = app.test_client()
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); __import__('migrations').run()
    a = Admin(username='admin', email='a@b.c', role='owner', tenant_id=__import__('migrations').default_tenant().id,
              email_verified_at=__import__('datetime').datetime.utcnow()); a.set_password('pw'); db.session.add(a)
    db.session.add(Plan(name='Fast10M')); db.session.commit(); __import__('migrations').run()
    plan_id = Plan.query.first().id

r = c.get('/login'); c.post('/login', data={'username': 'admin', 'password': 'pw', 'csrf_token': tok(r.text)})

# Package admin
r = c.get('/packages'); assert r.status_code == 200 and 'No packages yet' in r.text
r = c.get('/packages/add')
r = c.post('/packages/add', data={'csrf_token': tok(r.text), 'name': '1 Day', 'description': 'Unlimited', 'plan_id': plan_id,
    'price': '1000', 'validity_value': 1, 'validity_unit': 'days', 'sort_order': 1, 'is_active': 'y', 'show_on_portal': 'y', 'max_devices': 1}, follow_redirects=True)
assert 'Package &#34;1 Day&#34; created' in r.text or 'Package "1 Day" created' in r.text, r.text[:500]
r = c.get('/packages/add'); r = c.post('/packages/add', data={'csrf_token': tok(r.text), 'name': 'x', 'price': '50', 'validity_value': 1, 'validity_unit': 'hours'})
assert 'at least 100' in r.text
with app.app_context():
    pkg = Package.query.first(); assert pkg.validity_minutes == 1440 and pkg.plan_id == plan_id
    pkg_id = pkg.id
r = c.get(f'/packages/{pkg_id}/edit'); assert 'value="1000"' in r.text and 'selected' in r.text
r = c.post(f'/packages/{pkg_id}/edit', data={'csrf_token': tok(r.text), 'name': '1 Day', 'plan_id': plan_id, 'price': '1000', 'validity_value': 24, 'validity_unit': 'hours', 'is_active': 'y', 'show_on_portal': 'y'}, follow_redirects=True)
assert 'updated' in r.text

# API auth
g = app.test_client()
assert g.get('/api/portal/packages').status_code == 401
assert g.get('/api/portal/packages', headers={'X-SafeNet-Key': 'wrong'}).status_code == 401
H = {'X-SafeNet-Key': 'gw-secret'}
d = g.get('/api/portal/packages', headers=H).get_json()
assert d['payments_enabled'] and d['packages'][0]['price'] == '1000' and d['packages'][0]['validity'] == '1 day', d

# Purchase
bad = g.post('/api/portal/purchase', headers=H, json={'package_id': pkg_id, 'phone': '12345'})
assert bad.status_code == 400
r = g.post('/api/portal/purchase', headers=H, json={'package_id': pkg_id, 'phone': '0712 345 678', 'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '10.10.0.60', 'nas': 'devserver-gw'})
d = r.get_json(); assert r.status_code == 200 and d['status'] == 'pending' and d['phone'] == '255712345678', d
ref = d['reference']; assert re.fullmatch(r'SN[0-9A-F]{12}', ref)
assert calls['push'][-1][1] == '255712345678' and calls['push'][-1][0] == 1000
# duplicate within 90s blocked
assert g.post('/api/portal/purchase', headers=H, json={'package_id': pkg_id, 'phone': '+255712345678'}).status_code == 429

# Pending status
d = g.get(f'/api/portal/purchase/{ref}', headers=H).get_json(); assert d['status'] == 'pending' and 'code' not in d
# Paid via webhook (payload is only a hint; query decides)
state['status'] = 'SUCCESS'
assert c.post('/api/clickpesa/webhook', json={'event': 'PAYMENT RECEIVED', 'data': {'orderReference': ref}}).status_code == 200
d = g.get(f'/api/portal/purchase/{ref}', headers=H).get_json()
assert d['status'] == 'paid' and re.fullmatch(r'\d{8}', d['code']), d
code = d['code']
# idempotent: more polls/webhooks don't create more vouchers
c.post('/api/clickpesa/webhook', json={'data': {'orderReference': ref}})
g.get(f'/api/portal/purchase/{ref}', headers=H)
with app.app_context():
    v = Voucher.query.filter_by(code=code).one()
    assert Voucher.query.count() == 1 and v.batch == 'online-payments' and v.validity_minutes == 1440 and v.plan_id == plan_id
    assert RadCheck.query.filter_by(username=code, value=code).count() == 1
    assert RadUserGroup.query.filter_by(username=code, groupname='Fast10M').count() == 1
    p = Payment.query.filter_by(reference=ref).one(); assert p.paid_at and p.channel == 'M-PESA' and p.client_mac == 'aa:bb:cc:dd:ee:ff'

# Underpaid -> review, failed -> failed
with app.app_context():
    Payment.query.update({Payment.created_at: Payment.created_at}); db.session.commit()
state.update(status='PROCESSING')
r = g.post('/api/portal/purchase', headers=H, json={'package_id': pkg_id, 'phone': '0654 111 222'}); ref2 = r.get_json()['reference']
state.update(status='SUCCESS', amount='500')
d = g.get(f'/api/portal/purchase/{ref2}', headers=H).get_json(); assert d['status'] == 'review' and 'code' not in d, d
state.update(status='FAILED', amount='1000')
r = g.post('/api/portal/purchase', headers=H, json={'package_id': pkg_id, 'phone': '0689 000 111'}); ref3 = r.get_json()['reference']
d = g.get(f'/api/portal/purchase/{ref3}', headers=H).get_json(); assert d['status'] == 'failed'

# ClickPesa push error -> failed + 502
def boom(*a): raise clickpesa.ClickPesaError('400: Invalid phone')
clickpesa.initiate_ussd_push = boom
r = g.post('/api/portal/purchase', headers=H, json={'package_id': pkg_id, 'phone': '0677 123 456'})
assert r.status_code == 502 and r.get_json()['status'] == 'failed'

# Admin payments page
r = c.get('/payments'); assert r.status_code == 200 and code in r.text and '1,000' in r.text and 'Review' in r.text
assert c.get('/payments?status=paid').status_code == 200
# package delete keeps payment
r = c.get('/packages'); c.post(f'/packages/{pkg_id}/delete', data={'csrf_token': tok(r.text)})
with app.app_context(): assert Payment.query.count() == 4 and Package.query.count() == 0
assert g.get('/api/portal/packages', headers=H).get_json()['packages'] == []

# checksum matches ClickPesa's documented algorithm
config.Config.CLICKPESA_CHECKSUM_KEY = 'k'
import hmac, hashlib
exp = hmac.new(b'k', json.dumps({'amount':'1000','currency':'TZS','orderReference':'A1','phoneNumber':'255712345678'}, separators=(',',':')).encode(), hashlib.sha256).hexdigest()
assert clickpesa.checksum({'phoneNumber':'255712345678','orderReference':'A1','currency':'TZS','amount':'1000','checksum':'x'}) == exp
print('CLOUD OK')
