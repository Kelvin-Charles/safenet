"""UniFi: the controller client against a fake controller (classic and UniFi OS), then the guest flow through
/guest/s/<site>/ -> /unifi/<token> with SafeNet's hosted controller and a business's own."""
import html, json, os, re, sys, threading
from datetime import datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel',
                  PUBLIC_URL='https://radius.example.tz', UNIFI_HOSTED_URL='https://127.0.0.1:8445', UNIFI_HOSTED_USER='safenet',
                  UNIFI_HOSTED_PASSWORD='pw', UNIFI_PORTAL_HOST='radius.example.tz', UNIFI_INFORM_URL='http://radius.example.tz:8089/inform')
sys.path.insert(0, os.getcwd())
import unifi

# 1. the client, against a fake controller ------------------------------------------------------------------------
calls = []


class Fake(BaseHTTPRequestHandler):
    os_mode = False

    def log_message(self, *a):
        pass

    def _reply(self, code, data=None, headers=()):
        body = json.dumps({'meta': {'rc': 'ok' if code == 200 else 'error', 'msg': ''}, 'data': data or []}).encode()
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        calls.append(('POST', self.path, body, self.headers.get('X-CSRF-Token')))
        if self.path == '/api/auth/login':
            return self._reply(200, headers=[('X-CSRF-Token', 'csrf1'), ('Set-Cookie', 'TOKEN=t; Path=/')]) if Fake.os_mode else self._reply(404)
        if self.path == '/api/login':
            ok = body.get('password') == 'pw'
            return self._reply(200 if ok else 400, headers=[('Set-Cookie', 'unifises=s; Path=/')] if ok else ())
        if self.path.endswith('/cmd/sitemgr'):
            return self._reply(200, [{'name': 'ab12cd34', 'desc': body['desc']}])
        return self._reply(200)

    def do_GET(self):
        calls.append(('GET', self.path, None, self.headers.get('X-CSRF-Token')))
        if self.path.endswith('/api/self/sites'):
            return self._reply(200, [{'name': 'default', 'desc': 'Default'}])
        if self.path.endswith('/stat/sta'):
            return self._reply(200, [{'mac': 'aa:bb:cc:00:00:01', 'tx_bytes': 5000, 'rx_bytes': 700, 'ip': '10.0.0.5', 'ap_mac': 'f4:92:bf:00:00:01'}])
        return self._reply(200)


srv = ThreadingHTTPServer(('127.0.0.1', 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'

c = unifi.Controller(base, 'admin', 'pw')
assert c.check('default') == 'Default' and c.unifi_os is False
c.authorize('default', 'AA-BB-CC-00-00-01', 90, up_kbps=2048, down_kbps=5120, ap_mac='F4:92:BF:00:00:01')
assert calls[-1][:3] == ('POST', '/api/s/default/cmd/stamgr', {'cmd': 'authorize-guest', 'mac': 'aa:bb:cc:00:00:01', 'minutes': 90,
                                                                'up': 2048, 'down': 5120, 'ap_mac': 'f4:92:bf:00:00:01'})
c.unauthorize('default', 'AA-BB-CC-00-00-01')
assert calls[-1][2] == {'cmd': 'unauthorize-guest', 'mac': 'aa:bb:cc:00:00:01'}
assert c.create_site('Zulu #1') == 'ab12cd34' and calls[-1][2] == {'cmd': 'add-site', 'desc': 'Zulu #1'}
c.adopt('ab12cd34', 'F4-92-BF-00-00-09'); assert calls[-1][1:3] == ('/api/s/ab12cd34/cmd/devmgr', {'cmd': 'adopt', 'mac': 'f4:92:bf:00:00:09'})
try:
    unifi.Controller(base, 'admin', 'wrong').login(); raise SystemExit('wrong password accepted')
except unifi.UnifiError as e:
    assert 'refused the login' in str(e)
# UniFi OS: /api/auth/login, the Network API under /proxy/network, the CSRF token sent back
Fake.os_mode = True
o = unifi.Controller(base, 'admin', 'pw')
o.clients('default')
assert o.unifi_os is True and calls[-1][:2] == ('GET', '/proxy/network/api/s/default/stat/sta') and calls[-1][3] == 'csrf1'
assert unifi.mac('AABBCC000001') == 'aa:bb:cc:00:00:01' and unifi.mac('nope') == ''
print('client OK')

# 2. the guest flow ---------------------------------------------------------------------------------------------------
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
pay = {'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay['status'], 'collectedAmount': '1000'}
import app as appmod
from app import app, db
import migrations
from models import Admin, Tenant, Site, Package, Payment, Voucher, RadCheck, RadAcct
from tenancy import tenant_sites


class FakeController:
    """Stands in for unifi.Controller in the app: records what SafeNet asks."""
    log = []
    online = {}            # mac -> client dict

    def __init__(self, url, username, password, verify_tls=False, public_only=False):
        self.url = url

    def create_site(self, desc):
        FakeController.log.append(('create_site', desc)); return 'k7x2m9qa'

    def ensure_wlan(self, site, name):
        FakeController.log.append(('wlan', site, name)); return 'w1'

    def ensure_portal(self, site, host, allowed):
        FakeController.log.append(('portal', site, host)); return []

    def check(self, site):
        if self.url.endswith('bad'):
            raise unifi.UnifiError('the UniFi controller refused the login: check the username and password')
        return 'Default'

    def devices(self, site):
        return [{'mac': 'f4:92:bf:aa:00:01'}] if self.url.startswith('https://own-b') else [{'mac': 'f4:92:bf:bb:00:01'}]

    def adopt(self, site, m):
        FakeController.log.append(('adopt', site, m))

    def authorize(self, site, mac, minutes, **kw):
        FakeController.log.append(('authorize', self.url, site, mac, minutes, kw.get('down_kbps')))
        FakeController.online[unifi.mac(mac)] = {'mac': unifi.mac(mac), 'tx_bytes': 0, 'rx_bytes': 0, 'ap_mac': 'f4:92:bf:00:00:01'}

    def unauthorize(self, site, mac):
        FakeController.log.append(('unauthorize', site, unifi.mac(mac)))
        FakeController.online.pop(unifi.mac(mac), None)

    def clients(self, site):
        return list(FakeController.online.values())


unifi.Controller = FakeController
appmod.omada.public_address_problem = lambda url: None if url.startswith('https://own') else 'not public'
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add_all([o, Package(tenant_id=t.id, name='1 Day', price=Decimal(1000), validity_minutes=1440)])
    for code in ('11110000', '22220000', '33330000'):
        db.session.add_all([Voucher(tenant_id=t.id, code=code, validity_minutes=60, batch='x', status='unused'),
                            RadCheck(username=code, attribute='Cleartext-Password', op=':=', value=code)])
    db.session.commit(); TID = t.id; SID = tenant_sites(TID)[0].id

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = c.get('/sites').text
assert "Use SafeNet's controller" in html.unescape(p)
r = c.post(f'/sites/{SID}/unifi', data={'csrf_token': tok(p), 'action': 'hosted', 'wifi_name': 'Zulu Free'}, follow_redirects=True).text
assert "Connected to SafeNet's UniFi controller" in html.unescape(r) and 'set-inform http://radius.example.tz:8089/inform' in r, r[-2000:]
assert ('wlan', 'k7x2m9qa', 'Zulu Free') in FakeController.log and ('portal', 'k7x2m9qa', 'radius.example.tz') in FakeController.log
with app.app_context():
    s = db.session.get(Site, SID); TOKEN = s.portal_token
    assert s.unifi_hosted and s.unifi_site == 'k7x2m9qa' and s.unifi_ssid == 'Zulu Free' and s.unifi_ready
r = c.post(f'/sites/{SID}/unifi', data={'csrf_token': tok(p), 'action': 'adopt', 'macs': 'F4:92:BF:00:00:01\nnot-a-mac'}, follow_redirects=True).text
assert ('adopt', 'k7x2m9qa', 'f4:92:bf:00:00:01') in FakeController.log and 'Adopting 1 access point' in r

# a guest arrives from the controller
B = 'https://radius.example.tz'
g = app.test_client()
q = urlencode({'ap': 'f4:92:bf:00:00:01', 'id': 'aa:bb:cc:00:00:01', 't': '1700000000', 'url': 'http://example.com/', 'ssid': 'Zulu Free'})
r = g.get(f'/guest/s/k7x2m9qa/?{q}', base_url='http://radius.example.tz')
assert r.status_code == 302 and r.headers['Location'].endswith(f'/unifi/{TOKEN}')
page = g.get(f'/unifi/{TOKEN}', base_url=B).text
assert 'Zulu Connect' in page and '1 Day' in page and f'action="/unifi/{TOKEN}/login"' in page and f'action="/unifi/{TOKEN}/buy"' in page
assert app.test_client().get('/guest/s/nosuchsite/?id=aa').status_code == 404
assert "isn't valid" in html.unescape(g.post(f'/unifi/{TOKEN}/login', data={'code': '99999999', 'agree': '1'}, base_url=B).text)
r = g.post(f'/unifi/{TOKEN}/login', data={'code': '1111 0000', 'agree': '1'}, base_url=B).text
assert "You're online" in r and 'example.com' in r
last = [x for x in FakeController.log if x[0] == 'authorize'][-1]
assert last[2:5] == ('k7x2m9qa', 'aa:bb:cc:00:00:01', 60)
with app.app_context():
    row = RadAcct.query.filter_by(calledstationid=f'unifi-{SID}', username='11110000').one()
    assert row.callingstationid == 'AA-BB-CC-00-00-01' and row.acctstoptime is None

# usage sync: data counted; when the voucher ends, the phone is sent back to the login page
FakeController.online['aa:bb:cc:00:00:01'].update(tx_bytes=40_000_000, rx_bytes=3_000_000)
with app.app_context():
    appmod._unifi_sync_site(db.session.get(Site, SID))
    row = RadAcct.query.filter_by(calledstationid=f'unifi-{SID}', username='11110000').one()
    assert row.acctoutputoctets == 40_000_000 and row.acctinputoctets == 3_000_000
    FakeController.online['aa:bb:cc:00:00:01'].update(tx_bytes=50_000_000, rx_bytes=3_500_000)
    appmod._unifi_sync_site(db.session.get(Site, SID))
    row = RadAcct.query.filter_by(calledstationid=f'unifi-{SID}', username='11110000').one()
    assert row.acctoutputoctets == 50_000_000
    v = Voucher.query.filter_by(code='11110000').one(); v.expires_at = datetime.utcnow() - timedelta(minutes=1); db.session.commit()
    appmod._unifi_sync_site(db.session.get(Site, SID))
    row = RadAcct.query.filter_by(calledstationid=f'unifi-{SID}', username='11110000').one()
    assert row.acctstoptime is not None and ('unauthorize', 'k7x2m9qa', 'aa:bb:cc:00:00:01') in FakeController.log

# buying: pay, then online
g2 = app.test_client()
g2.get('/guest/s/k7x2m9qa/?' + urlencode({'ap': 'f4:92:bf:00:00:01', 'id': 'aa:bb:cc:00:00:02', 'url': 'http://x/'}), base_url=B)
with app.app_context(): PID = Package.query.filter_by(tenant_id=TID).first().id
r = g2.post(f'/unifi/{TOKEN}/buy', data={'package_id': PID, 'phone': '684000111', 'network': 'airtel', 'agree': '1'}, base_url=B)
assert r.status_code == 302 and '/buy/wait?ref=' in r.headers['Location'], r.text[:300]
wait = r.headers['Location'].replace(B, '').replace('http://localhost', '')
ref = wait.split('ref=')[1]
pay['status'] = 'SUCCESS'
with app.app_context():
    pm = Payment.query.filter_by(reference=ref).one(); assert pm.client_mac == 'AA-BB-CC-00-00-02'; pm.checked_at = None; db.session.commit()
r = g2.get(wait, base_url=B).text
assert "You're online" in r and 'Payment received' in r
# after buying, Android phones go on to the SafeNet app on Google Play (the page decides on the phone)
assert 'id="play-card" href="https://play.google.com/store/apps/details?id=com.safezonetz.safenet_app"' in r and '/Android/i.test' in r
assert [x for x in FakeController.log if x[0] == 'authorize'][-1][3] == 'aa:bb:cc:00:00:02'

# Disconnect from the dashboard sends the phone back to the login page
with app.app_context():
    code = Payment.query.filter_by(reference=ref).one().voucher.code
    appmod.disconnect_subscriber(TID, code); db.session.commit()
import time; time.sleep(0.3)
assert ('unauthorize', 'k7x2m9qa', 'aa:bb:cc:00:00:02') in FakeController.log

# a business's own controllers: two sites both called "default", told apart by the access point
with app.app_context():
    s2 = Site(tenant_id=TID, name='Branch B'); db.session.add(s2); db.session.commit(); S2 = s2.id
p = c.get('/sites').text
r = c.post(f'/sites/{S2}/unifi', data={'csrf_token': tok(p), 'action': 'own', 'unifi_url': 'https://own-bad', 'unifi_user': 'u',
                                      'unifi_password': 'p', 'unifi_site': 'default'}, follow_redirects=True).text
assert 'refused the login' in html.unescape(r)
r = c.post(f'/sites/{S2}/unifi', data={'csrf_token': tok(p), 'action': 'own', 'unifi_url': 'https://own-b.example', 'unifi_user': 'u',
                                      'unifi_password': 'p', 'unifi_site': 'default'}, follow_redirects=True).text
assert 'Connected to your UniFi controller' in r
assert c.post(f'/sites/{S2}/unifi', data={'csrf_token': tok(p), 'action': 'own', 'unifi_url': 'http://10.0.0.5:8443', 'unifi_user': 'u',
                                          'unifi_password': 'p'}, follow_redirects=True).status_code == 200
with app.app_context():
    s2 = db.session.get(Site, S2); assert s2.unifi_url == 'https://own-b.example' and s2.unifi_aps == 'f4:92:bf:aa:00:01'
    other = Tenant(name='Other', slug='other', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(other); db.session.flush()
    from secretbox import encrypt
    os3 = Site(tenant_id=other.id, name='Other', portal_token='othertoken123456', unifi_url='https://own-c.example', unifi_user='u',
               unifi_password_enc=encrypt('p'), unifi_site='default'); db.session.add(os3); db.session.commit()
    T2 = db.session.get(Site, S2).portal_token
r = app.test_client().get('/guest/s/default/?' + urlencode({'ap': 'f4:92:bf:aa:00:01', 'id': 'aa:bb:cc:00:00:03'}), base_url=B)
assert r.status_code == 302 and r.headers['Location'].endswith(f'/unifi/{T2}'), r.headers.get('Location')
r = app.test_client().get('/guest/s/default/?' + urlencode({'ap': 'f4:92:bf:bb:00:01', 'id': 'aa:bb:cc:00:00:04'}), base_url=B)
assert r.status_code == 302 and r.headers['Location'].endswith('/unifi/othertoken123456'), r.headers.get('Location')

# remove
c.post(f'/sites/{SID}/unifi', data={'csrf_token': tok(p), 'action': 'remove'})
with app.app_context(): assert not db.session.get(Site, SID).unifi_ready
assert app.test_client().get(f'/unifi/{TOKEN}').status_code == 404
for slug in ('unifi', 'radius-aps', 'start'):
    assert app.test_client().get(f'/docs/{slug}').status_code == 200
print('UNIFI OK')
