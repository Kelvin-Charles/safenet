"""TP-Link Omada external portal: SafeNet's login page + a fake Omada Controller."""
import html, json, os, re, sys, threading, time
from datetime import datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
pay_state = {'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay_state['status'], 'collectedAmount': '1000'}
from app import app, db
import migrations, omada
from models import Admin, Tenant, Site, Package, Payment, Voucher, RadCheck, RadAcct
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)

# --- fake Omada Controller (v5 external portal API)
CID = 'abc123omadac'
ctl = {'authorized': [], 'logins': 0, 'up': True}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, obj, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        if cookie: self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/api/info':
            return self.reply({'errorCode': 0, 'result': {'omadacId': CID, 'controllerVer': '5.13'}})
        self.send_error(404)
    def do_POST(self):
        if not ctl['up']:
            return self.reply({'errorCode': -1, 'msg': 'down'})
        data = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if self.path == f'/{CID}/api/v2/hotspot/login':
            ok = data == {'name': 'op', 'password': 'op-pass'}
            ctl['logins'] += 1
            return self.reply({'errorCode': 0 if ok else -30109, 'msg': 'bad login', 'result': {'token': 'TOK1'} if ok else {}},
                              cookie='TPOMADA_SESSIONID=S1; Path=/')
        if self.path == f'/{CID}/api/v2/hotspot/extPortal/auth':
            if self.headers.get('Csrf-Token') != 'TOK1' or 'TPOMADA_SESSIONID=S1' not in (self.headers.get('Cookie') or ''):
                return self.reply({'errorCode': -1200, 'msg': 'not logged in'})
            ctl['authorized'].append(data)
            return self.reply({'errorCode': 0})
        self.send_error(404)
srv = ThreadingHTTPServer(('127.0.0.1', 0), Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
CTL_URL = f'http://127.0.0.1:{srv.server_address[1]}'

# the client module on its own
c0 = omada.Controller(CTL_URL, 'op', 'op-pass')
assert c0.check() == CID
c0.authorize('AA-BB-CC-DD-EE-01', 3600, site='siteX', ap_mac='11-22-33-44-55-66', ssid='Guest', radio_id='1')
a = ctl['authorized'][-1]
assert a == {'clientMac': 'AA-BB-CC-DD-EE-01', 'site': 'siteX', 'time': '3600000000', 'authType': '4',
             'apMac': '11-22-33-44-55-66', 'ssidName': 'Guest', 'radioId': '1'}, a
try:
    omada.Controller(CTL_URL, 'op', 'wrong').check(); raise AssertionError('bad password accepted')
except omada.OmadaError as e:
    assert 'bad login' in str(e)
try:
    omada.Controller('http://127.0.0.1:9', 'op', 'x', timeout=2).check(); raise AssertionError
except omada.OmadaError as e:
    assert "can't reach" in str(e)

# --- tenant + site
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Hotel Kilimanjaro', slug='kili', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add_all([o, Package(tenant_id=t.id, name='1 Day', price=Decimal(1000), validity_minutes=1440)])
    db.session.commit(); TID = t.id
    from tenancy import tenant_sites; SID = tenant_sites(TID)[0].id

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = c.get('/sites').text
assert 'Omada' in p
assert "Use SafeNet's controller" not in p                       # no hosted controller on this server
r = c.post(f'/sites/{SID}/omada', data={'csrf_token': tok(p), 'omada_url': CTL_URL + '/', 'omada_user': 'op', 'omada_password': 'wrong'}, follow_redirects=True)
assert 'could not log in' in r.text
r = c.post(f'/sites/{SID}/omada', data={'csrf_token': tok(p), 'omada_url': CTL_URL, 'omada_user': 'op', 'omada_password': 'op-pass'}, follow_redirects=True)
assert 'Connected to the Omada Controller' in r.text, r.text[-3000:]
with app.app_context():
    s = db.session.get(Site, SID); TOKEN = s.portal_token
    assert s.omada_ready and s.omada_password_enc != 'op-pass' and s.omada_error is None and s.omada_url == CTL_URL
assert f'/omada/{TOKEN}' in r.text and 'External Portal Server' in r.text
# password kept when left empty
c.post(f'/sites/{SID}/omada', data={'csrf_token': tok(p), 'omada_url': CTL_URL, 'omada_user': 'op', 'omada_password': ''})
with app.app_context(): assert db.session.get(Site, SID).omada_ready

# --- guest arrives from the controller
g = app.test_client()
assert g.get('/omada/nope').status_code == 404
q = f'/omada/{TOKEN}?clientMac=AA-BB-CC-00-00-01&apMac=11-22-33-44-55-66&ssidName=Kili+Guest&radioId=1&site=omadaSite1&redirectUrl=http%3A%2F%2Fexample.com%2F&t=123'
page = g.get(q).text
assert 'Hotel Kilimanjaro' in page and '1 Day' in page and f'action="/omada/{TOKEN}/buy"' in page and f'action="/omada/{TOKEN}/login"' in page
# a direct visit without controller details can't log in
x = app.test_client(); x.get(f'/omada/{TOKEN}')
assert 'connect to the Wi-Fi again' in x.post(f'/omada/{TOKEN}/login', data={'code': '1', 'agree': '1'}).text

# wrong code, then a real voucher
with app.app_context():
    db.session.add_all([Voucher(tenant_id=TID, code='77778888', validity_minutes=120, batch='x', status='unused'),
                        RadCheck(username='77778888', attribute='Cleartext-Password', op=':=', value='77778888')]); db.session.commit()
assert "isn't valid" in html.unescape(g.post(f'/omada/{TOKEN}/login', data={'code': '11112222', 'agree': '1'}).text)
assert 'accept the terms' in g.post(f'/omada/{TOKEN}/login', data={'code': '77778888'}).text
before = len(ctl['authorized'])
r = g.post(f'/omada/{TOKEN}/login', data={'code': '7777 8888', 'agree': '1'}).text
assert "You're online" in r and 'example.com' in r and '/logout' not in r, r[-1500:]
a = ctl['authorized'][-1]
assert len(ctl['authorized']) == before + 1 and a['clientMac'] == 'AA-BB-CC-00-00-01' and a['site'] == 'omadaSite1' \
    and a['apMac'] == '11-22-33-44-55-66' and a['ssidName'] == 'Kili Guest' and a['radioId'] == '1' and a['time'] == str(120 * 60 * 1_000_000)
with app.app_context():
    v = Voucher.query.filter_by(code='77778888').one(); assert v.status == 'active' and v.first_mac == 'aa:bb:cc:00:00:01'
    row = RadAcct.query.filter_by(username='77778888').one(); assert row.calledstationid == f'omada-{SID}'
# the session shows on the dashboard for this site
d = c.get('/dashboard').text
assert '77778888' in d
# another phone can't use the same code while the first is online
g2 = app.test_client(); g2.get(q.replace('00-00-01', '00-00-02'))
assert 'another device' in g2.post(f'/omada/{TOKEN}/login', data={'code': '77778888', 'agree': '1'}).text

# --- buying with mobile money
b = app.test_client(); b.get(q.replace('00-00-01', '00-00-03'))
with app.app_context(): pkg = Package.query.filter_by(tenant_id=TID).one().id
assert 'Choose your mobile-money network' in b.post(f'/omada/{TOKEN}/buy', data={'package_id': pkg, 'phone': '0684000111', 'agree': '1'}).text
r = b.post(f'/omada/{TOKEN}/buy', data={'package_id': pkg, 'phone': '684000111', 'network': 'airtel', 'agree': '1'})
assert r.status_code == 302 and f'/omada/{TOKEN}/buy/wait?ref=SN' in r.headers['Location'], (r.status_code, r.headers.get('Location'))
wait = r.headers['Location']
ref = wait.split('ref=')[1]
with app.app_context():
    pay = Payment.query.filter_by(reference=ref).one(); assert pay.site_id == SID and pay.client_mac == 'AA-BB-CC-00-00-03' and pay.phone == '255684000111'
w = b.get(wait).text
assert 'Check your phone' in w and f'/omada/{TOKEN}/buy/wait?ref={ref}' in w
assert app.test_client().get(wait).status_code == 302           # someone else's browser can't follow this payment
pay_state['status'] = 'SUCCESS'
with app.app_context():                          # ClickPesa is asked at most every 3 s
    Payment.query.filter_by(reference=ref).update({'checked_at': None}); db.session.commit()
w = b.get(wait).text
assert "You're online" in w and 'Payment received' in w, w[-1500:]
assert ctl['authorized'][-1]['clientMac'] == 'AA-BB-CC-00-00-03' and ctl['authorized'][-1]['time'] == str(1440 * 60 * 1_000_000)
with app.app_context():
    code = Payment.query.filter_by(reference=ref).one().voucher.code
assert code in w

# --- controller trouble: code is fine but the login fails clearly; error shown on the Sites page
ctl['up'] = False
with app.app_context():
    db.session.add_all([Voucher(tenant_id=TID, code='55554444', validity_minutes=60, batch='x', status='unused'),
                        RadCheck(username='55554444', attribute='Cleartext-Password', op=':=', value='55554444')]); db.session.commit()
e = app.test_client(); e.get(q.replace('00-00-01', '00-00-04'))
assert "didn't accept the login" in html.unescape(e.post(f'/omada/{TOKEN}/login', data={'code': '55554444', 'agree': '1'}).text)
with app.app_context():
    assert db.session.get(Site, SID).omada_error and Voucher.query.filter_by(code='55554444').one().status == 'unused'   # not used up
ctl['up'] = True

# --- too many wrong codes from one phone
f = app.test_client(); f.get(q.replace('00-00-01', '00-00-09'))
for i in range(6):
    f.post(f'/omada/{TOKEN}/login', data={'code': f'1000000{i}', 'agree': '1'})
assert 'Too many wrong attempts' in f.post(f'/omada/{TOKEN}/login', data={'code': '55554444', 'agree': '1'}).text

# --- remove Omada: the portal link stops working
c.post(f'/sites/{SID}/omada', data={'csrf_token': tok(p), 'action': 'remove'})
assert app.test_client().get(q).status_code == 404
# --- SafeNet's own (hosted) controller
config.Config.OMADA_HOSTED_URL, config.Config.OMADA_HOSTED_USER, config.Config.OMADA_HOSTED_PASSWORD = CTL_URL, 'op', 'op-pass'
config.Config.OMADA_HOSTED_HOST = 'radius.example.tz'
p = c.get('/sites').text
assert "Use SafeNet's controller" in p
r = c.post(f'/sites/{SID}/omada', data={'csrf_token': tok(p), 'action': 'hosted'}, follow_redirects=True)
assert 'now uses SafeNet' in html.unescape(r.text) and 'radius.example.tz' in r.text, r.text[-2000:]
with app.app_context():
    s = db.session.get(Site, SID); assert s.omada_hosted and s.omada_ready and not s.omada_url and s.portal_token
    TOKEN = s.portal_token
q2 = f'/omada/{TOKEN}?clientMac=AA-BB-CC-00-00-21&apMac=11-22-33-44-55-66&ssidName=Kili+Guest&radioId=0&site=hostedSite&redirectUrl=http%3A%2F%2Fexample.com%2F'
with app.app_context():
    db.session.add_all([Voucher(tenant_id=TID, code='12123434', validity_minutes=30, batch='x', status='unused'),
                        RadCheck(username='12123434', attribute='Cleartext-Password', op=':=', value='12123434')]); db.session.commit()
h = app.test_client(); h.get(q2)
assert "You're online" in h.post(f'/omada/{TOKEN}/login', data={'code': '12123434', 'agree': '1'}).text
assert ctl['authorized'][-1]['clientMac'] == 'AA-BB-CC-00-00-21' and ctl['authorized'][-1]['site'] == 'hostedSite'
# hosted controller removed from the server: login fails clearly, page does not offer it
config.Config.OMADA_HOSTED_URL = ''
assert "Use SafeNet's controller" not in c.get('/sites').text
h2 = app.test_client(); h2.get(q2.replace('00-21', '00-22'))
with app.app_context():
    db.session.add_all([Voucher(tenant_id=TID, code='56567878', validity_minutes=30, batch='x', status='unused'),
                        RadCheck(username='56567878', attribute='Cleartext-Password', op=':=', value='56567878')]); db.session.commit()
assert "didn't accept the login" in html.unescape(h2.post(f'/omada/{TOKEN}/login', data={'code': '56567878', 'agree': '1'}).text)
srv.shutdown()
print('OMADA OK')
