"""Captive portal preview shows what a guest really sees: per site, per equipment, with payments on or off."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
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
