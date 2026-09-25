import os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', CLICKPESA_CLIENT_ID='platform-id', CLICKPESA_API_KEY='platform-key', PLATFORM_FEE_PERCENT='5', MIN_WITHDRAWAL='500', SECRET_KEY='test-secret-key-long-enough')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa, secretbox
used = []
clickpesa.preview_ussd_push = lambda a, p, r, c=None: used.append(('preview', c.client_id)) or ['M-PESA']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: used.append(('push', c.client_id)) or {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: used.append(('query', c.client_id)) or {'status': 'SUCCESS', 'collectedAmount': '2000'}
def fake_test(c):
    if c.api_key != 'b-secret-key': raise clickpesa.ClickPesaError('401: Invalid')
clickpesa.test_credentials = fake_test
outbox = []
import app as appmod
appmod.send_mail = lambda to, subj, body: outbox.append((to, subj, body)) or True
from app import app, db, _hash_key, tenant_balance
import migrations
from models import Admin, Tenant, Package, Payment, Gateway, Withdrawal
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)

assert secretbox.decrypt(secretbox.encrypt('abc')) == 'abc' and secretbox.decrypt('garbage') == '' and secretbox.encrypt('') is None

with app.app_context():
    db.create_all(); migrations.run()
    now = datetime.utcnow()
    ta = Tenant(name='A', slug='a', status='active', fee_percent=Decimal('10')); tb = Tenant(name='B', slug='b', status='active')
    db.session.add_all([ta, tb]); db.session.flush()
    A, B = ta.id, tb.id
    for t, key in ((ta, 'sgw_a'), (tb, 'sgw_b')):
        db.session.add(Package(tenant_id=t.id, name='Day', price=Decimal(2000), validity_minutes=1440, currency='TZS'))
        db.session.add(Gateway(tenant_id=t.id, name='gw', key_prefix=key[:8], key_hash=_hash_key(key)))
    for u, t, role, sa in (('ownera', A, 'owner', False), ('admina', A, 'admin', False), ('ownerb', B, 'owner', False), ('boss', 1, 'owner', True)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=t, role=role, is_superadmin=sa, email_verified_at=now); a.set_password('password1'); db.session.add(a)
    db.session.commit()
    pkg = {t: Package.query.filter_by(tenant_id=t).one().id for t in (A, B)}

def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
api = app.test_client()
def buy(key, tid, phone):
    r = api.post('/api/portal/purchase', headers={'X-SafeNet-Key': key}, json={'package_id': pkg[tid], 'phone': phone}).get_json()
    return api.get(f"/api/portal/purchase/{r['reference']}", headers={'X-SafeNet-Key': key}).get_json(), r['reference']

# --- A: platform mode, 10 % fee
d, ref = buy('sgw_a', A, '0684000001'); assert d['status'] == 'paid'
assert ('push', 'platform-id') in used and ('query', 'platform-id') in used
with app.app_context():
    p = Payment.query.filter_by(reference=ref).one(); assert p.provider_account == 'platform' and p.fee_amount == Decimal('200.00') and p.net_amount == Decimal('1800.00')
    assert tenant_balance(A)[0] == Decimal('1800')

# --- B: switch to own ClickPesa
cb = login('ownerb')
r = cb.get('/settings/payments'); r = cb.post('/settings/payments', data={'csrf_token': tok(r.text), 'payment_mode': 'own', 'client_id': ''}, follow_redirects=True)
assert 'Enter your ClickPesa Client ID' in r.text
r = cb.get('/settings/payments'); cb.post('/settings/payments', data={'csrf_token': tok(r.text), 'payment_mode': 'own', 'client_id': 'b-client', 'api_key': 'wrong'})
r = cb.get('/settings/payments'); assert 'saved' in r.text
r = cb.post('/settings/payments/test', data={'csrf_token': tok(r.text)}, follow_redirects=True); assert 'rejected the keys' in r.text
r = cb.get('/settings/payments'); cb.post('/settings/payments', data={'csrf_token': tok(r.text), 'payment_mode': 'own', 'client_id': 'b-client', 'api_key': 'b-secret-key'})
r = cb.get('/settings/payments'); r = cb.post('/settings/payments/test', data={'csrf_token': tok(r.text)}, follow_redirects=True); assert 'ClickPesa accepted your keys' in r.text
with app.app_context():
    t = db.session.get(Tenant, B); assert t.payment_mode == 'own' and t.clickpesa_api_key_enc and 'b-secret-key' not in t.clickpesa_api_key_enc
used.clear()
d, ref = buy('sgw_b', B, '0684000002'); assert d['status'] == 'paid'
assert ('push', 'b-client') in used and ('query', 'b-client') in used and not any(c == 'platform-id' for _, c in used)
with app.app_context():
    p = Payment.query.filter_by(reference=ref).one(); assert p.provider_account == 'own' and p.fee_amount == 0 and p.net_amount == Decimal('2000')
    assert tenant_balance(B)[0] == 0          # own-mode money is not held by the platform
# webhook for B's payment re-queries with B's keys
used.clear(); api.post('/api/clickpesa/webhook', json={'data': {'orderReference': ref}})
r = cb.get('/earnings'); assert 'straight into your own ClickPesa' in r.text

# --- withdrawals (owner only)
ca = login('ownera'); cad = login('admina')
r = cad.get('/earnings'); assert r.status_code == 200 and 'Request withdrawal' not in r.text
assert cad.post('/earnings/withdraw', data={'csrf_token': tok(r.text), 'amount': 1000, 'phone': '0684000009'}).status_code == 302
with app.app_context(): assert Withdrawal.query.count() == 0
r = ca.get('/earnings'); assert '1,800' in r.text and 'Request withdrawal' in r.text
r = ca.post('/earnings/withdraw', data={'csrf_token': tok(r.text), 'amount': 400, 'phone': '0684000009'}, follow_redirects=True); assert 'minimum withdrawal' in r.text
r = ca.post('/earnings/withdraw', data={'csrf_token': tok(r.text), 'amount': 5000, 'phone': '0684000009'}, follow_redirects=True); assert 'up to TZS 1,800' in r.text
r = ca.post('/earnings/withdraw', data={'csrf_token': tok(r.text), 'amount': 1200, 'phone': '0712 000 009', 'account_name': 'Asha'}, follow_redirects=True)
assert 'Withdrawal of TZS 1,200 requested' in r.text and any('boss@x.tz' == o[0] for o in outbox)
with app.app_context(): assert tenant_balance(A)[0] == Decimal('600')
r = ca.post('/earnings/withdraw', data={'csrf_token': tok(r.text), 'amount': 1000, 'phone': '0684000009'}, follow_redirects=True); assert 'up to TZS 600' in r.text

# --- platform payouts
cs = login('boss')
r = cs.get('/platform/payouts'); assert 'Asha' in r.text and '1,200' in r.text
with app.app_context(): wid = Withdrawal.query.one().id
r = cs.post(f'/platform/payouts/{wid}', data={'csrf_token': tok(r.text), 'action': 'paid'}, follow_redirects=True); assert 'transaction reference' in r.text
r = cs.post(f'/platform/payouts/{wid}', data={'csrf_token': tok(r.text), 'action': 'paid', 'reference': 'MP123'}, follow_redirects=True)
assert 'marked paid' in r.text and outbox[-1][0] == 'ownera@x.tz' and 'MP123' in outbox[-1][2]
r = cs.post(f'/platform/payouts/{wid}', data={'csrf_token': tok(r.text), 'action': 'reject'}, follow_redirects=True); assert 'already processed' in r.text
with app.app_context(): assert tenant_balance(A)[0] == Decimal('600')
# a rejected request returns the money
r = ca.get('/earnings'); ca.post('/earnings/withdraw', data={'csrf_token': tok(r.text), 'amount': 600, 'phone': '0684000009'})
with app.app_context(): w2 = Withdrawal.query.filter_by(status='requested').one().id; assert tenant_balance(A)[0] == 0
r = cs.get('/platform/payouts'); cs.post(f'/platform/payouts/{w2}', data={'csrf_token': tok(r.text), 'action': 'reject', 'note': 'wrong number'})
with app.app_context(): assert tenant_balance(A)[0] == Decimal('600')
assert 'wrong number' in outbox[-1][2]
# tenants cannot open payouts
assert ca.get('/platform/payouts').status_code == 404

# --- fee settings
r = cs.get('/platform/tenants'); assert 'owed' in r.text
cs.post(f'/platform/tenants/{A}/fee', data={'csrf_token': tok(r.text), 'fee_percent': '99'})
with app.app_context(): assert db.session.get(Tenant, A).fee_percent == Decimal('10')
cs.post(f'/platform/tenants/{A}/fee', data={'csrf_token': tok(r.text), 'fee_percent': ''})
d, ref = buy('sgw_a', A, '0684000003')
with app.app_context(): assert Payment.query.filter_by(reference=ref).one().fee_amount == Decimal('100.00')   # default 5 %
print('PHASE3 OK')
