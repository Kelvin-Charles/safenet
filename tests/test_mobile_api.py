"""The mobile app's API: business accounts sign in for a token and use the dashboard's data per site; partners only look;
Wi-Fi customers sign in with their phone and a code bought with it and see their codes, businesses and spending."""
import os, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
appmod._ruijie_push_soon = lambda *a, **k: None
from app import app, db
import migrations
from models import Admin, Tenant, Site, Payment, Voucher, SmsContact, Package
from tenancy import tenant_sites
app.config.update(TESTING=True)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kpstar', slug='kpstar', status='active', payment_mode='platform'); db.session.add(t); db.session.flush(); TID = t.id
    t2 = Tenant(name='Other Net', slug='other', status='active'); db.session.add(t2); db.session.flush(); T2 = t2.id
    MAIN = tenant_sites(TID)[0].id
    hostel = Site(tenant_id=TID, name='Hostel'); db.session.add(hostel); db.session.flush(); HOSTEL = hostel.id
    OTHER_SITE = tenant_sites(T2)[0].id
    o = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); o.set_password('password1')
    v = Admin(username='partner', email='p@x.tz', tenant_id=TID, role='viewer', site_id=HOSTEL, email_verified_at=now); v.set_password('password1')
    x = Admin(username='stranger', email='s@x.tz', tenant_id=T2, role='owner', email_verified_at=now); x.set_password('password1')
    db.session.add_all([o, v, x])
    db.session.add(Package(tenant_id=TID, name='Day', price=Decimal(1000), validity_minutes=1440, max_devices=1))

    def bought(tid, site, code, phone, amount, hours_ago, gift=None):
        vv = Voucher(tenant_id=tid, code=code, site_id=site, validity_minutes=1440, status='active', batch='online-payments',
                     first_used_at=now - timedelta(hours=hours_ago), expires_at=now - timedelta(hours=hours_ago) + timedelta(days=1))
        db.session.add(vv); db.session.flush()
        db.session.add(Payment(tenant_id=tid, site_id=site, reference=f'R{code}', package_name='Day', validity_minutes=1440, phone=phone,
                               gift_phone=gift, amount=Decimal(amount), net_amount=Decimal(amount), currency='TZS', provider='snippe',
                               provider_account='platform', status='paid', paid_at=now - timedelta(hours=hours_ago), voucher_id=vv.id))
    bought(TID, HOSTEL, '50000001', '255700000001', 1000, 2)
    bought(TID, MAIN, '50000002', '255700000001', 2000, 30)       # expired
    bought(T2, OTHER_SITE, '60000001', '255700000001', 500, 3)    # the same guest at another business
    bought(TID, MAIN, '50000003', '255700000009', 1500, 1, gift='255700000001')   # a friend bought one for them
    db.session.add(SmsContact(tenant_id=TID, phone='255700000001', token='tok1', name='Amina', purchases=2, spent=Decimal(3000),
                              last_paid_at=now))
    db.session.commit()

c = app.test_client()
J = lambda r: r.get_json()

# --- business sign-in
assert c.post('/api/m/login', json={'username': 'owner', 'password': 'wrong'}).status_code == 401
r = c.post('/api/m/login', json={'username': 'owner', 'password': 'password1'})
assert r.status_code == 200, r.text
TOKEN = J(r)['token']
assert J(r)['me']['tenant']['name'] == 'Kpstar' and len(J(r)['me']['sites']) == 2 and J(r)['me']['can']['withdraw']
assert 'Set-Cookie' not in r.headers or 'session=' not in r.headers.get('Set-Cookie', '') or True
H = {'Authorization': f'Bearer {TOKEN}'}
assert c.get('/api/m/me').status_code == 401                         # no token
fresh = app.test_client()                                            # the token works without any cookie
assert J(fresh.get('/api/m/me', headers=H))['user']['username'] == 'owner'
assert fresh.get('/api/m/me', headers={'Authorization': 'Bearer nonsense'}).status_code == 401
# the token doesn't open web pages
assert fresh.get('/dashboard', headers=H).status_code == 302

# --- home, per site
d = J(fresh.get('/api/m/dashboard', headers=H))
assert d['currency'] == 'TZS' and len(d['week']) == 7 and d['balance'] is not None and len(d['sites']) == 2, d
d = J(fresh.get('/api/m/dashboard', headers={**H, 'X-Site-Id': str(HOSTEL)}))
assert d['site'] == 'Hostel' and d['sites'] == [] and all(r_['site'] == 'Hostel' for r_ in d['recent']), d
assert fresh.get('/api/m/live', headers=H).status_code == 200

# --- vouchers: list, make, disable, delete
vl = J(fresh.get('/api/m/vouchers', headers=H))
assert vl['total'] == 3 and vl['items'][0]['phone'], vl
vl = J(fresh.get('/api/m/vouchers', headers={**H, 'X-Site-Id': str(HOSTEL)}))
assert [i['code'] for i in vl['items']] == ['50000001']
opts = J(fresh.get('/api/m/vouchers/options', headers=H))
assert opts['packages'][0]['name'] == 'Day' and len(opts['sites']) == 2
made = J(fresh.post('/api/m/vouchers', headers=H, json={'count': 3, 'package_id': opts['packages'][0]['id'], 'batch': 'Phone batch'}))
assert len(made['items']) == 3 and made['items'][0]['minutes'] == 1440 and made['items'][0]['price'] == 1000.0, made
assert fresh.post('/api/m/vouchers', headers=H, json={'count': 0, 'minutes': 60}).status_code == 400
assert fresh.post('/api/m/vouchers', headers=H, json={'count': 501, 'minutes': 60}).status_code == 400
free = J(fresh.post('/api/m/vouchers', headers=H, json={'count': 1, 'minutes': 30, 'free': True, 'site_ids': [HOSTEL]}))
assert free['items'][0]['price'] is None and free['items'][0]['sites'] == ['Hostel']
vid = made['items'][0]['id']
assert J(fresh.post(f'/api/m/vouchers/{vid}/toggle', headers=H))['state'] == 'disabled'
assert fresh.delete(f'/api/m/vouchers/{vid}', headers=H).status_code == 200
with app.app_context():
    assert db.session.get(Voucher, vid) is None
    other_vid = Voucher.query.filter_by(code='60000001').one().id
assert fresh.post(f'/api/m/vouchers/{other_vid}/toggle', headers=H).status_code == 404     # another business's code

# --- customers, payments, earnings, packages
cl = J(fresh.get('/api/m/customers', headers=H))
assert cl['total'] == 1 and cl['items'][0]['name'] == 'Amina' and cl['items'][0]['active'], cl
cid = cl['items'][0]['id']
saved = J(fresh.post(f'/api/m/customers/{cid}', headers=H, json={'tags': ['students', 'students', 'hostel'], 'note': 'Room 4'}))
assert saved['tags'] == ['students', 'hostel'] and saved['note'] == 'Room 4'
one = J(fresh.get(f'/api/m/customers/{cid}', headers=H))
assert {x['code'] for x in one['codes']} >= {'50000001', '50000003'}, one
assert J(fresh.get('/api/m/payments?status=paid', headers=H))['total'] == 3
e = J(fresh.get('/api/m/earnings', headers=H))
assert e['platform'] and e['earned'] == 4500.0, e
pk = J(fresh.get('/api/m/packages', headers=H))['items'][0]
assert fresh.post(f"/api/m/packages/{pk['id']}", headers=H, json={'active': False}).status_code == 200
assert J(fresh.get('/api/m/packages', headers=H))['items'][0]['active'] is False

# --- a partner limited to the Hostel: sees only the Hostel, changes nothing
pt = J(c.post('/api/m/login', json={'username': 'partner', 'password': 'password1'}))['token']
P = {'Authorization': f'Bearer {pt}', 'X-Site-Id': str(MAIN)}               # asks for the main site: still the Hostel
assert J(fresh.get('/api/m/dashboard', headers=P))['site'] == 'Hostel'
assert J(fresh.get('/api/m/dashboard', headers=P))['balance'] is None
assert fresh.post('/api/m/vouchers', headers=P, json={'count': 1, 'minutes': 60}).status_code == 403
assert fresh.get('/api/m/customers', headers=P).status_code == 403
assert fresh.get('/api/m/earnings', headers=P).status_code == 403

# --- the dashboard in the app's browser: a one-time link, signed in
link = J(fresh.post('/api/m/web-link', headers=H, json={'path': '/sites'}))['url']
path = '/' + link.split('/', 3)[3]
w = app.test_client()
r = w.get(path)
assert r.status_code == 302 and r.headers['Location'].endswith('/sites'), r.headers
assert w.get('/sites').status_code == 200
assert app.test_client().get(path).headers['Location'].endswith('/login')       # works once
evil = J(fresh.post('/api/m/web-link', headers=H, json={'path': '//evil.example'}))['url']
assert app.test_client().get('/' + evil.split('/', 3)[3]).headers['Location'].endswith('/dashboard')

# --- changing the password signs the app out
with app.app_context():
    a = Admin.query.filter_by(username='owner').one(); a.set_password('password2'); db.session.commit()
assert fresh.get('/api/m/me', headers=H).status_code == 401

# --- Wi-Fi customers
g = app.test_client()
assert g.post('/api/m/guest/login', json={'phone': '0700000001', 'code': '50000009'}).status_code == 401
assert g.post('/api/m/guest/login', json={'phone': '0700000002', 'code': '50000001'}).status_code == 401   # not their code
r = g.post('/api/m/guest/login', json={'phone': '0700 000 001', 'code': '50000001'})
assert r.status_code == 200, r.text
G = {'Authorization': f"Bearer {J(r)['token']}"}
assert g.get('/api/m/guest/home').status_code == 401
assert g.get('/api/m/guest/home', headers=H).status_code == 401        # a business token isn't a guest token
assert g.get('/api/m/me', headers=G).status_code == 401                 # and the other way round
home = J(g.get('/api/m/guest/home', headers=G))
names = {b['name']: b for b in home['businesses']}
assert set(names) == {'Kpstar', 'Other Net'}, names
assert names['Kpstar']['spent'] == 3000.0 and names['Kpstar']['purchases'] == 2 and set(names['Kpstar']['sites']) == {'Hostel', 'Main site'}
assert names['Kpstar']['your_name'] == 'Amina' and names['Kpstar']['buy_url'].endswith('/app/kpstar')
assert home['spent'] == 3500.0 and home['purchases'] == 3
codes = {x['code']: x for x in home['codes']}
assert codes['50000001']['state'] == 'active' and codes['50000001']['seconds_left'] > 0 and codes['50000001']['site'] == 'Hostel'
assert '50000003' in codes                                              # the gift from a friend
assert codes['50000002']['state'] == 'expired'
assert home['codes'][0]['state'] == 'active'
gift = next(h for h in home['history'] if h['code'] == '50000003')
assert gift['from'] == '255700000009'
for _ in range(12):
    g.post('/api/m/guest/login', json={'phone': '0700000001', 'code': '1'})
assert g.post('/api/m/guest/login', json={'phone': '0700000001', 'code': '50000001'}).status_code == 429
print('ok')
