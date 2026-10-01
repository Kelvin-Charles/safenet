"""Captive portal preview shows what a guest really sees: per site, per equipment, with payments on or off."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
appmod.sms_is_configured = lambda: True            # SMS set up (sending itself is faked)
appmod.send_sms_async = lambda *a, **k: None
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Site, Package, Gateway, Nas
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1')
    MAIN = tenant_sites(TID)[0]
    mw = Site(tenant_id=TID, name='Mwenge', portal_token='tokmwenge', omada_hosted=True)
    rj = Site(tenant_id=TID, name='Kariakoo', portal_token='tokkariakoo', wifidog_enabled=True)
    db.session.add_all([a, mw, rj]); db.session.flush()
    db.session.add_all([Package(tenant_id=TID, name='Everywhere Day', price=Decimal(1000), validity_minutes=1440),
                        Package(tenant_id=TID, name='Mwenge Week', price=Decimal(5000), validity_minutes=10080, site_id=mw.id),
                        Gateway(tenant_id=TID, name='gw', key_prefix='sgw_z', key_hash=_hash_key('sgw_z')),
                        Nas(tenant_id=TID, nasname='10.8.0.9', shortname='mt', type='mikrotik', secret='s', site_id=rj.id)])
    db.session.commit()
    MAINID, MW, RJ = MAIN.id, mw.id, rj.id

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
s = html.unescape(c.get('/settings/portal').text)
# sites listed with the equipment each one has (first = default for the preview)
assert f'<option value="{MW}" data-equip="omada">Mwenge</option>' in s, s[s.find('pv-site'):s.find('pv-site') + 800]
assert f'<option value="{RJ}" data-equip="ruijie">Kariakoo</option>' in s
assert f'<option value="{MAINID}" data-equip="gateway">' in s                 # unassigned gateway = main site
assert 'For a friend' in s and 'TP-Link Omada' in s and 'MikroTik / other router' in s
assert "aren't set up" not in s                                             # platform payments ready
raw = c.get('/settings/portal').text
# the preview URL in the script must not be HTML-escaped (&amp; broke every refresh)
assert '"/portal?t=zulu' + chr(92) + 'u0026preview=1" + ' in raw and "'/portal?t=zulu&amp;" not in raw

pv = lambda **q: html.unescape(c.get('/portal?t=zulu&preview=1&' + '&'.join(f'{k}={v}' for k, v in q.items())).text)
# packages follow the site
b = pv(view='buy', site=MW, equip='omada')
assert 'Everywhere Day' in b and 'Mwenge Week' in b and 'Buy for a friend' in b
b = pv(view='buy', site=RJ, equip='ruijie')
assert 'Everywhere Day' in b and 'Mwenge Week' not in b
# "Connected": Omada/Ruijie have no Disconnect and no time bar; the gateway has both
o = pv(view='online', site=MW, equip='omada'); g = pv(view='online', site=MAINID, equip='gateway')
assert "You're online" in o and 'Disconnect' not in o and 'class="bar"' not in o
assert 'Disconnect' in g and 'class="bar"' in g
# MikroTik: voucher only, no buying, and its own status page after login
m = pv(view='buy', site=RJ, equip='mikrotik')
assert 'Enter your voucher' in m and 'Choose a package' not in m and 'name="package_id"' not in m
assert "router's own status page" in pv(view='online', equip='mikrotik')
# friend screen and logo preview hook
f = pv(view='gift', site=MW, equip='omada')
assert 'The code is on its way' in f and '0712 345 678' in f
assert "postMessage" not in f and "addEventListener('message'" in f
# a site id from another tenant is ignored
with app.app_context():
    other = Tenant(name='Other', slug='other', status='active'); db.session.add(other); db.session.flush()
    os_ = Site(tenant_id=other.id, name='Secret'); db.session.add(os_); db.session.flush()
    db.session.add(Package(tenant_id=other.id, name='Other Pkg', price=Decimal(1), validity_minutes=60, site_id=os_.id)); db.session.commit(); OS = os_.id
assert 'Other Pkg' not in pv(view='buy', site=OS)

# payments not ready: no Buy tab for guests, and the preview says so
with app.app_context():
    t = db.session.get(Tenant, TID); t.payment_mode = 'own'; t.own_provider = 'clickpesa'; db.session.commit()
s = html.unescape(c.get('/settings/portal').text)
assert "Mobile payments aren't set up" in s
b = pv(view='buy', site=MW, equip='omada')
assert 'Choose a package' not in b and 'Enter your voucher' in b
# every mobile-money network has its logo file (the M-Pesa one was missing)
from gateway import portal_ui
for key, info in portal_ui.NETWORKS.items():
    assert os.path.isfile(os.path.join('static', 'img', info['logo'])), (key, info['logo'])
print('PORTAL PREVIEW OK')

# --- click through like a guest (payments ready again): nothing is charged
with app.app_context():
    t = db.session.get(Tenant, TID); t.payment_mode = 'platform'; db.session.commit()
    from models import Payment, Voucher
    db.session.add(Voucher(tenant_id=TID, code='11112222', validity_minutes=120, batch='x', status='unused')); db.session.commit()
    WEEK = Package.query.filter_by(name='Mwenge Week').one().id
base = f'/portal?t=zulu&preview=1&site={MW}&equip=omada&color=%23B91C1C'
b = html.unescape(c.get(base + '&view=buy').text)
assert 'type="submit" id="paybtn"' in b and f'action="/portal?t=zulu&preview=1&site={MW}&equip=omada&color=%23B91C1C&view=sim-buy"' in b, b[b.find('<form'):b.find('<form') + 400]
post = lambda view, **d: html.unescape(c.post(base + f'&view={view}', data=d).text)
# same checks as the real page
assert 'accept the terms' in post('sim-buy', package_id=WEEK, network='airtel', phone='684000111')
assert 'Choose your mobile-money network' in post('sim-buy', package_id=WEEK, phone='684000111', agree='1')
assert 'valid mobile number' in post('sim-buy', package_id=WEEK, network='airtel', phone='12', agree='1')
assert "That is a M-Pesa number, and M-Pesa isn't available yet. Use an Airtel Money number." in post('sim-buy', package_id=WEEK, network='airtel', phone='0754000111', agree='1')
assert "friend's mobile number" in post('sim-buy', package_id=WEEK, network='airtel', phone='684000111', agree='1', gift='1', gift_phone='1')
# pay -> "check your phone" -> (auto refresh) connected with the package's time
w = post('sim-buy', package_id=WEEK, network='airtel', phone='684000111', agree='1')
assert 'Check your phone' in w and 'TZS 5,000' in w and '--brand:#B91C1C' in w
nxt = re.search(r'http-equiv="refresh" content="3;url=([^"]+)"', w).group(1)
assert 'view=sim-paid' in nxt and f'pkg={WEEK}' in nxt
done = html.unescape(c.get(nxt).text)
assert "You're online" in done and 'Payment received' in done and ('7d' in done or '7 days' in done), done[-1500:]
assert 'Disconnect' not in done                                            # Omada: no disconnect button
# buying for a friend ends on the friend screen
w = post('sim-buy', package_id=WEEK, network='airtel', phone='684000111', agree='1', gift='1', gift_phone='0712345678')
nxt = re.search(r'http-equiv="refresh" content="3;url=([^"]+)"', w).group(1)
assert 'send the code to 0712 345 678' in w and 'The code is on its way' in html.unescape(c.get(nxt).text)
# voucher: real codes are checked for the owner, but not used up
assert 'Enter your voucher code' in post('sim-login', agree='1')
assert "isn't valid" in post('sim-login', code='99998888', agree='1')
v = post('sim-login', code='1111 2222', agree='1')
assert "You're online" in v and '11112222' in v and ('2 hours' in v or '2h' in v)
# MikroTik: the router's login form also works in the preview
m = html.unescape(c.get(f'/portal?t=zulu&preview=1&site={RJ}&equip=mikrotik&view=voucher').text)
assert 'view=sim-login' in m
assert "router's own status page" in html.unescape(c.post(f'/portal?t=zulu&preview=1&site={RJ}&equip=mikrotik&view=sim-login',
                                                          data={'username': '11112222', 'password': '11112222', 'agree': '1'}).text)
with app.app_context():
    assert Payment.query.count() == 0 and Voucher.query.filter_by(code='11112222').one().status == 'unused'
# the language switch stays in the preview
assert f'site={MW}' in re.search(r'class="lang" href="([^"]+)"', b).group(1)
# anyone else only gets the example, never a real code's details; and real (non-preview) posts are refused
anon = app.test_client()
assert "You're online" in html.unescape(anon.post(base + '&view=sim-login', data={'code': '99998888', 'agree': '1'}).text)
assert anon.post('/portal?t=zulu', data={'code': '1'}).status_code == 405
print('PORTAL SIMULATION OK')
