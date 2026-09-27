"""Tenants set up Omada access points from SafeNet alone: a fake controller speaking the Omada Open API."""
import html, json, os, re, sys, threading
from datetime import datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PUBLIC_URL='https://radius.example.tz', OMADA_HOSTED_HOST='radius.example.tz')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations, omada, app as appmod
from models import Admin, Tenant, Site, Package, Voucher, RadCheck, RadAcct
from tenancy import tenant_sites
app.config.update(TESTING=True)
appmod.time.sleep = lambda s: None                     # don't wait while polling the adopt result
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)

CID = 'cid123'
st = {'sites': {'S0': {'siteId': 'S0', 'name': 'SafeNet Main'}}, 'ssids': {}, 'portals': {}, 'acl': {},
      'pending': {'B8-FB-B3-79-C7-E6': {'mac': 'B8-FB-B3-79-C7-E6', 'model': 'EAP225-Outdoor(EU) v3.0'},
                  'AA-AA-AA-AA-AA-01': {'mac': 'AA-AA-AA-AA-AA-01', 'model': 'EAP225 v5.0'}},
      'devices': {}, 'operator': {'id': 'OP1', 'name': 'safenet-portal', 'sites': ['S0'], 'operatorRoleType': 0},   # the real list reports no sites
      'calls': [], 'unauth': [], 'tokens': 0, 'needs_login': {'AA-AA-AA-AA-AA-01'}}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, obj, code=0, msg='Success.'):
        body = json.dumps({'errorCode': code, 'msg': msg, 'result': obj}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n) or b'{}') if n else {}
    def authed(self):
        return self.headers.get('Authorization') == 'AccessToken=AT-1'
    def route(self, method):
        u = urlparse(self.path); path, q = u.path, parse_qs(u.query)
        if path == '/api/info':
            return self.out({'omadacId': CID})
        if path == '/openapi/authorize/token':
            b = self.body(); st['tokens'] += 1
            ok = q.get('grant_type') == ['client_credentials'] and b == {'omadacId': CID, 'client_id': 'ci', 'client_secret': 'cs'}
            return self.out({'accessToken': 'AT-1', 'expiresIn': 7200} if ok else {}, 0 if ok else -44111, 'bad client')
        if not self.authed():
            return self.out(None, -44112, 'token invalid')
        p = path.replace(f'/openapi/v1/{CID}', '').replace(f'/openapi/v2/{CID}', '')
        b = self.body() if method in ('POST', 'PATCH') else {}
        st['calls'].append((method, p, b))
        m = re.match(r'/sites/([^/]+)(/.*)?$', p)
        if p == '/scenarios': return self.out(['Office', 'Hotel', 'Restaurant'])
        if p == '/sites' and method == 'GET':
            key = (q.get('searchKey') or [''])[0]
            return self.out({'data': [s for s in st['sites'].values() if key in s['name']]})
        if p == '/sites' and method == 'POST':
            sid = f"S{len(st['sites'])}"; st['sites'][sid] = {'siteId': sid, **b}
            pw = b['deviceAccountSetting']['password']
            assert b['region'] and b['timeZone'] and b['scenario'] == 'Hotel' and 10 <= len(pw) <= 64, b
            assert re.search('[A-Z]', pw) and re.search('[a-z]', pw) and re.search('[0-9]', pw) and re.search('[#@%&*]', pw), pw
            assert not re.search(r'(.)\1', pw), pw
            return self.out({})
        sid, rest = m.group(1), (m.group(2) or '')
        if rest == '/devices': return self.out({'data': [d for d in st['devices'].values() if d['site'] == sid]})
        if rest == '/grid/devices/pending': return self.out({'data': list(st['pending'].values())})
        am = re.match(r'/devices/([^/]+)/(start-adopt|adopt-result)$', rest)
        if am:
            mac = am.group(1)
            if am.group(2) == 'start-adopt':
                if mac in st['needs_login'] and b != {'username': 'brighton', 'password': 'pw12345'}:
                    st['adopt'] = (mac, 'fail'); return self.out(None)
                st['adopt'] = (mac, 'ok'); dev = st['pending'].pop(mac)
                st['devices'][mac] = {**dev, 'site': sid, 'status': 1, 'detailStatus': 14, 'name': mac, 'ip': '192.168.100.33'}
                return self.out(None)
            ok = st.get('adopt') == (mac, 'ok')
            return self.out({'deviceMac': mac, 'adoptErrorCode': 0 if ok else -39003, 'adoptFailedType': -1 if ok else -2})
        if rest == '/wireless-network/wlans': return self.out([{'wlanId': f'W-{sid}', 'name': 'Default', 'primary': True}])
        if rest == '/wireless-network/ssids':
            assert q.get('type') == ['1'], q
            return self.out([{'wlanId': f'W-{sid}', 'ssidList': [{'ssidId': k, 'ssidName': v['name']} for k, v in st['ssids'].items() if v['site'] == sid]}])
        if re.match(r'/wireless-network/wlans/[^/]+/ssids$', rest) and method == 'POST':
            assert b == {'name': b['name'], 'deviceType': 1, 'band': 3, 'guestNetEnable': True, 'security': 0, 'broadcast': True}, b
            st['ssids'][f"SS{len(st['ssids'])}"] = {**b, 'site': sid}; return self.out({})
        if rest == '/portals': return self.out([{'id': k, **v} for k, v in st['portals'].items() if v['site'] == sid])
        if rest == '/portal' and method == 'POST':
            assert set(b['portalCustomize']) >= {'copyrightEnable', 'defaultLanguage', 'logoDisplay', 'termsOfServiceEnable', 'welcomeEnable'}, b
            st['portals'][f"P{len(st['portals'])}"] = {**b, 'site': sid}; return self.out({})
        pm = re.match(r'/portal/([^/]+)$', rest)
        if pm and method == 'PATCH':
            st['portals'][pm.group(1)].update(b); return self.out({})
        if rest == '/setting/access-control':
            if method == 'GET': return self.out(st['acl'].get(sid, {'preAuthAccessEnable': False, 'preAuthAccessPolicies': [], 'freeAuthClientEnable': False}))
            st['acl'][sid] = b; return self.out({})
        if rest == '/hotspot/operators': return self.out({'data': [{**st['operator'], 'sites': None}]})
        if rest == '/hotspot/operators/OP1' and method == 'PATCH':
            assert b['password'] == 'op-pass', b
            st['operator']['sites'] = b['selectedSites']; return self.out({})
        um = re.match(r'/hotspot/clients/([^/]+)/unauth$', rest)
        if um: st['unauth'].append((sid, um.group(1))); return self.out(None)
        return self.out(None, -1, f'not faked: {method} {p}')
    def do_GET(self): self.route('GET')
    def do_POST(self): self.route('POST')
    def do_PATCH(self): self.route('PATCH')
srv = ThreadingHTTPServer(('127.0.0.1', 0), Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f'http://127.0.0.1:{srv.server_address[1]}'

now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add(o); db.session.commit(); TID = t.id; SID = tenant_sites(TID)[0].id
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})

# not configured on this server: no button, page redirects
assert 'Set up Wi-Fi access points' not in c.get('/sites').text
assert c.get(f'/sites/{SID}/wifi').status_code == 302
config.Config.OMADA_HOSTED_URL, config.Config.OMADA_HOSTED_USER, config.Config.OMADA_HOSTED_PASSWORD = URL, 'safenet-portal', 'op-pass'
config.Config.OMADA_OPENAPI_CLIENT_ID, config.Config.OMADA_OPENAPI_CLIENT_SECRET = 'ci', 'cs'
p = c.get('/sites').text
assert 'Set up Wi-Fi access points' in p
w = c.get(f'/sites/{SID}/wifi').text
assert 'Create my Wi-Fi' in w and 'radius.example.tz' in w and 'No access points yet' in w

# step 1: one form creates the controller site, Wi-Fi, portal, pre-login access and operator access
r = c.post(f'/sites/{SID}/wifi/setup', data={'csrf_token': tok(w), 'wifi_name': 'Zulu Connect WiFi'}, follow_redirects=True).text
assert 'is ready' in r, r[-2000:]
with app.app_context():
    s = db.session.get(Site, SID); OSID, TOKEN = s.omada_site_id, s.portal_token
    assert s.omada_hosted and s.omada_ssid == 'Zulu Connect WiFi' and OSID and s.omada_device_password_enc and s.omada_ready
assert st['sites'][OSID]['name'] == 'Zulu Connect'
portal = [v for v in st['portals'].values() if v['site'] == OSID][0]
assert portal['authType'] == 4 and portal['externalPortal'] == {'hostType': 2, 'serverUrlScheme': 'https', 'serverUrl': f'radius.example.tz/omada/{TOKEN}'} and portal['enable']
assert st['acl'][OSID]['preAuthAccessEnable'] and {'type': 2, 'url': 'radius.example.tz'} in st['acl'][OSID]['preAuthAccessPolicies']
assert set(st['operator']['sites']) == set(st['sites'])            # every site, the old ones kept
# running it again (e.g. renaming) doesn't duplicate anything
n_sites, n_portals = len(st['sites']), len(st['portals'])
c.post(f'/sites/{SID}/wifi/setup', data={'csrf_token': tok(w), 'wifi_name': 'Zulu Connect WiFi'})
assert len(st['sites']) == n_sites and len(st['portals']) == n_portals and len([x for x in st['ssids'].values() if x['site'] == OSID]) == 1

# step 3: add the access point by MAC (any format)
w = c.get(f'/sites/{SID}/wifi').text
r = c.post(f'/sites/{SID}/wifi/adopt', data={'csrf_token': tok(w), 'mac': 'b8:fb:b3:79:c7:e6'}, follow_redirects=True).text
assert 'is being added' in r, r[-2000:]
assert 'B8-FB-B3-79-C7-E6' in r and 'Online' in r and 'EAP225-Outdoor' in r
# an access point with its own login asks for it
r = c.post(f'/sites/{SID}/wifi/adopt', data={'csrf_token': tok(w), 'mac': 'AA-AA-AA-AA-AA-01'}, follow_redirects=True).text
assert 'needs its own login' in r
r = c.post(f'/sites/{SID}/wifi/adopt', data={'csrf_token': tok(w), 'mac': 'AA-AA-AA-AA-AA-01', 'username': 'brighton', 'password': 'pw12345'}, follow_redirects=True).text
assert 'is being added' in r
# unknown or mistyped MACs are explained
assert "can't see CC-CC-CC-CC-CC-CC yet" in html.unescape(c.post(f'/sites/{SID}/wifi/adopt', data={'csrf_token': tok(w), 'mac': 'cc-cc-cc-cc-cc-cc'}, follow_redirects=True).text)
assert 'MAC address from the label' in c.post(f'/sites/{SID}/wifi/adopt', data={'csrf_token': tok(w), 'mac': 'nonsense'}, follow_redirects=True).text
assert 'already one of your access points' in c.post(f'/sites/{SID}/wifi/adopt', data={'csrf_token': tok(w), 'mac': 'B8FBB379C7E6'}, follow_redirects=True).text
# the pending list (which includes other tenants' devices) is never shown
assert 'AA-AA-AA-AA-AA-01' in c.get(f'/sites/{SID}/wifi').text      # now adopted, so it is ours
st['pending']['DD-DD-DD-DD-DD-99'] = {'mac': 'DD-DD-DD-DD-DD-99', 'model': 'EAP610'}
assert 'DD-DD-DD-DD-DD-99' not in c.get(f'/sites/{SID}/wifi').text

# a portal set up by hand on the Wi-Fi is reused, not doubled
with app.app_context(): ssid_id = next(k for k, v in st['ssids'].items() if v['site'] == OSID)
for k in [k for k, v in st['portals'].items() if v['site'] == OSID]: del st['portals'][k]
st['portals']['PH'] = {'name': 'Zulu Connect Kitonga', 'authType': 4, 'ssidList': [ssid_id], 'site': OSID}
c.post(f'/sites/{SID}/wifi/setup', data={'csrf_token': tok(w), 'wifi_name': 'Zulu Connect WiFi'})
mine = [v for v in st['portals'].values() if v['site'] == OSID]
assert len(mine) == 1 and mine[0]['name'] == 'Zulu Connect Kitonga' and mine[0]['externalPortal']['serverUrl'].endswith(f'/omada/{TOKEN}'), mine

# a second site of the same tenant gets its own controller site, named after both
p = c.get('/sites').text
c.post('/sites/add', data={'csrf_token': tok(p), 'name': 'Mwenge'})
with app.app_context(): SID2 = Site.query.filter_by(tenant_id=TID, name='Mwenge').one().id
c.post(f'/sites/{SID2}/wifi/setup', data={'csrf_token': tok(p), 'wifi_name': 'Zulu Mwenge'})
with app.app_context(): OSID2 = db.session.get(Site, SID2).omada_site_id
assert OSID2 != OSID and st['sites'][OSID2]['name'] == 'Zulu Connect - Mwenge' and OSID2 in st['operator']['sites']

# Disconnect on the Live page cuts an Omada guest off in the controller
with app.app_context():
    db.session.add_all([Voucher(tenant_id=TID, code='12344321', validity_minutes=60, batch='x', status='active', first_used_at=now, expires_at=now + timedelta(hours=1)),
                        RadCheck(username='12344321', attribute='Cleartext-Password', op=':=', value='12344321'),
                        RadAcct(acctsessionid='x1', acctuniqueid='x1', username='12344321', nasipaddress='1.2.3.4', groupname='', acctterminatecause='',
                                calledstationid=f'omada-{SID}', callingstationid='AA-BB-CC-00-00-07', acctstarttime=now, acctupdatetime=now,
                                acctsessiontime=0, acctinputoctets=0, acctoutputoctets=0)])
    db.session.commit()
lv = c.get('/live').text
c.post('/live/disconnect', data={'csrf_token': tok(lv), 'username': '12344321'})
import time as _t
deadline = _t.monotonic() + 5                          # (time.sleep is stubbed above, so wait on the clock)
while not st['unauth'] and _t.monotonic() < deadline:
    pass
assert st['unauth'] == [(OSID, 'AA-BB-CC-00-00-07')], st['unauth']
with app.app_context(): assert RadAcct.query.filter_by(acctuniqueid='x1').one().acctstoptime is not None

# the access token is reused, not fetched for every call
assert st['tokens'] <= 4, st['tokens']
srv.shutdown()
print('OMADA OPEN API OK')
