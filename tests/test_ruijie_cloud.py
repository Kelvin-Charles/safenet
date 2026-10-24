"""Ruijie Cloud vouchers (Reyee RG-RAP access points): connect a site, codes SafeNet makes or sells are created on
Ruijie Cloud in the package with the same duration, and the guest app sells for the site in its link."""
import html, os, re, sys
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS', 'collectedAmount': '1000'}
import ruijie
from datetime import datetime, timedelta
made, down, can_create, created, own_codes = [], [False], [False], [], [True]
pkgs = [{'user_group': 'ug1', 'profile': 'pf1', 'minutes': 60, 'name': '1 Hour'},
        {'user_group': 'ug2', 'profile': 'pf2', 'minutes': 1440, 'name': '1 Day'}]


class FakeCloud:
    def __init__(self, base, appid, secret):
        assert ruijie.valid_cloud(base)
        self.base, self.secret = base, secret

    def token(self):       # this account lives on the Global server; the others don't know it
        if self.base != 'https://cloud.ruijienetworks.com' or self.secret != 'shh':
            raise ruijie.RuijieError('Ruijie Cloud refused the App ID or secret: Login failed')

    def projects(self):
        return [('9001', 'JRIIT Hostel')]

    def packages(self, group_id):
        assert group_id == '9001'
        return list(pkgs)

    def vouchers(self, group_id):
        assert group_id == '9001'
        return list(ruijie_list)

    def clients(self, group_id):
        return list(phones)

    def create_package(self, group_id, name, minutes, devices=1, price='', down_kbps=0, up_kbps=0):
        if not can_create[0]:
            raise ruijie.RuijieError('Ruijie Cloud: You do not have permission to perform this operation')
        created.append((group_id, name, minutes, devices, price, down_kbps))
        pkgs.append({'user_group': f'ug{len(pkgs) + 1}', 'profile': f'pf{len(pkgs) + 1}', 'minutes': minutes, 'name': name})

    def create_voucher(self, group_id, code, package):
        if down[0]:
            raise ruijie.RuijieError('Ruijie Cloud could not be reached: timed out')
        if not own_codes[0]:
            raise ruijie.RuijieError('Ruijie Cloud: Invalid code')
        made.append((group_id, code, package['user_group']))

    def generate_voucher(self, group_id, package, digits=8):
        code = f'7{len(made):07d}'
        made.append((group_id, code, package['user_group']))
        return code


# the real client's project list: only buildings (projects), not Ruijie's placeholder entries
RealCloud = ruijie.Cloud
real = RealCloud('https://cloud-eu.ruijienetworks.com', 'a', 'b')
real.call = lambda *a, **k: {'groups': [{'groupId': 0, 'name': 'dumy', 'subGroups': [
    {'groupId': 10331303, 'name': 'Safetanzania.tech', 'type': 'ROOT', 'subGroups': [
        {'groupId': 10331699, 'name': 'SafeNet Free WiFi', 'type': 'BUILDING'}]}]}]}
assert real.projects() == [('10331699', 'SafeNet Free WiFi')], real.projects()
ruijie.Cloud = FakeCloud
ruijie_list, phones = [], []
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
from app import app, db
import migrations
from models import Admin, Tenant, Package, Voucher, Site, RadCheck
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    SID = tenant_sites(TID)[0].id
    other = Site(tenant_id=TID, name='Town'); db.session.add(other); db.session.flush(); OTHER = other.id
    db.session.add_all([Package(tenant_id=TID, name='Saa 1', price=Decimal(500), validity_minutes=60, site_id=SID),
                        Package(tenant_id=TID, name='Siku 1', price=Decimal(1000), validity_minutes=1440),
                        Package(tenant_id=TID, name='Wiki 1', price=Decimal(5000), validity_minutes=10080, site_id=SID),
                        Package(tenant_id=TID, name='Town only', price=Decimal(700), validity_minutes=120, site_id=OTHER)])
    db.session.commit()
    PKG_DAY = Package.query.filter_by(name='Siku 1').one().id

assert not ruijie.valid_cloud('https://evil.example.com') and not ruijie.valid_cloud('http://cloud-as.ruijienetworks.com')
assert ruijie.valid_cloud('https://cloud-as.ruijienetworks.com')

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = c.get('/sites').text
post = lambda **d: c.post(f'/sites/{SID}/ruijie-cloud', data={'csrf_token': tok(p), **d}, follow_redirects=True)
# only Ruijie's own servers
assert 'Choose the Ruijie Cloud server' in html.unescape(post(action='save', cloud='https://evil.example.com', appid='a', secret='shh').text)
# wrong secret: every server refuses it
r = html.unescape(post(action='save', cloud='https://cloud-as.ruijienetworks.com', appid='app1', secret='nope').text)
assert 'No Ruijie Cloud server accepted this App ID and secret' in r
with app.app_context(): assert not db.session.get(Site, SID).ruijie_appid
# keys made on another server than the one chosen: SafeNet finds it
r = html.unescape(post(action='save', cloud='https://cloud-as.ruijienetworks.com', appid='app1', secret='shh').text)
assert 'These keys belong to the Global (cloud) server' in r
with app.app_context(): assert db.session.get(Site, SID).ruijie_cloud_url == 'https://cloud.ruijienetworks.com'
assert 'Ruijie Cloud connected' in r and 'Project: JRIIT Hostel' in r and '1 Hour · 1 hour' in r
# 1 week has no Ruijie package: SafeNet tried to make it, Ruijie refused, and the page says why
warn = r[r.index('no Ruijie package with the same duration'):][:800]
assert 'Wiki 1' in warn and 'Ruijie refused: Ruijie Cloud: You do not have permission' in warn
with app.app_context():
    s = db.session.get(Site, SID)
    assert s.ruijie_ready and s.ruijie_secret_enc and 'shh' not in s.ruijie_secret_enc and s.portal_token
    TOKEN = s.portal_token
assert f'/app/jriit?s={TOKEN}' in r and 'shh' not in r
# saving again without the secret keeps it
assert 'Ruijie Cloud connected' in html.unescape(post(action='save', cloud='https://cloud-as.ruijienetworks.com', appid='app1').text)

# generated vouchers wait for Ruijie Cloud, then are made there in the package with the same duration
r = c.get('/vouchers/generate')
c.post('/vouchers/generate', data={'csrf_token': tok(r.text), 'count': 3, 'validity_value': 1, 'validity_unit': 'hours', 'max_devices': 1, 'plan_id': 0})
with app.app_context():
    codes = [v.code for v in Voucher.query.filter_by(ruijie_state='pending')]
    assert len(codes) == 3
    appmod._ruijie_push_due()
    assert made == [('9001', code, 'ug1') for code in sorted(codes, key=lambda x: Voucher.query.filter_by(code=x).one().id)]
    assert Voucher.query.filter_by(ruijie_state='ok').count() == 3
# Ruijie Cloud down: the codes wait and the site shows why; they go once it's back
with app.app_context():
    v = appmod._create_vouchers(1, None, 1440, None, 'x', tenant=TID, site_id=SID)[0]; db.session.commit(); CODE = v.code
    down[0] = True; appmod._ruijie_push_due()
    assert Voucher.query.filter_by(code=CODE).one().ruijie_state == 'pending' and 'could not be reached' in db.session.get(Site, SID).ruijie_error
    down[0] = False; appmod._ruijie_push_due()
    assert Voucher.query.filter_by(code=CODE).one().ruijie_state == 'ok' and db.session.get(Site, SID).ruijie_error is None
    # a duration with no Ruijie package fails, and says what to create
    w = appmod._create_vouchers(1, None, 10080, None, 'x', tenant=TID, site_id=SID)[0]; db.session.commit()
    WCODE = w.code
    appmod._ruijie_push_due()
    assert Voucher.query.filter_by(code=w.code).one().ruijie_state == 'failed' and 'No Ruijie package lasts 7 days' in db.session.get(Site, SID).ruijie_error
    # another site's codes aren't copied
    o = appmod._create_vouchers(1, None, 60, None, 'x', tenant=TID, site_id=OTHER)[0]; db.session.commit()
    assert o.ruijie_state is None
p = html.unescape(c.get('/sites').text)
assert '4 codes made on Ruijie Cloud, 0 waiting, 1 failed' in p and 'Try failed codes again' in p
# when Ruijie lets the keys create packages, SafeNet makes the missing one and the failed code goes through
can_create[0] = True
r = html.unescape(post(action='retry').text)
assert created == [('9001', 'SafeNet 7 days', 10080, 1, '5000', 0)], created
assert 'no Ruijie package with the same duration' not in r and 'SafeNet 7 days · 7 days' in r
with app.app_context():
    appmod._ruijie_push_due()
    assert Voucher.query.filter_by(code=WCODE).one().ruijie_state == 'ok' and made[-1][2] == 'ug3'
# a package added in SafeNet later is made on Ruijie Cloud straight away
f = c.get('/packages/add').text
c.post('/packages/add', data={'csrf_token': tok(f), 'name': 'Mwezi', 'price': '20000', 'validity_value': 30, 'validity_unit': 'days',
                              'max_devices': 2, 'plan_id': 0, 'site_id': SID, 'is_active': 'y', 'show_on_portal': 'y'})
assert created[-1][1:4] == ('SafeNet 30 days', 43200, 2), created

# the guest app from the Ruijie login page link: this site's packages, buy straight away, the code to type on Ruijie's page
g = app.test_client()
me = g.post('/app/jriit/api/me', json={'tokens': [], 'site': TOKEN}).get_json()
assert me['ruijie'] and me['can_buy'] and sorted(x['name'] for x in me['packages']) == ['Mwezi', 'Saa 1', 'Siku 1', 'Wiki 1']
b = g.post('/app/jriit/api/buy', json={'tokens': [], 'site': TOKEN, 'package_id': PKG_DAY, 'phone': '0684000111', 'network': 'airtel'}).get_json()
paid = g.get(f'/app/jriit/api/pay/{b["reference"]}').get_json()
assert paid['status'] == 'paid' and paid['ruijie'] and paid['code']
assert paid['ready'] is False                         # not on Ruijie Cloud yet: the login page waits
with app.app_context():
    v = Voucher.query.filter_by(code=paid['code']).one()
    assert v.site_id == SID and v.ruijie_state == 'pending'
    appmod._ruijie_push_due()
    assert made[-1] == ('9001', paid['code'], 'ug2')
assert g.get(f'/app/jriit/api/pay/{b["reference"]}').get_json()['ready'] is True
# Ruijie's login page calls this API from its own address
r = g.options('/app/jriit/api/me', headers={'Origin': 'https://portal.ruijienetworks.com', 'Access-Control-Request-Method': 'POST'})
assert r.status_code == 200 and r.headers['Access-Control-Allow-Origin'] == '*' and 'Content-Type' in r.headers['Access-Control-Allow-Headers']
assert g.post('/app/jriit/api/me', json={'tokens': [], 'site': TOKEN}).headers['Access-Control-Allow-Origin'] == '*'
assert 'Access-Control-Allow-Origin' not in c.get('/sites').headers                  # not the admin pages

# the login page for Ruijie Cloud's Custom HTML, made for this site
import io, json as _json, zipfile
z = c.get(f'/sites/{SID}/ruijie-portal.zip')
assert z.status_code == 200 and z.mimetype == 'application/zip' and 'safenet-ruijie-jriit' in z.headers['Content-Disposition']
files = zipfile.ZipFile(io.BytesIO(z.data))
names = set(files.namelist())
assert {'index.html', 'loadConfig.json', 'css/index.css', 'js/index.js', 'js/language.js', 'js/i18n/i18n.js', 'js/jquery/jquery.min.js', 'img/logo.png'} <= names
js = files.read('js/index.js').decode()
cfg = _json.loads(re.search(r'var SAFENET = (\{.*?\});\n', js, re.S).group(1))
assert cfg['slug'] == 'jriit' and cfg['site'] == TOKEN and cfg['base'].startswith('http')
# the same login page SafeNet shows: tabs, packages, network logos, terms, in both languages
sw, en = cfg['pages']['sw'], cfg['pages']['en']
assert 'id="tab-buy"' in sw['body'] and 'Nunua kifurushi' in sw['body'] and 'Buy package' in en['body'] and 'Siku 1' in sw['body']
assert 'name="agree"' in sw['body'] and 'img/airtel.png' in sw['body'] and '.pkg' in cfg['css'] and '--brand:' in sw['vars']
assert '@@AMOUNT@@' in sw['wait'] and '@@CODE@@' in sw['connecting'] and 'Lipa {price}' == cfg['texts']['sw']['pay']
assert {'img/mpesa.png', 'img/airtel.png'} <= names
lc = files.read('loadConfig.json').decode()
assert lc.startswith('loadConfig(') and '"voucher"' in lc and 'fixaccount' not in lc
assert app.test_client().get(f'/sites/{SID}/ruijie-portal.zip').status_code in (302, 401)   # admins only

# Ruijie won't take codes it didn't make: it makes one, SafeNet uses it (RADIUS too), and the SMS has the final code
own_codes[0] = False
texts = []
appmod._guest_sms = lambda payment, phone, text, kind: texts.append(text)
appmod._sms_on = lambda tenant: True
b = g.post('/app/jriit/api/buy', json={'tokens': [], 'site': TOKEN, 'package_id': PKG_DAY, 'phone': '0684000222', 'network': 'airtel'}).get_json()
paid = g.get(f'/app/jriit/api/pay/{b["reference"]}').get_json()
assert paid['ready'] is False and texts == []                       # no SMS yet: the code may change
OLD = paid['code']
with app.app_context():
    appmod._ruijie_push_due()
    v = Voucher.query.filter_by(code=made[-1][1]).one()
    assert v.code != OLD and v.ruijie_state == 'ok' and made[-1][2] == 'ug2'
    assert RadCheck.query.filter_by(username=v.code, value=v.code).count() == 1 and RadCheck.query.filter_by(username=OLD).count() == 0
    NEW = v.code
    assert _json.loads(db.session.get(Site, SID).ruijie_packages)['ruijie_codes'] is True        # remembered for the site
paid = g.get(f'/app/jriit/api/pay/{b["reference"]}').get_json()
assert paid['ready'] is True and paid['code'] == NEW and len(texts) == 1 and NEW in texts[0] and OLD not in texts[0]
# generated vouchers get Ruijie's codes too; printing leaves out the ones not made yet
r = c.get('/vouchers/generate')
c.post('/vouchers/generate', data={'csrf_token': tok(r.text), 'count': 2, 'validity_value': 1, 'validity_unit': 'hours', 'max_devices': 1, 'plan_id': 0, 'batch': 'reyee'})
pr = html.unescape(c.get('/vouchers/print?batch=reyee').text)
assert '2 codes are still being made on Ruijie Cloud' in pr
with app.app_context():
    appmod._ruijie_push_due()
    codes = sorted(v.code for v in Voucher.query.filter_by(batch='reyee'))
    assert all(c_.startswith('7') for c_ in codes) and all(Voucher.query.filter_by(code=c_).one().ruijie_state == 'ok' for c_ in codes)
pr = html.unescape(c.get('/vouchers/print?batch=reyee').text)
assert 'still being made' not in pr and all(c_ in pr for c_ in codes)

# guests online: Ruijie says which codes have a phone on now; they show on Live as Reyee sessions, with Ruijie's times
from models import RadAcct
import time as _time; login_ms = int((_time.time() - 1800) * 1000)
ruijie_list[:] = [{'voucherCode': NEW, 'loginTime': login_ms, 'expiryTime': login_ms + 1440 * 60000, 'currentClients': 1, 'usedTime': 30},
                  {'voucherCode': 'not-ours', 'currentClients': 1}]
with app.app_context():
    appmod._ruijie_sync_site(db.session.get(Site, SID))
    v = Voucher.query.filter_by(code=NEW).one()
    assert v.status == 'active' and abs((v.first_used_at - (datetime.utcnow() - timedelta(minutes=30))).total_seconds()) < 5
    assert abs((v.expires_at - v.first_used_at).total_seconds() - 1440 * 60) < 2
    row = RadAcct.query.filter_by(calledstationid=f'ruijie-{SID}', username=NEW).one()
    assert row.acctstoptime is None and RadAcct.query.filter_by(username='not-ours').count() == 0
    appmod._ruijie_sync_site(db.session.get(Site, SID))                     # still online: same session, not a second one
    assert RadAcct.query.filter_by(calledstationid=f'ruijie-{SID}').count() == 1
phones[:] = [{'mac': '06:5A:00:00:00:01', 'ip': '192.168.0.10', 'ssid': 'U-SMART CONNECT', 'ap': 'Ruijie RAP6262', 'band': '2.4G',
               'rssi': -94, 'down_kb': 322888, 'up_kb': 143192, 'since': login_ms, 'online_ms': 813000},
              {'mac': '06:5A:00:00:00:02', 'ip': '192.168.0.11', 'ssid': 'U-SMART CONNECT', 'ap': 'Ruijie RAP6262', 'band': '5G',
               'rssi': -60, 'down_kb': 10, 'up_kb': 5, 'since': login_ms, 'online_ms': 1000}]
with app.app_context():
    appmod._ruijie_sync_site(db.session.get(Site, SID))
lv = c.get('/api/live').get_json()
# every phone Ruijie lists, with its real address, signal and traffic (KB from Ruijie, bytes here), most data first
assert [(w['mac'], w['ip'], w['rssi'], w['down'], w['up']) for w in lv['wifi']] == \
    [('06:5A:00:00:00:01', '192.168.0.10', -94, 322888 * 1024, 143192 * 1024), ('06:5A:00:00:00:02', '192.168.0.11', -60, 10240, 5120)]
assert lv['wifi'][0]['ssid'] == 'U-SMART CONNECT' and lv['wifi'][0]['ap'] == 'Ruijie RAP6262' and lv['wifi'][0]['since']
assert 'Phones on the Reyee Wi-Fi now' in html.unescape(c.get('/live').text)
assert [(x['user'], x['router']) for x in lv['online']] == [(NEW, 'Reyee · TICD')] or \
       [x['user'] for x in lv['online']] == [NEW] and lv['online'][0]['router'].startswith('Reyee · '), lv['online']
ruijie_list[0]['currentClients'] = 0                                        # the phone left
with app.app_context():
    appmod._ruijie_sync_site(db.session.get(Site, SID))
    assert RadAcct.query.filter_by(calledstationid=f'ruijie-{SID}', username=NEW).one().acctstoptime is not None

# removing it stops the copying
assert 'Ruijie Cloud removed' in html.unescape(post(action='remove').text)
with app.app_context():
    assert not db.session.get(Site, SID).ruijie_ready and Voucher.query.filter(Voucher.ruijie_state.in_(('pending', 'sending'))).count() == 0
print('RUIJIE CLOUD OK')
