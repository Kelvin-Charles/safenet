import os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='pid', CLICKPESA_API_KEY='pkey', BILLING_GRACE_DAYS='3')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
cp_state = {'status': 'SUCCESS', 'amount': None}
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['M-PESA']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': cp_state['status'], 'collectedAmount': cp_state['amount']}
outbox = []
import app as appmod
appmod.send_mail = lambda to, subj, body: outbox.append((to, subj, body)) or True
from app import app, db, _hash_key, billing_state, send_billing_reminders
import migrations
from models import Admin, Tenant, Gateway, BillingPlan, SubscriptionPayment, Router
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow

with app.app_context():
    db.create_all(); migrations.run(); __import__("models").BillingPlan.query.delete(); db.session.commit()
    boss = Admin(username='platform', email='p@x.tz', tenant_id=migrations.default_tenant().id, role='owner', is_superadmin=True, email_verified_at=now())
    boss.set_password('password1'); db.session.add(boss); db.session.commit()

def login(u, pw='password1'):
    c = app.test_client(); r = c.get('/login'); r = c.post('/login', data={'username': u, 'password': pw, 'csrf_token': tok(r.text)}, follow_redirects=True); return c, r
def form_tok(c): return re.search(r'name="csrf-token" content="([^"]+)"', c.get('/billing').text).group(1)

# signup -> trial with service_until = trial end + grace
c = app.test_client(); r = c.get('/signup')
c.post('/signup', data={'csrf_token': tok(r.text), 'business_name': 'Cafe', 'username': 'owner1', 'email': 'o@cafe.tz', 'password': 'password1', 'confirm': 'password1', 'accept': 'y'})
with app.app_context():
    t = Tenant.query.filter_by(slug='cafe').one(); owner = Admin.query.filter_by(username='owner1').one()
    owner.email_verified_at = now(); A = t.id
    assert abs((t.service_until - t.trial_ends_at) - timedelta(days=3)) < timedelta(seconds=1)
    admin2 = Admin(username='admin1', email='a@cafe.tz', tenant_id=A, role='admin', email_verified_at=now()); admin2.set_password('password1')
    db.session.add_all([admin2, Gateway(tenant_id=A, name='gw', key_prefix='sgw_c', key_hash=_hash_key('sgw_c'))]); db.session.commit()
    assert billing_state(migrations.default_tenant())['state'] == 'complimentary'
co, r = login('owner1'); assert 'Free trial: 14 days left' in r.text
api = app.test_client(); H = {'X-SafeNet-Key': 'sgw_c'}
assert api.get('/api/gateway/config', headers=H).status_code == 200

# trial ended -> grace: still works, warning shown
with app.app_context():
    t = db.session.get(Tenant, A); t.trial_ends_at = now() - timedelta(days=1); appmod.refresh_service_until(t); db.session.commit()
    assert billing_state(t)['state'] == 'grace'
r = co.get('/dashboard'); assert r.status_code == 200 and 'has ended' in r.text
assert api.get('/api/gateway/config', headers=H).status_code == 200
# past grace -> expired: dashboard locked to billing, gateway refused
with app.app_context():
    t = db.session.get(Tenant, A); t.trial_ends_at = now() - timedelta(days=5); appmod.refresh_service_until(t); db.session.commit()
    assert billing_state(t)['state'] == 'expired'
r = co.get('/dashboard'); assert r.status_code == 302 and '/billing' in r.headers['Location']
r = co.get('/billing'); assert r.status_code == 200 and 'Wi-Fi is paused' in r.text and 'No plans are available' in r.text
assert api.get('/api/gateway/config', headers=H).status_code == 403
ca, _ = login('admin1'); assert ca.get('/vouchers').status_code == 302 and 'Only the account owner can pay' in ca.get('/billing').text

# platform creates plans
cp, _ = login('platform')
cp.post('/platform/billing', data={'csrf_token': tok(cp.get('/platform/billing').text), 'name': 'Starter', 'price': '20000', 'max_routers': '1', 'max_gateways': '', 'is_active': '1'})
cp.post('/platform/billing', data={'csrf_token': tok(cp.get('/platform/billing').text), 'name': 'Bad', 'price': 'abc'})
with app.app_context():
    plans = BillingPlan.query.all(); assert [p.name for p in plans] == ['Starter'] and plans[0].max_routers == 1 and plans[0].max_gateways is None
    pid = plans[0].id

# admin cannot pay; owner pays 3 months
assert ca.post('/billing/pay', data={'csrf_token': form_tok(ca), 'plan_id': pid, 'months': 3, 'phone': '0712000001'}).status_code == 302
with app.app_context(): assert SubscriptionPayment.query.count() == 0
r = co.post('/billing/pay', data={'csrf_token': form_tok(co), 'plan_id': pid, 'months': 5, 'phone': '0712000001'}, follow_redirects=True); assert 'Choose a plan and a period' in r.text
r = co.post('/billing/pay', data={'csrf_token': form_tok(co), 'plan_id': pid, 'months': 3, 'phone': '0712 000 001'})
ref = r.headers['Location'].rsplit('/', 1)[1]; assert ref.startswith('SB')
assert 'Check your phone' in co.get(f'/billing/payments/{ref}').text and 'TZS 60,000' in co.get(f'/billing/payments/{ref}').text
d = co.get(f'/billing/payments/{ref}/status').get_json(); assert d['status'] == 'paid', d
with app.app_context():
    t = db.session.get(Tenant, A); sp = SubscriptionPayment.query.filter_by(reference=ref).one()
    assert t.status == 'active' and t.billing_plan_id == pid and sp.amount == Decimal('60000')
    assert abs(t.paid_until - (now() + timedelta(days=90))) < timedelta(minutes=1) and t.service_until == t.paid_until + timedelta(days=3)
    first_until = t.paid_until
assert any('renewed' in o[1] and o[0] == 'o@cafe.tz' for o in outbox)
assert co.get('/dashboard').status_code == 200 and api.get('/api/gateway/config', headers=H).status_code == 200
# another tenant can't see this payment
cp.post(f'/platform/switch/{migrations.default_tenant().id if False else 1}', data={'csrf_token': tok(cp.get('/platform/tenants').text)})

# paying early adds after the current period (via webhook this time)
cp_state['status'] = 'PROCESSING'
r = co.post('/billing/pay', data={'csrf_token': form_tok(co), 'plan_id': pid, 'months': 1, 'phone': '0712000001'}); ref2 = r.headers['Location'].rsplit('/', 1)[1]
assert co.get(f'/billing/payments/{ref2}/status').get_json()['status'] == 'pending'
cp_state['status'] = 'SUCCESS'
app.test_client().post('/api/clickpesa/webhook', json={'data': {'orderReference': ref2}})
with app.app_context(): assert db.session.get(Tenant, A).paid_until == first_until + timedelta(days=30)
# underpaid -> review, failed -> failed
cp_state.update(status='SUCCESS', amount='100')
r = co.post('/billing/pay', data={'csrf_token': form_tok(co), 'plan_id': pid, 'months': 1, 'phone': '0712000001'}); ref3 = r.headers['Location'].rsplit('/', 1)[1]
assert co.get(f'/billing/payments/{ref3}/status').get_json()['status'] == 'review'
cp_state.update(status='FAILED', amount=None)
r = co.post('/billing/pay', data={'csrf_token': form_tok(co), 'plan_id': pid, 'months': 1, 'phone': '0712000001'}); ref4 = r.headers['Location'].rsplit('/', 1)[1]
assert co.get(f'/billing/payments/{ref4}/status').get_json()['status'] == 'failed'
with app.app_context(): assert db.session.get(Tenant, A).paid_until == first_until + timedelta(days=30)
assert cp.get(f'/billing/payments/{ref}/status').status_code == 404        # platform admin is in its own tenant

# plan limit: 1 router
t0 = tok(co.get('/routers').text)
co.post('/routers/add', data={'csrf_token': t0, 'name': 'r1', 'vendor': 'mikrotik'})
r = co.post('/routers/add', data={'csrf_token': t0, 'name': 'r2', 'vendor': 'mikrotik'}, follow_redirects=True)
assert 'does not allow more routers' in r.text
with app.app_context(): assert Router.query.filter_by(tenant_id=A).count() == 1

# platform manual actions
st = lambda action: cp.post(f'/platform/tenants/{A}/status', data={'csrf_token': tok(cp.get('/platform/tenants').text), 'action': action})
st('add_month')
with app.app_context():
    assert db.session.get(Tenant, A).paid_until == first_until + timedelta(days=60)
    assert SubscriptionPayment.query.filter_by(method='manual', status='paid').count() == 1
assert 'Paid' in cp.get('/platform/tenants').text and 'Starter' in cp.get('/platform/billing').text
st('suspend'); st('resume')
with app.app_context(): t = db.session.get(Tenant, A); assert t.status == 'active' and t.service_until
st('comp')
with app.app_context(): t = db.session.get(Tenant, A); assert t.paid_until is None and t.service_until is None and billing_state(t)['state'] == 'complimentary'
st('extend')
with app.app_context(): t = db.session.get(Tenant, A); assert t.status == 'trial' and t.service_until > now() + timedelta(days=14)

# reminders: once before the end, once after
with app.app_context():
    t = db.session.get(Tenant, A); t.trial_ends_at = now() + timedelta(days=2); appmod.refresh_service_until(t); db.session.commit()
    outbox.clear()
    assert send_billing_reminders() == 1 and send_billing_reminders() == 0 and 'ends soon' in outbox[0][1]
    assert send_billing_reminders(now() + timedelta(days=3)) == 1 and 'has ended' in outbox[-1][1]
    assert send_billing_reminders(now() + timedelta(days=3)) == 0
print('BILLING OK')
