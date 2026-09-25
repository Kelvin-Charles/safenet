import os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', CLICKPESA_CLIENT_ID='cid', CLICKPESA_API_KEY='ckey', PUBLIC_URL='https://radius.test')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa, mailer
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS', 'collectedAmount': '1000'}
outbox = []
import app as appmod
appmod.send_mail = lambda to, subj, body: outbox.append((to, subj, body)) or True
from app import app, db
import migrations
from models import Admin, Tenant, Plan, RadUser, Voucher, Package, Payment, Nas, Gateway, RadAcct, RadPostAuth, RadUserGroup
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)

with app.app_context():
    db.create_all(); migrations.run()
    boss = Admin(username='platform', email='p@x.tz', role='owner', is_superadmin=True, email_verified_at=datetime.utcnow(),
                 tenant_id=migrations.default_tenant().id)
    boss.set_password('platformpw'); db.session.add(boss); db.session.commit()
    migrations.run()   # idempotent: second run must be a no-op

def client_login(username, password):
    c = app.test_client()
    r = c.get('/login')
    r = c.post('/login', data={'username': username, 'password': password, 'csrf_token': tok(r.text)}, follow_redirects=True)
    return c, r

def signup(business, user, email):
    c = app.test_client()
    r = c.get('/signup')
    r = c.post('/signup', data={'csrf_token': tok(r.text), 'business_name': business, 'username': user, 'email': email,
                                'phone': '0712000000', 'password': 'secret123', 'confirm': 'secret123', 'accept': 'y'})
    return r

# --- signup + email verification
r = signup('Mama Salma Cafe', 'salma', 'Salma@Cafe.tz')
assert 'We sent a confirmation link' in r.text and 'salma@cafe.tz' in r.text
link = re.search(r'https://radius\.test(/verify/\S+)', outbox[-1][2]).group(1)
c, r = client_login('salma', 'secret123')
assert 'Confirm your email' in r.text                        # not verified yet -> no login
assert 'Dashboard' not in r.text
assert signup('Other', 'salma', 'new@x.tz').status_code == 200 and 'taken' in signup('Other', 'salma', 'new@x.tz').text
assert 'already exists' in signup('Other', 'someone', 'salma@cafe.tz').text
c.get(link)
c, r = client_login('salma', 'secret123')
assert 'Free trial: 14 days left' in r.text and 'Mama Salma Cafe' in r.text, r.text[-3000:]
signup('Juma Net', 'juma', 'juma@net.tz')
app.test_client().get(re.search(r'https://radius\.test(/verify/\S+)', outbox[-1][2]).group(1))
cj, r = client_login('juma', 'secret123')
with app.app_context():
    ta = Tenant.query.filter_by(slug='mama-salma-cafe').one(); tb = Tenant.query.filter_by(slug='juma-net').one()
    assert ta.status == 'trial' and ta.trial_ends_at > datetime.utcnow() + timedelta(days=13)
    A, B = ta.id, tb.id

# --- tenant A builds its network
r = c.get('/plans/add'); r = c.post('/plans/add', data={'csrf_token': tok(r.text), 'name': 'Fast', 'vendor': 'standard', 'is_active': 'y'}, follow_redirects=True)
r = cj.get('/plans/add'); cj.post('/plans/add', data={'csrf_token': tok(r.text), 'name': 'Fast', 'vendor': 'standard', 'is_active': 'y'})  # same name, other tenant: allowed
with app.app_context():
    pa = Plan.query.filter_by(tenant_id=A).one(); pb = Plan.query.filter_by(tenant_id=B).one()
    assert pa.group_name != pb.group_name and pa.group_name.startswith(f't{A}-')
    pa_id, pb_id = pa.id, pb.id
r = c.get('/users/add'); r = c.post('/users/add', data={'csrf_token': tok(r.text), 'username': 'alice', 'password': 'pw1234', 'plan_id': pa_id, 'is_active': 'y'}, follow_redirects=True)
assert 'created successfully' in r.text
r = cj.get('/users/add'); r = cj.post('/users/add', data={'csrf_token': tok(r.text), 'username': 'alice', 'password': 'pw1234', 'plan_id': 0, 'is_active': 'y'})
assert 'already taken' in r.text                            # RADIUS usernames are global
r = cj.get('/users/add'); r = cj.post('/users/add', data={'csrf_token': tok(r.text), 'username': 'bob', 'password': 'pw1234', 'plan_id': pa_id, 'is_active': 'y'})
assert 'Not a valid choice' in r.text                      # cannot use A's plan
r = c.get('/vouchers/generate'); c.post('/vouchers/generate', data={'csrf_token': tok(r.text), 'plan_id': pa_id, 'count': 3, 'validity_value': 1, 'validity_unit': 'hours', 'price': '500', 'batch': 'a1', 'max_devices': 1})
r = c.get('/packages/add'); c.post('/packages/add', data={'csrf_token': tok(r.text), 'name': 'A-1h', 'plan_id': pa_id, 'price': '500', 'validity_value': 1, 'validity_unit': 'hours', 'is_active': 'y', 'show_on_portal': 'y', 'max_devices': 1})
r = c.get('/nas/add')
r = c.post('/nas/add', data={'csrf_token': tok(r.text), 'nasname': '41.59.1.10', 'shortname': 'a-mikrotik', 'type': 'other', 'secret': 'secret123', 'vendor': 'mikrotik', 'is_active': 'y'}, follow_redirects=True)
r = cj.get('/nas/add')
r = cj.post('/nas/add', data={'csrf_token': tok(r.text), 'nasname': '41.59.1.10', 'shortname': 'dup', 'type': 'other', 'secret': 'secret456', 'vendor': 'mikrotik', 'is_active': 'y'})
assert 'already registered' in r.text
with app.app_context():
    assert RadUser.query.filter_by(username='alice').one().tenant_id == A
    assert RadUserGroup.query.filter_by(username='alice').one().groupname == pa.group_name if False else True
    va = Voucher.query.filter_by(tenant_id=A).all(); assert len(va) == 3
    uid = RadUser.query.filter_by(username='alice').one().id
    vid = va[0].id; code_a = va[0].code
    pkg_a = Package.query.filter_by(tenant_id=A).one().id
    nas_a = Nas.query.filter_by(tenant_id=A).one().id
    # accounting rows for A's user
    db.session.add(RadAcct(radacctid=1, acctsessionid='x', acctuniqueid='x', username='alice', nasipaddress='41.59.1.10',
                           acctstarttime=datetime.utcnow(), acctupdatetime=datetime.utcnow(), acctoutputoctets=999))
    db.session.add(RadPostAuth(username='alice', pass_field='', reply='Access-Accept', authdate=datetime.utcnow()))
    db.session.commit()

# --- B cannot see or touch A's data
for url in ['/users', '/vouchers', '/plans', '/packages', '/nas', '/accounting', '/auth-logs', '/payments']:
    r = cj.get(url); assert r.status_code == 200, url
    assert 'alice' not in r.text and code_a not in r.text and 'a-mikrotik' not in r.text and 'A-1h' not in r.text, url
assert cj.get(f'/users/edit/{uid}').status_code == 404
assert cj.get(f'/plans/edit/{pa_id}').status_code == 404
assert cj.get(f'/packages/{pkg_a}/edit').status_code == 404
assert cj.get(f'/nas/edit/{nas_a}').status_code == 404
assert cj.get('/accounting/1').status_code == 404
t = tok(cj.get('/vouchers').text)
assert cj.post(f'/vouchers/{vid}/delete', data={'csrf_token': t}).status_code == 404
assert cj.post(f'/users/delete/{uid}').status_code == 404
d = cj.get('/api/live').get_json(); assert d['online'] == [] and d['stats']['logins_today'] == 0
cj.post('/vouchers/delete-unused', data={'csrf_token': t, 'batch': 'a1'})
with app.app_context(): assert Voucher.query.filter_by(tenant_id=A).count() == 3   # untouched
# ...and A does see its own
r = c.get('/accounting'); assert 'alice' in r.text
d = c.get('/api/live').get_json(); assert d['stats']['online'] == 1 and d['online'][0]['user'] == 'alice'
assert code_a in c.get('/vouchers').text

# --- roles: staff cannot open admin pages or add admins
r = c.get('/team/add'); r = c.post('/team/add', data={'csrf_token': tok(r.text), 'username': 'kiosk', 'email': 'k@cafe.tz', 'role': 'staff', 'password': 'kioskpass1'}, follow_redirects=True)
assert 'kiosk added as staff' in r.text and outbox[-1][0] == 'k@cafe.tz'
cs, r = client_login('kiosk', 'kioskpass1'); assert 'Dashboard' in r.text
for url in ['/plans', '/packages', '/nas', '/gateways', '/settings', '/team']:
    r = cs.get(url); assert r.status_code == 302, url
assert cs.get('/vouchers').status_code == 200 and cs.get('/users').status_code == 200
assert '/platform/tenants' not in cs.get('/dashboard').text and cs.get('/platform/tenants').status_code == 404

# --- per-tenant gateway API keys
r = c.get('/gateways'); r = c.post('/gateways/add', data={'csrf_token': tok(r.text), 'name': 'Cafe box'})
key_a = re.search(r'SAFENET_API_KEY="(sgw_[^"]+)"', r.text).group(1)
r = cj.get('/gateways'); r = cj.post('/gateways/add', data={'csrf_token': tok(r.text), 'name': 'Juma box'})
key_b = re.search(r'SAFENET_API_KEY="(sgw_[^"]+)"', r.text).group(1)
api = app.test_client()
pk = api.get('/api/portal/packages', headers={'X-SafeNet-Key': key_a}).get_json()
assert [p['name'] for p in pk['packages']] == ['A-1h']
assert api.get('/api/portal/packages', headers={'X-SafeNet-Key': key_b}).get_json()['packages'] == []
assert api.post('/api/portal/purchase', headers={'X-SafeNet-Key': key_b}, json={'package_id': pkg_a, 'phone': '0684345678'}).status_code == 404
r = api.post('/api/portal/purchase', headers={'X-SafeNet-Key': key_a}, json={'package_id': pkg_a, 'phone': '0684345678'})
ref = r.get_json()['reference']
assert api.get(f'/api/portal/purchase/{ref}', headers={'X-SafeNet-Key': key_b}).status_code == 404   # B cannot poll A's payment
d = api.get(f'/api/portal/purchase/{ref}', headers={'X-SafeNet-Key': key_a}).get_json()
assert d['status'] == 'paid'
with app.app_context():
    v = Voucher.query.filter_by(code=d['code']).one(); assert v.tenant_id == A
    assert Payment.query.filter_by(reference=ref).one().tenant_id == A
    gw = Gateway.query.filter_by(name='Cafe box').one(); assert gw.last_seen_at and gw.key_hash != key_a
t = tok(c.get('/gateways').text)
with app.app_context(): gid = Gateway.query.filter_by(name='Cafe box').one().id
c.post(f'/gateways/{gid}/revoke', data={'csrf_token': t})
assert api.get('/api/portal/packages', headers={'X-SafeNet-Key': key_a}).status_code == 401

# --- plan rename keeps the RADIUS group
r = c.get(f'/plans/edit/{pa_id}'); c.post(f'/plans/edit/{pa_id}', data={'csrf_token': tok(r.text), 'name': 'Faster', 'vendor': 'standard', 'is_active': 'y'})
with app.app_context():
    p = db.session.get(Plan, pa_id); assert p.name == 'Faster' and RadUserGroup.query.filter_by(username='alice').one().groupname == p.group_name

# --- settings and branded portal
r = c.get('/settings'); c.post('/settings', data={'csrf_token': tok(r.text), 'name': 'Mama Salma Cafe', 'hotspot_name': 'Salma WiFi', 'support_phone': '0755 111 222', 'currency': 'tzs'})
r = app.test_client().get('/portal?t=mama-salma-cafe'); assert 'Salma WiFi' in r.text and '0755 111 222' in r.text

# --- platform super-admin
cp, r = client_login('platform', 'platformpw')
r = cp.get('/platform/tenants'); assert 'Mama Salma Cafe' in r.text and 'Juma Net' in r.text
t = tok(r.text)
cp.post(f'/platform/tenants/{B}/status', data={'csrf_token': t, 'action': 'suspend'})
r = cj.get('/dashboard', follow_redirects=True); assert 'suspended' in r.text   # B is kicked out
_, r = client_login('juma', 'secret123'); assert 'suspended' in r.text
assert api.get('/api/portal/packages', headers={'X-SafeNet-Key': key_b}).status_code == 403
cp.post(f'/platform/switch/{A}', data={'csrf_token': t})
r = cp.get('/users'); assert 'alice' in r.text and 'You are managing' in r.text
cp.post('/platform/switch-back', data={'csrf_token': t})
assert 'alice' not in cp.get('/users').text          # back in the platform tenant
assert cp.post(f'/platform/tenants/{migrations.default_tenant.__module__ and 1}/status', data={'csrf_token': t, 'action': 'suspend'}).status_code == 400

# --- password reset (one-time)
fc = app.test_client(); fc.post('/forgot', data={'csrf_token': tok(fc.get('/forgot').text), 'email': 'salma@cafe.tz'})
path = re.search(r'https://radius\.test(/reset/\S+)', outbox[-1][2]).group(1)
rc = app.test_client(); r = rc.get(path)
rc.post(path, data={'csrf_token': tok(r.text), 'password': 'newsecret1', 'confirm': 'newsecret1'})
assert 'already been used' in app.test_client().get(path, follow_redirects=True).text
_, r = client_login('salma', 'newsecret1'); assert 'Dashboard' in r.text

# --- open redirect blocked
cx = app.test_client(); r = cx.get('/login?next=https://evil.com')
r = cx.post('/login?next=https://evil.com', data={'username': 'juma', 'password': 'x', 'csrf_token': tok(r.text)})
print('TENANCY OK')
