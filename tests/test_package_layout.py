"""Captive portal: the business picks how packages are shown (list, the default, or a grid of tiles) and every page follows."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Site, Package, Gateway
from tenancy import tenant_sites
from gateway import portal_ui
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Swaibah', slug='swaibah', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1')
    rj = Site(tenant_id=TID, name='Kariakoo', portal_token='tokkariakoo', wifidog_enabled=True)
    db.session.add_all([a, rj, Gateway(tenant_id=TID, name='gw', key_prefix='sgw_s', key_hash=_hash_key('sgw_s'))])
    for i, (n, m, p) in enumerate((('Silver', 1440, 1000), ('Gold', 10080, 5000), ('Diamond', 43200, 18000))):
        db.session.add(Package(tenant_id=TID, name=n, price=Decimal(p), validity_minutes=m, sort_order=i))
    db.session.commit(); MAIN, RJ = tenant_sites(TID)[0].id, rj.id
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
grid = lambda h: '<div class="pkgs grid">' in h
listed = lambda h: '<div class="pkgs">' in h
pv = lambda **q: html.unescape(c.get('/portal', query_string={'t': 'swaibah', 'preview': 1, 'view': 'buy', 'site': MAIN, 'equip': 'gateway', **q}).text)

# list by default; the setting is on the page; the preview tries grid before saving
s = html.unescape(c.get('/settings/portal').text)
assert 'How packages are shown' in s and 'Grid: tiles side by side' in s and 'package_layout' in s
assert listed(pv()) and grid(pv(package_layout='grid'))
cfg = lambda: c.application.test_client().get('/api/gateway/config', headers={'X-SafeNet-Key': 'sgw_s'}).get_json()['portal']
assert cfg()['package_layout'] == 'list'

# saved as grid: preview, the gateway box's config, Ruijie pages and SafeNet's own pages all use it
form = {'csrf_token': tok(s), 'color': '#051D60', 'style': 'gradient', 'language': 'en', 'show_voucher': 'y', 'show_packages': 'y', 'package_layout': 'grid'}
assert 'Captive portal saved' in c.post('/settings/portal', data=form, follow_redirects=True).text
assert grid(pv()) and cfg()['package_layout'] == 'grid'
with app.test_request_context('/'):
    tenant = db.session.get(Tenant, TID)
    th = portal_ui.theme(appmod.portal_config(tenant))
    assert th['package_layout'] == 'grid'
    assert 'pkgs grid' in str(appmod._ruijie_portal_pages(db.session.get(Site, RJ), tenant, th))
    assert grid(appmod._hotspot_page(db.session.get(Site, RJ), tenant, '/x').get_data(as_text=True))
# the gateway box draws it the same way from that config; anything else falls back to the list
assert grid(portal_ui.login_page(portal_ui.theme({'package_layout': 'grid'}), 'en', packages=[{'id': 1, 'name': 'Silver', 'price': '1000', 'validity_minutes': 1440}]))
assert portal_ui.theme({'package_layout': 'weird'})['package_layout'] == 'list' and portal_ui.theme({})['package_layout'] == 'list'
# back to the list
form['package_layout'] = 'list'; c.post('/settings/portal', data=form)
assert listed(pv())
form['package_layout'] = 'tiles'
assert 'Not a valid choice' in c.post('/settings/portal', data=form).text
print('ok')
