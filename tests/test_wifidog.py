"""WiFiDog (Ruijie RG-AP and others): SafeNet as the authentication server, driven like an access point would."""
import html, os, re, sys, time
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode, urlparse, parse_qs
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel',
                  PUBLIC_URL='https://radius.example.tz', WIFIDOG_BASE='http://radius.example.tz:5001')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
pay = {'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay['status'], 'collectedAmount': '1000'}
from app import app, db
import migrations
from models import Admin, Tenant, Site, Package, Payment, Voucher, RadCheck, RadAcct, WifidogSession
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add_all([o, Package(tenant_id=t.id, name='1 Day', price=Decimal(1000), validity_minutes=1440)])
    for code, minutes in (('11110000', 60), ('22220000', 60), ('33330000', 60)):
        db.session.add_all([Voucher(tenant_id=t.id, code=code, validity_minutes=minutes, batch='x', status='unused'),
                            RadCheck(username=code, attribute='Cleartext-Password', op=':=', value=code)])
    db.session.commit(); TID = t.id; SID = tenant_sites(TID)[0].id

# owner switches it on
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = c.get('/sites').text
assert 'Switch on Ruijie access points' in p
r = c.post(f'/sites/{SID}/wifidog', data={'csrf_token': tok(p), 'action': 'enable'}, follow_redirects=True).text
with app.app_context(): TOKEN = db.session.get(Site, SID).portal_token
AUTH_URL = f'http://radius.example.tz:5001/wifidog/{TOKEN}/'
assert AUTH_URL in r and 'web-auth template safenet' in r and 'No access point has contacted SafeNet yet' in r, r[-3000:]

AP = app.test_client()                                    # the access point's own HTTP calls
def ap(path, **q):
    return AP.get(f'/wifidog/{TOKEN}/{path}?' + urlencode(q), base_url='http://radius.example.tz:5001').text

# heartbeat
assert ap('ping/', gw_id='RG-AP820', sys_uptime=100) == 'Pong'
with app.app_context():
    s = db.session.get(Site, SID); assert s.wifidog_seen_at and s.wifidog_gw_id == 'RG-AP820'
assert ap('auth/', stage='login', token='nope', mac='AA:BB:CC:00:00:01') == 'Auth: 0'

# a guest arrives: the access point sends them to login/ over plain HTTP; SafeNet moves them to HTTPS
LOGIN_Q = dict(gw_address='192.168.110.1', gw_port='2060', gw_id='RG-AP820', mac='aa:bb:cc:00:00:01',
               ip='192.168.110.23', url='http://example.com/')
g = app.test_client()
r = g.get(f'/wifidog/{TOKEN}/login/?' + urlencode(LOGIN_Q), base_url='http://radius.example.tz:5001')
assert r.status_code == 302 and r.headers['Location'].startswith(f'https://radius.example.tz/wifidog/{TOKEN}/login/?gw_address=192.168.110.1'), r.headers.get('Location')
page = g.get(r.headers['Location'].replace('https://radius.example.tz', ''), base_url='https://radius.example.tz').text
assert 'Zulu Connect' in page and '1 Day' in page and f'action="/wifidog/{TOKEN}/guest/login"' in page and f'action="/wifidog/{TOKEN}/guest/buy"' in page

# voucher login -> back to the access point with a one-time token
assert "isn't valid" in html.unescape(g.post(f'/wifidog/{TOKEN}/guest/login', data={'code': '99999999', 'agree': '1'}, base_url='https://radius.example.tz').text)
r = g.post(f'/wifidog/{TOKEN}/guest/login', data={'code': '1111 0000', 'agree': '1'}, base_url='https://radius.example.tz')
assert r.status_code == 302 and r.headers['Location'].startswith('http://192.168.110.1:2060/wifidog/auth?token='), r.headers.get('Location')
T1 = parse_qs(urlparse(r.headers['Location']).query)['token'][0]
assert ap('auth/', stage='login', token=T1, mac='AA:BB:CC:00:00:09', ip='192.168.110.23') == 'Auth: 0'   # other phone
assert ap('auth/', stage='login', token=T1, mac='AA:BB:CC:00:00:01', ip='192.168.110.23', incoming=0, outgoing=0) == 'Auth: 1'
assert ap('auth/', stage='login', token=T1, mac='AA:BB:CC:00:00:01') == 'Auth: 0'                       # no replay
with app.app_context():
    ws = WifidogSession.query.filter_by(token=T1).one(); assert ws.status == 'active' and ws.username == '11110000'
    row = RadAcct.query.filter_by(acctuniqueid=ws.acct_uid).one(); assert row.calledstationid == f'wifidog-{SID}' and row.acctstoptime is None
    assert Voucher.query.filter_by(code='11110000').one().status == 'active'
# the access point then shows the portal page
st = g.get(f'/wifidog/{TOKEN}/portal/?gw_id=RG-AP820', base_url='https://radius.example.tz').text
assert "You're online" in st and 'example.com' in st and '/logout' not in st

# counters: usage recorded, still allowed
assert ap('auth/', stage='counters', token=T1, mac='AA:BB:CC:00:00:01', incoming=50_000_000, outgoing=4_000_000) == 'Auth: 1'
with app.app_context():
    row = RadAcct.query.filter_by(acctsessionid=T1[:32]).one(); assert row.acctoutputoctets == 50_000_000 and row.acctinputoctets == 4_000_000
d = c.get('/dashboard').text
assert '11110000' in d and 'Ruijie / WiFiDog' in d

# instant disconnect from the Live page -> next counters says Auth: 0 and the session closes
lv = c.get('/live').text
c.post('/live/disconnect', data={'csrf_token': tok(lv), 'username': '11110000'})
assert ap('auth/', stage='counters', token=T1, mac='AA:BB:CC:00:00:01', incoming=51_000_000, outgoing=4_100_000) == 'Auth: 0'
with app.app_context():
    assert WifidogSession.query.filter_by(token=T1).one().status == 'ended'
    assert RadAcct.query.filter_by(acctsessionid=T1[:32]).one().acctstoptime is not None

# expiry: time runs out -> Auth: 0
g2 = app.test_client(); g2.get(f'/wifidog/{TOKEN}/login/?' + urlencode({**LOGIN_Q, 'mac': 'aa:bb:cc:00:00:02'}), base_url='https://radius.example.tz')
T2 = parse_qs(urlparse(g2.post(f'/wifidog/{TOKEN}/guest/login', data={'code': '22220000', 'agree': '1'}, base_url='https://radius.example.tz').headers['Location']).query)['token'][0]
assert ap('auth/', stage='login', token=T2, mac='AA:BB:CC:00:00:02') == 'Auth: 1'
with app.app_context():
    ws = WifidogSession.query.filter_by(token=T2).one(); assert 3500 < (ws.expires_at - datetime.utcnow()).total_seconds() <= 3600
    ws.expires_at = datetime.utcnow() - timedelta(seconds=1); db.session.commit()
assert ap('auth/', stage='counters', token=T2, mac='AA:BB:CC:00:00:02') == 'Auth: 0'
# logout from the access point
g3 = app.test_client(); g3.get(f'/wifidog/{TOKEN}/login/?' + urlencode({**LOGIN_Q, 'mac': 'aa:bb:cc:00:00:03'}), base_url='https://radius.example.tz')
T3 = parse_qs(urlparse(g3.post(f'/wifidog/{TOKEN}/guest/login', data={'code': '33330000', 'agree': '1'}, base_url='https://radius.example.tz').headers['Location']).query)['token'][0]
assert ap('auth/', stage='login', token=T3, mac='AA:BB:CC:00:00:03') == 'Auth: 1'
assert ap('auth/', stage='logout', token=T3, mac='AA:BB:CC:00:00:03') == 'Auth: 0'
with app.app_context(): assert WifidogSession.query.filter_by(token=T3).one().status == 'ended'

# buying with mobile money
b = app.test_client(); b.get(f'/wifidog/{TOKEN}/login/?' + urlencode({**LOGIN_Q, 'mac': 'aa:bb:cc:00:00:04'}), base_url='https://radius.example.tz')
with app.app_context(): pkg = Package.query.filter_by(tenant_id=TID).one().id
r = b.post(f'/wifidog/{TOKEN}/guest/buy', data={'package_id': pkg, 'phone': '684000111', 'network': 'airtel', 'agree': '1'}, base_url='https://radius.example.tz')
assert r.status_code == 302 and '/guest/buy/wait?ref=SN' in r.headers['Location'], r.headers.get('Location')
wait = r.headers['Location']; ref = wait.split('ref=')[1]
with app.app_context():
    pm = Payment.query.filter_by(reference=ref).one(); assert pm.site_id == SID and pm.client_mac == 'AA-BB-CC-00-00-04'
assert 'Check your phone' in b.get(wait, base_url='https://radius.example.tz').text
pay['status'] = 'SUCCESS'
with app.app_context(): Payment.query.filter_by(reference=ref).update({'checked_at': None}); db.session.commit()
r = b.get(wait, base_url='https://radius.example.tz')
assert r.status_code == 302 and r.headers['Location'].startswith('http://192.168.110.1:2060/wifidog/auth?token='), r.text[-800:]
T4 = parse_qs(urlparse(r.headers['Location']).query)['token'][0]
assert ap('auth/', stage='login', token=T4, mac='AA:BB:CC:00:00:04') == 'Auth: 1'
st = b.get(f'/wifidog/{TOKEN}/portal/', base_url='https://radius.example.tz').text
with app.app_context(): code = Payment.query.filter_by(reference=ref).one().voucher.code
assert "You're online" in st and code in st and 'Payment received' in st

# safety: a guest can't be sent to an address outside the local network
e = app.test_client(); e.get(f'/wifidog/{TOKEN}/login/?' + urlencode({**LOGIN_Q, 'gw_address': '203.0.113.9', 'mac': 'aa:bb:cc:00:00:05'}), base_url='https://radius.example.tz')
with app.app_context():
    db.session.add_all([Voucher(tenant_id=TID, code='44440000', validity_minutes=60, batch='x', status='unused'),
                        RadCheck(username='44440000', attribute='Cleartext-Password', op=':=', value='44440000')]); db.session.commit()
r = e.post(f'/wifidog/{TOKEN}/guest/login', data={'code': '44440000', 'agree': '1'}, base_url='https://radius.example.tz')
assert r.status_code == 200 and 'connect to the Wi-Fi again' in r.text
with app.app_context(): assert Voucher.query.filter_by(code='44440000').one().status == 'unused'      # not used up
# access point message page
assert 'session has ended' in g.get(f'/wifidog/{TOKEN}/gw_message.php?message=denied', base_url='https://radius.example.tz').text

# switched off: access point gets Auth: 0, guests get 404
p = c.get('/sites').text
c.post(f'/sites/{SID}/wifidog', data={'csrf_token': tok(p), 'action': 'disable'})
assert ap('auth/', stage='counters', token=T4, mac='AA:BB:CC:00:00:04') == 'Auth: 0'
assert app.test_client().get(f'/wifidog/{TOKEN}/login/?' + urlencode(LOGIN_Q), base_url='https://radius.example.tz').status_code == 404
print('WIFIDOG OK')
