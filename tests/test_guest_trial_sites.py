"""'Try free' at the sites the business chose, end to end on Omada (controller lets the phone in), Ruijie RG-AP
(WiFiDog: back to the access point with a token) and the gateway box's site."""
import html, os, re, sys
from datetime import datetime
from urllib.parse import urlencode
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PUBLIC_URL='https://radius.example.tz', WIFIDOG_BASE='http://radius.example.tz:5001')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
let_in = []


class FakeController:
    def authorize(self, mac, seconds, **kw):
        let_in.append((mac, seconds))


appmod._omada_controller = lambda site: FakeController()
from app import app, db
import migrations, secretbox
from models import Admin, Tenant, Site, Voucher, Gateway
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1')
    db.session.add(a)
    main = tenant_sites(TID)[0]
    main.portal_token, main.omada_url, main.omada_user, main.omada_password_enc = 'omtok', 'https://10.0.0.2:8043', 'op', secretbox.encrypt('pw')
    rg = Site(tenant_id=TID, name='Hostel B', portal_token='wdtok', wifidog_enabled=True); db.session.add(rg)
    db.session.add(Gateway(tenant_id=TID, name='Box', key_prefix='k', key_hash=appmod._hash_key('gwkey')))     # no site: the main site
    db.session.commit()
    MAIN, RG = main.id, rg.id

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = html.unescape(c.get('/settings/portal').text)
assert 'At these sites' in p and 'Hostel B' in p
c.post('/settings/free-trial', data={'csrf_token': tok(p), 'minutes': 30, 'who': 'all', 'every': 'once', 'sites': [MAIN, RG]})
with app.app_context():
    assert not db.session.get(Site, MAIN).guest_trial_off and not db.session.get(Site, RG).guest_trial_off

# Omada: the controller lets the phone in for the trial time
g = app.test_client()
g.get('/omada/omtok?clientMac=AA-BB-CC-00-00-01&apMac=11-22-33-44-55-66&ssidName=Guest&radioId=1&site=s1&redirectUrl=http%3A%2F%2Fexample.com%2F')
page = html.unescape(g.get('/omada/omtok').text)
assert 'action="/omada/omtok/trial"' in page and 'Try free for' in page
r = html.unescape(g.post('/omada/omtok/trial').text)
assert let_in == [('AA-BB-CC-00-00-01', 1800)], let_in
with app.app_context():
    v = Voucher.query.filter_by(is_free=True, site_id=MAIN).one()
    assert v.first_mac == 'aa:bb:cc:00:00:01' and v.status == 'active'
assert 'already had a free trial' in html.unescape(g.post('/omada/omtok/trial').text) and len(let_in) == 1

# Ruijie RG-AP (WiFiDog): back to the access point with its login token
w = app.test_client()
q = dict(gw_address='192.168.110.1', gw_port='2060', gw_id='RG', mac='aa:bb:cc:00:00:02', ip='192.168.110.23', url='http://example.com/')
w.get('/wifidog/wdtok/login/?' + urlencode(q), base_url='https://radius.example.tz')
page = html.unescape(w.get('/wifidog/wdtok/guest', base_url='https://radius.example.tz').text)
assert 'action="/wifidog/wdtok/guest/trial"' in page
r = w.post('/wifidog/wdtok/guest/trial', base_url='https://radius.example.tz')
assert r.status_code == 302 and r.headers['Location'].startswith('http://192.168.110.1:2060/wifidog/auth?token='), r.headers.get('Location')
with app.app_context():
    assert Voucher.query.filter_by(is_free=True, site_id=RG).one().first_mac == 'aa:bb:cc:00:00:02'

# switched off at one site: no button there and the route refuses; the other site keeps it
c.post('/settings/free-trial', data={'csrf_token': tok(p), 'minutes': 30, 'who': 'all', 'every': 'once', 'sites': [MAIN]})
w2 = app.test_client()
w2.get('/wifidog/wdtok/login/?' + urlencode({**q, 'mac': 'aa:bb:cc:00:00:03'}), base_url='https://radius.example.tz')
assert 'action="/wifidog/wdtok/guest/trial"' not in w2.get('/wifidog/wdtok/guest', base_url='https://radius.example.tz').text
assert "isn't available" in html.unescape(w2.post('/wifidog/wdtok/guest/trial', base_url='https://radius.example.tz').text)
g2 = app.test_client()
g2.get('/omada/omtok?clientMac=AA-BB-CC-00-00-04&site=s1&redirectUrl=http%3A%2F%2Fexample.com%2F')
assert 'action="/omada/omtok/trial"' in g2.get('/omada/omtok').text

# the gateway box (no site set: the main site) follows the main site's choice
api = app.test_client()
assert api.get('/api/gateway/config', headers={'X-SafeNet-Key': 'gwkey'}).get_json()['trial']['minutes'] == 30
c.post('/settings/free-trial', data={'csrf_token': tok(p), 'minutes': 30, 'who': 'all', 'every': 'once', 'sites': [RG]})
assert api.get('/api/gateway/config', headers={'X-SafeNet-Key': 'gwkey'}).get_json()['trial'] is None
assert api.post('/api/portal/trial', json={'mac': 'AA:BB:CC:00:00:09'}, headers={'X-SafeNet-Key': 'gwkey'}).status_code == 403
# Reyee zip for a site without it: Ruijie's one-click login stays off there
with app.app_context():
    assert appmod._ruijie_load_config(db.session.get(Tenant, TID), db.session.get(Site, MAIN))['custom_html']['login_options'] == ['voucher']
    assert 'pass' in appmod._ruijie_load_config(db.session.get(Tenant, TID), db.session.get(Site, RG))['custom_html']['login_options']
print('GUEST TRIAL SITES OK')
