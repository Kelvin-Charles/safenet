"""RADIUS access points with an external login page (Grandstream, Cambium, CoovaChilli, MikroTik, Meraki): /hs/<token>."""
import hashlib, html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode, urlparse, parse_qs
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel',
                  PUBLIC_URL='https://radius.example.tz')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
pay = {'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay['status'], 'collectedAmount': '1000'}
from app import app, db
import migrations
from models import Admin, Tenant, Site, Package, Voucher, RadCheck, Nas
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add_all([o, Package(tenant_id=t.id, name='1 Day', price=Decimal(1000), validity_minutes=1440)])
    for code in ('11110000', '22220000', '33330000', '44440000', '55550000'):
        db.session.add_all([Voucher(tenant_id=t.id, code=code, validity_minutes=60, batch='x', status='unused'),
                            RadCheck(username=code, attribute='Cleartext-Password', op=':=', value=code)])
    other = Tenant(name='Other', slug='other', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(other); db.session.flush()
    db.session.add(Nas(tenant_id=other.id, nasname='41.59.9.9', shortname='theirs', secret='s3cret', vendor='mikrotik'))
    db.session.commit(); TID = t.id; SID = tenant_sites(TID)[0].id

# the owner switches it on
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = c.get('/sites').text
assert 'Switch on RADIUS access points' in p
r = c.post(f'/sites/{SID}/hotspot', data={'csrf_token': tok(p), 'action': 'enable'}, follow_redirects=True).text
with app.app_context():
    s = db.session.get(Site, SID); TOKEN = s.portal_token; SECRET = db.session.get(Tenant, TID).radius_secret
    assert s.hotspot_enabled and SECRET and len(SECRET) >= 16
assert f'/hs/{TOKEN}' in r and SECRET in r and 'No guest has been sent here yet' in r
assert app.test_client().get('/hs/nope').status_code == 404

SITE_IP = {'REMOTE_ADDR': '41.59.1.10'}         # the site's public address, as guests' browsers reach SafeNet
B = 'https://radius.example.tz'

def arrive(q, ip=SITE_IP):
    g = app.test_client()
    page = g.get(f'/hs/{TOKEN}?' + urlencode(q), base_url=B, environ_overrides=ip).text
    return g, page

def login(g, code):
    return g.post(f'/hs/{TOKEN}/login', data={'code': code, 'agree': '1'}, base_url=B, environ_overrides=SITE_IP)

# Grandstream: back to its login_url with the code (GET)
g, page = arrive(dict(login_url='http://192.168.80.1:8080/login', client_mac='AA:BB:CC:00:00:01', ap_mac='00:0B:82:11:22:33',
                      orig_url='http://example.com/', ssid='Zulu Free'))
assert 'Zulu Connect' in page and '1 Day' in page and f'action="/hs/{TOKEN}/login"' in page and f'action="/hs/{TOKEN}/buy"' in page
with app.app_context():
    s = db.session.get(Site, SID); assert s.hotspot_kind == 'grandstream' and s.hotspot_ip == '41.59.1.10' and not s.hotspot_problem
    n = Nas.query.filter_by(site_id=SID, vendor='hotspot').one()
    assert n.nasname == '41.59.1.10' and n.secret == SECRET and n.tenant_id == TID and n.shortname.startswith('hotspot-')
assert "isn't valid" in html.unescape(login(g, '99999999').text)
r = login(g, '1111 0000')
assert r.status_code == 302, r.text[:300]
u = urlparse(r.headers['Location']); q = parse_qs(u.query)
assert (u.scheme, u.netloc, u.path) == ('http', '192.168.80.1:8080', '/login')
assert q['username'] == ['11110000'] and q['password'] == ['11110000'] and q['redirect'] == ['http://example.com/']
with app.app_context():
    v = Voucher.query.filter_by(code='11110000').one(); assert v.status == 'active' and v.first_used_at

# returning phone with time left: straight back to the device
g2, _ = None, None
r = app.test_client().get(f'/hs/{TOKEN}?' + urlencode(dict(login_url='http://192.168.80.1:8080/login', client_mac='AA:BB:CC:00:00:01',
                                                           orig_url='http://x/')), base_url=B, environ_overrides=SITE_IP)
assert r.status_code == 302 and 'username=11110000' in r.headers['Location']

# never hand a code to a public site
g, _ = arrive(dict(login_url='http://evil.example.com/steal', client_mac='AA:BB:CC:00:00:02', orig_url='http://x/'))
assert 'connect to the Wi-Fi again' in html.unescape(login(g, '22220000').text)
with app.app_context():
    assert Voucher.query.filter_by(code='22220000').one().first_used_at is None     # the code was not used up

# Cambium: a form posted to the access point on port 880, with ga_Qv in the URL
g, _ = arrive(dict(ga_ssid='Zulu', ga_ap_mac='58-C1-7A-00-00-01', ga_nas_id='ap1', ga_srvr='192.168.1.20', ga_cmac='AA-BB-CC-00-00-03',
                   ga_Qv='eUROAhcFBQAYHRIVQkxRVkQGCgQ', ga_orig_url='http://example.com/'))
r = login(g, '22220000'); body = html.unescape(r.text)
assert r.status_code == 200 and 'action="http://192.168.1.20:880/cgi-bin/hotspot_login.cgi?ga_Qv=eUROAhcFBQAYHRIVQkxRVkQGCgQ"' in body
assert 'name="ga_user" value="22220000"' in body and 'name="ga_pass" value="22220000"' in body and '.submit()' in body

# CoovaChilli: CHAP response from the challenge
CH = '0123456789abcdef0123456789abcdef'
g, _ = arrive(dict(res='notyet', uamip='10.1.0.1', uamport='3990', challenge=CH, mac='AA-BB-CC-00-00-04', ip='10.1.0.5',
                   userurl='http://example.com/'))
r = login(g, '33330000'); u = urlparse(r.headers['Location']); q = parse_qs(u.query)
assert r.status_code == 302 and (u.netloc, u.path) == ('10.1.0.1:3990', '/logon') and q['username'] == ['33330000']
assert q['response'] == [hashlib.md5(b'\0' + b'33330000' + bytes.fromhex(CH)).hexdigest()] and 'password' not in q

# MikroTik: GET to its login URL (no https-to-http form warning)
g, _ = arrive({'link-login-only': 'http://10.5.50.1/login', 'link-orig': 'http://example.com/', 'mac': 'AA:BB:CC:00:00:05'})
r = login(g, '44440000'); assert r.status_code == 302 and r.headers['Location'].startswith('http://10.5.50.1/login?username=44440000')

# Meraki: posted to its https login URL
g, _ = arrive(dict(login_url='https://n123.network-auth.com/splash/login', continue_url='http://example.com/', client_mac='AA:BB:CC:00:00:06'))
body = html.unescape(login(g, '55550000').text)
assert 'action="https://n123.network-auth.com/splash/login"' in body and 'name="success_url" value="http://example.com/"' in body

# buying: pay, then logged in on the device
g, _ = arrive(dict(login_url='http://192.168.80.1:8080/login', client_mac='AA:BB:CC:00:00:07', orig_url='http://example.com/'))
with app.app_context(): PID = Package.query.filter_by(tenant_id=TID).first().id
r = g.post(f'/hs/{TOKEN}/buy', data={'package_id': PID, 'phone': '684000111', 'network': 'airtel', 'agree': '1'}, base_url=B,
           environ_overrides=SITE_IP)
assert r.status_code == 302 and '/buy/wait?ref=' in r.headers['Location'], r.text[:500]
wait = r.headers['Location'].replace(B, '')
assert g.get(wait, base_url=B).status_code == 200
pay['status'] = 'SUCCESS'
with app.app_context():
    from models import Payment
    ref = wait.split('ref=')[1]; pm = Payment.query.filter_by(reference=ref).one()
    assert pm.site_id == SID and pm.client_mac == 'AA-BB-CC-00-00-07'
    pm.checked_at = None; db.session.commit()
r = g.get(wait, base_url=B)
assert r.status_code == 302 and r.headers['Location'].startswith('http://192.168.80.1:8080/login?username='), r.headers.get('Location')

# an unknown device: shown on Sites for support
app.test_client().get(f'/hs/{TOKEN}?usermac=aa&ac-ip=1.2.3.4', base_url=B, environ_overrides=SITE_IP)
with app.app_context(): assert 'usermac=aa' in db.session.get(Site, SID).hotspot_unknown

# a shared internet address (another business's RADIUS client): warned, nothing taken over
arrive(dict(login_url='http://192.168.80.1:8080/login', client_mac='AA:BB:CC:00:00:08'), ip={'REMOTE_ADDR': '41.59.9.9'})
with app.app_context():
    s = db.session.get(Site, SID); assert s.hotspot_problem == 'shared'
    assert Nas.query.filter_by(nasname='41.59.9.9').one().shortname == 'theirs'
assert 'shared with another SafeNet business' in c.get('/sites').text
# a new address: the client moves with it
arrive(dict(login_url='http://192.168.80.1:8080/login', client_mac='AA:BB:CC:00:00:08'), ip={'REMOTE_ADDR': '41.59.1.77'})
with app.app_context():
    assert Nas.query.filter_by(site_id=SID, vendor='hotspot').one().nasname == '41.59.1.77'
    assert db.session.get(Site, SID).hotspot_problem is None

# new secret, then switching off removes the RADIUS client
p = c.get('/sites').text
c.post(f'/sites/{SID}/hotspot', data={'csrf_token': tok(p), 'action': 'new-secret'})
with app.app_context():
    new = db.session.get(Tenant, TID).radius_secret
    assert new != SECRET and Nas.query.filter_by(site_id=SID, vendor='hotspot').one().secret == new
c.post(f'/sites/{SID}/hotspot', data={'csrf_token': tok(p), 'action': 'disable'})
with app.app_context():
    assert not db.session.get(Site, SID).hotspot_enabled and Nas.query.filter_by(vendor='hotspot').count() == 0
assert app.test_client().get(f'/hs/{TOKEN}').status_code == 404

# the guides
for slug in ('wifidog', 'radius-aps', 'start'):
    assert app.test_client().get(f'/docs/{slug}').status_code == 200
print('HOTSPOT APS OK')
