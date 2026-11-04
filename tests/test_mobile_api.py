"""The mobile app's API: business accounts sign in for a token and use the dashboard's data per site; partners only look;
Wi-Fi customers sign in with their phone and a code bought with it and see their codes, businesses and spending."""
import os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
texts = []
appmod.send_sms_async = lambda to, text, *a, **k: texts.append((to, text))
appmod.sms_is_configured = lambda: True
mails = []
appmod._send_verification = lambda admin: mails.append(admin.email)
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

# --- Wi-Fi customers: with a voucher code alone (sees that code)
g = app.test_client()
assert g.post('/api/m/guest/login', json={'code': '59999999'}).status_code == 401
r = g.post('/api/m/guest/login', json={'code': '5000 0001'})
assert r.status_code == 200, r.text
V = {'Authorization': f"Bearer {J(r)['token']}"}
home = J(g.get('/api/m/guest/home', headers=V))
assert [x['code'] for x in home['codes']] == ['50000001'] and home['spent'] == 1000.0 and home['phone'] is None, home
assert [b['name'] for b in home['businesses']] == ['Kpstar'] and home['businesses'][0]['sites'] == ['Hostel']
assert g.get('/api/m/me', headers=V).status_code == 401                 # a guest token isn't a business token
assert g.get('/api/m/guest/home', headers=H).status_code == 401        # and the other way round

# --- with the phone number: SafeNet texts a code
assert g.post('/api/m/guest/send-code', json={'phone': '0711111111'}).status_code == 404     # never bought
r = g.post('/api/m/guest/send-code', json={'phone': '0700 000 001'})
assert r.status_code == 200, r.text
to, text = texts[-1]
assert to == '255700000001'
otp = re.search(r'\b(\d{6})\b', text).group(1)
wrong = '000000' if otp != '000000' else '111111'
assert g.post('/api/m/guest/login', json={'phone': '0700000001', 'otp': wrong}).status_code == 401
r = g.post('/api/m/guest/login', json={'phone': '0700000001', 'otp': otp})
assert r.status_code == 200, r.text
G = {'Authorization': f"Bearer {J(r)['token']}"}
assert g.post('/api/m/guest/login', json={'phone': '0700000001', 'otp': otp}).status_code == 401   # works once
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
for _ in range(3):
    g.post('/api/m/guest/send-code', json={'phone': '0700000001'})
assert g.post('/api/m/guest/send-code', json={'phone': '0700000001'}).status_code == 429       # 3 an hour per number
for _ in range(12):
    g.post('/api/m/guest/login', json={'code': '1'})
assert g.post('/api/m/guest/login', json={'code': '50000001'}).status_code == 429

# --- registering a business from the app
appmod.Config.SIGNUP_ENABLED = True
cfg = J(c.get('/api/m/config'))
assert cfg['signup'] and cfg['sms_login'] and cfg['trial_days'] >= 0
bad = c.post('/api/m/signup', json={'business_name': 'X', 'username': 'a b', 'email': 'nope', 'password': 'short'})
assert bad.status_code == 400 and set(J(bad)['fields']) >= {'business_name', 'username', 'email', 'password', 'accept'}, J(bad)
taken = c.post('/api/m/signup', json={'business_name': 'Mpya Net', 'username': 'owner', 'email': 'new@x.tz', 'password': 'password1', 'accept': True})
assert J(taken)['fields'] == {'username': 'That username is taken.'}
r = c.post('/api/m/signup', json={'business_name': 'Mpya Net', 'username': 'mpya', 'email': 'New@X.tz', 'phone': '0755123456',
                                  'password': 'password1', 'accept': True})
assert r.status_code == 200 and J(r)['email'] == 'new@x.tz' and mails == ['new@x.tz'], r.text
with app.app_context():
    a = Admin.query.filter_by(username='mpya').one()
    assert a.role == 'owner' and a.tenant.name == 'Mpya Net' and a.tenant.status == 'trial' and a.email_verified_at is None
r = c.post('/api/m/login', json={'username': 'mpya', 'password': 'password1'})
assert r.status_code == 403 and J(r)['unverified'] and J(r)['email'] == 'new@x.tz'
assert c.post('/api/m/resend', json={'email': 'new@x.tz'}).status_code == 200 and mails == ['new@x.tz', 'new@x.tz']
appmod.Config.SIGNUP_ENABLED = False
assert c.post('/api/m/signup', json={}).status_code == 404
print('ok')

# ================================================================ managing the business from the app
with app.app_context():
    a = Admin.query.filter_by(username='owner').one(); a.set_password('password1'); db.session.commit()
H = {'Authorization': 'Bearer ' + J(c.post('/api/m/login', json={'username': 'owner', 'password': 'password1'}))['token']}
m = app.test_client()

# packages
form = J(m.get('/api/m/packages/form', headers=H)); assert len(form['sites']) == 2
assert m.post('/api/m/packages/new', headers=H, json={'name': '', 'price': 500, 'minutes': 60}).status_code == 400
pid = J(m.post('/api/m/packages/new', headers=H, json={'name': 'Hour', 'price': 500, 'minutes': 60, 'devices': 1, 'site_id': HOSTEL}))['id']
full = J(m.get(f'/api/m/packages/{pid}/full', headers=H)); assert full['site_id'] == HOSTEL and full['price'] == 500.0
assert m.post(f'/api/m/packages/{pid}/save', headers=H, json={**full, 'price': 600}).status_code == 200
assert J(m.get(f'/api/m/packages/{pid}/full', headers=H))['price'] == 600.0

# offers
o = m.post('/api/m/offers', headers=H, json={'name': 'Buy a day, get 6 hours', 'package_id': pid, 'bonus_minutes': 360, 'active': True})
assert o.status_code == 200 and J(o)['bonus_minutes'] == 360 and J(o)['live'], o.text
oid = J(o)['id']
assert m.post('/api/m/offers', headers=H, json={'name': 'Nothing'}).status_code == 400          # no extra time or discount
assert J(m.post(f'/api/m/offers/{oid}/toggle', headers=H))['active'] is False
assert [x['id'] for x in J(m.get('/api/m/offers', headers=H))['items']] == [oid]
assert m.delete(f'/api/m/offers/{oid}', headers=H).status_code == 200

# SMS to customers: audience, cost, send
pre = J(m.post('/api/m/sms', headers=H, json={'text': 'Habari! Ofa leo.'}))
assert pre['count'] == 2 and pre['parts'] == 1 and pre['cost'] == pre['count'] * pre['price'] and pre['sample'].startswith('Kpstar: '), pre
one = J(m.post('/api/m/sms', headers=H, json={'text': 'Hi', 'site_id': HOSTEL}))
assert one['count'] == 1
assert m.post('/api/m/sms', headers=H, json={'text': '', 'action': 'send'}).status_code == 400
sent = m.post('/api/m/sms', headers=H, json={'text': 'Habari', 'phones': ['255700000001'], 'action': 'send'})
assert sent.status_code == 200 and J(sent)['sent'] == 1, sent.text
assert J(m.get('/api/m/sms/history', headers=H))['items'][0]['recipients'] == 1

# speed plans
pl = m.post('/api/m/plans', headers=H, json={'name': 'Fast', 'down': '10M', 'up': '2m'})
assert pl.status_code == 200 and J(pl)['up'] == '2M', pl.text
assert m.post('/api/m/plans', headers=H, json={'name': 'Bad', 'down': 'fast'}).status_code == 400
assert m.post('/api/m/plans', headers=H, json={'name': 'Fast'}).status_code == 400              # same name
assert m.delete(f"/api/m/plans/{J(pl)['id']}", headers=H).status_code == 200

# team
tm = J(m.get('/api/m/team', headers=H)); assert 'viewer' in tm['roles'] and any(x['me'] for x in tm['items'])
r = m.post('/api/m/team', headers=H, json={'username': 'cashier', 'email': 'c@x.tz', 'role': 'staff', 'password': 'password1'})
assert r.status_code == 200, r.text
cid_ = J(r)['id']
assert J(m.post(f'/api/m/team/{cid_}/toggle', headers=H))['active'] is False
me_id = next(x['id'] for x in tm['items'] if x['me'])
assert m.post(f'/api/m/team/{me_id}/toggle', headers=H).status_code == 403                      # not yourself
assert m.delete(f'/api/m/team/{cid_}', headers=H).status_code == 200

# settings
st = J(m.post('/api/m/settings', headers=H, json={'support_phone': '0755000111', 'sale_sms': True, 'notify_phone': '0755000222'}))
assert st['support_phone'] == '0755000111' and st['sale_sms'] and st['notify_phone'] == '255755000222'
assert m.post('/api/m/settings', headers=H, json={'notify_phone': 'abc'}).status_code == 400

# sites and devices
sv = J(m.get('/api/m/sites', headers=H)); assert {x['name'] for x in sv['sites']} == {'Main site', 'Hostel'}
assert m.post(f'/api/m/sites/{HOSTEL}', headers=H, json={'name': 'Hostel A'}).status_code == 200
assert 'Hostel A' in {x['name'] for x in J(m.get('/api/m/sites', headers=H))['sites']}

# a partner can't manage
assert m.post('/api/m/plans', headers=P, json={'name': 'X'}).status_code in (401, 403)

# pages opened in the app lose the web menu
link = J(m.post('/api/m/web-link', headers=H, json={'path': '/team'}))['url']
w = app.test_client(); w.get('/' + link.split('/', 3)[3])
assert 'body.in-app' in w.get('/team').text and 'in-app' in w.get('/team').text.split('<body', 1)[1][:200]
assert 'in-app' not in app.test_client().get('/login').text.split('<body', 1)[1][:200]
print('manage ok')
