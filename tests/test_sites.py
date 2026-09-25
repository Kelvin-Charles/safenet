import os, re, sys, time
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS'}
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Gateway, Package, Payment, Voucher, RadAcct, Site, BillingPlan, RadUser
app.config.update(TESTING=True)
now = datetime.utcnow
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all()
    t = Tenant(name='Mama Net', slug='mama', status='trial', trial_ends_at=now() + timedelta(days=5)); db.session.add(t); db.session.flush()
    db.session.add(Gateway(tenant_id=t.id, name='gw-main', key_prefix='sgw_m', key_hash=_hash_key('sgw_main'), last_seen_at=now()))
    db.session.commit(); TID = t.id
    migrations.run(); migrations.run()                                     # idempotent
    sites = Site.query.filter_by(tenant_id=TID).all()
    assert [s.name for s in sites] == ['Main site'] and Gateway.query.one().site_id == sites[0].id
    MAIN = sites[0].id
    starter = BillingPlan.query.filter_by(name='Starter').one()
    assert starter.max_sites == 1 and starter.max_gateways is None
    biz = BillingPlan.query.filter_by(name='Business').one(); t = db.session.get(Tenant, TID); t.billing_plan_id = biz.id
    a = Admin(username='mama', email='m@x.tz', tenant_id=TID, role='owner', email_verified_at=now()); a.set_password('password1')
    db.session.add_all([a, Package(tenant_id=TID, name='Everywhere', price=Decimal(1000), validity_minutes=60)]); db.session.commit()

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'mama', 'password': 'password1', 'csrf_token': tok(r.text)})
d = c.get('/dashboard'); assert d.status_code == 200, d.text[-2000:]
assert 'Good ' in d.text and 'Mama Net' in d.text and 'Free trial: 5 days left' in d.text and 'gw-main' in d.text

# Add a second site: it becomes the selected one, new gateway goes there
p = c.get('/sites').text
c.post('/sites/add', data={'csrf_token': tok(p), 'name': 'Mwenge shop', 'location': 'Mwenge'})
with app.app_context(): MW = Site.query.filter_by(name='Mwenge shop').one().id
g = c.get('/gateways').text
assert 'Mwenge shop' in g
c.post('/gateways/add', data={'csrf_token': tok(g), 'name': 'gw-mwenge'})
with app.app_context():
    gw2 = Gateway.query.filter_by(name='gw-mwenge').one(); assert gw2.site_id == MW
    gw2.key_hash = _hash_key('sgw_mwenge'); gw2.last_seen_at = now(); GW2 = gw2.id
    db.session.add(Package(tenant_id=TID, name='Mwenge only', price=Decimal(500), validity_minutes=30, site_id=MW))
    db.session.add(Package(tenant_id=TID, name='Main only', price=Decimal(700), validity_minutes=30, site_id=MAIN))
    db.session.commit()

# Each gateway's portal sells its own site's packages plus the all-sites ones
api = app.test_client()
names = lambda key: sorted(x['name'] for x in api.get('/api/portal/packages', headers={'X-SafeNet-Key': key}).get_json()['packages'])
assert names('sgw_main') == ['Everywhere', 'Main only'] and names('sgw_mwenge') == ['Everywhere', 'Mwenge only']
with app.app_context(): main_only = Package.query.filter_by(name='Main only').one().id; mw_only = Package.query.filter_by(name='Mwenge only').one().id
assert api.post('/api/portal/purchase', headers={'X-SafeNet-Key': 'sgw_mwenge'}, json={'package_id': main_only, 'phone': '0684000111', 'network': 'airtel'}).status_code == 404

# A sale at Mwenge is recorded there, and so is its voucher
ref = api.post('/api/portal/purchase', headers={'X-SafeNet-Key': 'sgw_mwenge'}, json={'package_id': mw_only, 'phone': '0684000111', 'network': 'airtel'}).get_json()['reference']
code = api.get(f'/api/portal/purchase/{ref}', headers={'X-SafeNet-Key': 'sgw_mwenge'}).get_json()['code']
with app.app_context():
    pay = Payment.query.filter_by(reference=ref).one(); assert pay.site_id == MW and pay.voucher.site_id == MW
# Session at the Mwenge gateway
api.post('/api/gateway/auth', headers={'X-SafeNet-Key': 'sgw_mwenge'}, json={'username': code, 'password': code, 'mac': 'aa:00:00:00:00:01'})
api.post('/api/gateway/accounting', headers={'X-SafeNet-Key': 'sgw_mwenge'}, json={'events': [{'type': 'interim', 'session_id': 's1', 'username': code, 'mac': 'aa:00:00:00:00:01', 'ip': '10.10.0.5', 'input_octets': 2000000, 'output_octets': 30000000, 'session_time': 60, 'time': int(time.time())}]})

# Mwenge selected: dashboard shows its sale and session; Main site: neither
d = c.get('/dashboard').text
assert 'TZS 500' in d and code in d and 'gw-mwenge' in d and 'gw-main' not in d, d[d.find('Financial'):][:600]
s = c.get('/sites').text
c.post('/sites/switch', data={'csrf_token': tok(s), 'site_id': MAIN})
d = c.get('/dashboard').text
assert code not in d and 'gw-main' in d and 'gw-mwenge' not in d
c.post('/sites/switch', data={'csrf_token': tok(s), 'site_id': ''})             # all sites
d = c.get('/dashboard').text
assert code in d and 'gw-main' in d and 'gw-mwenge' in d and 'This month by site' in d and 'Mwenge shop' in d

# Move a package to all sites, and the gateway to Main
pk = c.get('/packages').text
c.post('/sites/assign', data={'csrf_token': tok(pk), 'kind': 'package', 'id': mw_only, 'site_id': ''})
with app.app_context(): assert db.session.get(Package, mw_only).site_id is None
c.post('/sites/assign', data={'csrf_token': tok(pk), 'kind': 'gateway', 'id': GW2, 'site_id': MAIN})
with app.app_context(): assert db.session.get(Gateway, GW2).site_id == MAIN
# Another tenant's site can't be used
with app.app_context():
    other = Tenant(name='O', slug='o', status='active'); db.session.add(other); db.session.flush()
    os_ = Site(tenant_id=other.id, name='theirs'); db.session.add(os_); db.session.commit(); OS = os_.id
assert c.post('/sites/assign', data={'csrf_token': tok(pk), 'kind': 'gateway', 'id': GW2, 'site_id': OS}).status_code == 404

# Delete Mwenge: its sale moves to Main
c.post(f'/sites/{MW}/delete', data={'csrf_token': tok(pk)})
with app.app_context():
    assert not db.session.get(Site, MW) and Payment.query.filter_by(reference=ref).one().site_id == MAIN
# Can't delete the last site
assert 'at least one site' in c.post(f'/sites/{MAIN}/delete', data={'csrf_token': tok(pk)}, follow_redirects=True).text

# Plan limit: Starter allows 1 site
with app.app_context():
    t = db.session.get(Tenant, TID); t.billing_plan_id = BillingPlan.query.filter_by(name='Starter').one().id; db.session.commit()
r = c.post('/sites/add', data={'csrf_token': tok(pk), 'name': 'Third'}, follow_redirects=True).text
assert 'does not allow more sites' in r
assert 'Your plan allows 1 site' in c.get('/sites').text
# Mobile menu + site switcher exist
assert 'menu-btn' in d and 'Manage sites' in d
print('SITES OK')
