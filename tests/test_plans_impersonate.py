import os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
paid = []
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: paid.append(a) or {'id': 'TX', 'status': 'PROCESSING'}
from app import app, db
import migrations
from models import Admin, Tenant, BillingPlan, RadUser
app.config.update(TESTING=True)
now = datetime.utcnow
tok = lambda html: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
with app.app_context():
    db.create_all(); migrations.run(); migrations.run()                      # seeding is idempotent
    plans = {p.name: p for p in BillingPlan.query.all()}
    assert sorted(plans) == ['Business', 'Economic', 'Starter'], plans
    s = plans['Starter']
    assert (s.price, s.price_yearly, s.max_customers, s.max_routers, s.max_sites, s.max_staff) == (10000, 110000, 200, 1, 1, 2)
    assert plans['Business'].price == 20000 and plans['Economic'].price_yearly == 339000
    assert s.amount_for(1) == 10000 and s.amount_for(3) == 30000 and s.amount_for(12) == 110000
    boss = Admin(username='platform', email='p@x.tz', tenant_id=migrations.default_tenant().id, role='owner', is_superadmin=True, email_verified_at=now())
    boss.set_password('password1')
    t = Tenant(name='Mama Shop', slug='mama', status='trial', trial_ends_at=now() + __import__('datetime').timedelta(days=7), billing_plan_id=s.id); db.session.add(t); db.session.flush()
    owner = Admin(username='mama', email='m@x.tz', tenant_id=t.id, role='owner', email_verified_at=now()); owner.set_password('secret-pw-1')
    db.session.add_all([boss, owner]); db.session.commit(); TID = t.id

def login(u, pw='password1'):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': pw, 'csrf_token': tok(r.text)}); return c

# Landing shows the plans and limits
home = app.test_client().get('/').text
assert 'TZS 10,000' in home and '110,000 billed yearly' in home and 'Staff accounts' in home and '1,000' in home

# Platform admin logs in as the owner without their password
c = login('platform')
page = c.get('/platform/tenants').text
assert 'Log in as owner' in page
r = c.post(f'/platform/impersonate/{TID}', data={'csrf_token': tok(page)}, follow_redirects=True).text
assert 'You are logged in as <strong>mama</strong>' in r and 'Mama Shop' in r
assert c.get('/platform/tenants').status_code == 404                       # really is the owner now
b = c.get('/billing').text
assert '200 customers' in b and '2 staff' in b and 'or 110,000 / year' in b and '1 year' in b

# Limits: staff (owner counts, so 1 more allowed), customers
with app.app_context():
    db.session.add(Admin(username='staff1', email='s1@x.tz', tenant_id=TID, role='staff', email_verified_at=now(), password_hash='x'))
    db.session.add_all([RadUser(username=f'cust{i}', tenant_id=TID) for i in range(200)]); db.session.commit()
f = c.get('/team/add').text
r = c.post('/team/add', data={'csrf_token': tok(f), 'username': 'staff2', 'email': 's2@x.tz', 'password': 'password12', 'password2': 'password12', 'confirm': 'password12', 'role': 'staff'}, follow_redirects=True).text
assert 'does not allow more staff' in r
f = c.get('/users/add').text
r = c.post('/users/add', data={'csrf_token': tok(f), 'username': 'extra', 'password': 'pw123456', 'plan_id': 0, 'is_active': 'y'}, follow_redirects=True).text
assert 'does not allow more customers' in r
with app.app_context(): assert not RadUser.query.filter_by(username='extra').first()

# Yearly payment charges the yearly price
with app.app_context(): sid = BillingPlan.query.filter_by(name='Starter').one().id
b = c.get('/billing').text
c.post('/billing/pay', data={'csrf_token': tok(b), 'plan_id': sid, 'months': 12, 'phone': '0684000111'})
assert paid and Decimal(str(paid[-1])) == 110000, paid

# Logging out while impersonating returns to the platform account
r = c.get('/logout', follow_redirects=True).text
assert 'Back to your platform account' in r and c.get('/platform/tenants').status_code == 200

# Owners cannot use the stop route to become anyone else
o = login('mama', 'secret-pw-1')
r = o.post('/platform/impersonate/stop', data={}, follow_redirects=True)
assert o.get('/dashboard').status_code == 302                              # just logged out
# Non-admins cannot impersonate
o = login('mama', 'secret-pw-1')
assert o.post(f'/platform/impersonate/{TID}', data={'csrf_token': tok(o.get('/billing').text)}).status_code == 404

# Platform billing form saves the new fields
p = c.get('/platform/billing').text
assert 'Price / year' in p and 'Staff' in p
c.post('/platform/billing', data={'csrf_token': tok(p), 'id': sid, 'name': 'Starter', 'price': '12000', 'price_yearly': '',
                                   'max_customers': '250', 'max_routers': '1', 'max_sites': '1', 'max_staff': '3', 'sort_order': 0, 'is_active': '1'})
with app.app_context():
    s = db.session.get(BillingPlan, sid); assert (s.price, s.price_yearly, s.max_customers, s.max_staff) == (12000, None, 250, 3)
    assert s.amount_for(12) == 144000
print('PLANS + IMPERSONATE OK')
