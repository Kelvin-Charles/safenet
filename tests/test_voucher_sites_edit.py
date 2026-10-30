"""Vouchers for some sites only (refused at the business's other sites, also when a phone comes back), and editing a
voucher's plan, validity, price, devices and sites, one at a time or many at once."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
from app import app, db
import migrations
from models import Admin, Tenant, Site, Plan, Voucher, RadUserGroup
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    sites = [Site(tenant_id=TID, name=n) for n in ('Hostel', 'Library', 'Cafe')]
    db.session.add_all(sites)
    db.session.add_all([Plan(tenant_id=TID, name='Slow', group_name='jriit-slow', is_active=True),
                        Plan(tenant_id=TID, name='Fast', group_name='jriit-fast', is_active=True)])
    db.session.commit()
    HOSTEL, LIBRARY, CAFE = (s.id for s in sites)
    SLOW, FAST = (p.id for p in Plan.query.filter_by(tenant_id=TID).order_by(Plan.id))

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
g = c.get('/vouchers/generate').text
assert 'All sites' in g and 'Library' in g
gen = lambda **d: c.post('/vouchers/generate', data={'csrf_token': tok(g), 'plan_id': SLOW, 'count': 3, 'validity_value': 1, 'validity_unit': 'days',
                                                      'price': '1000', 'max_devices': 1, 'sites_form': '1', **d}, follow_redirects=True)
assert 'Choose at least one site' in html.unescape(gen(batch='none').text)            # nothing ticked
gen(batch='hostel-lib', sites=[HOSTEL, LIBRARY])
gen(batch='everywhere', sites_all='1')
with app.app_context():
    v = Voucher.query.filter_by(batch='hostel-lib').first(); CODE = v.code
    assert {s.id for s in v.sites} == {HOSTEL, LIBRARY} and v.site_id == HOSTEL
    assert Voucher.query.filter_by(batch='everywhere').first().sites == []
    EVERY = Voucher.query.filter_by(batch='everywhere').first().code
    tenant, site = db.session.get(Tenant, TID), lambda i: db.session.get(Site, i)
    # logging in: refused at the Cafe, fine at the Library; an all-sites code works anywhere
    ok, msg, _ = appmod._gateway_authenticate(tenant, CODE, CODE, 'AA:BB:CC:00:00:01', site(CAFE))
    assert not ok and "doesn't work at this Wi-Fi" in msg
    ok, _, _ = appmod._gateway_authenticate(tenant, CODE, CODE, 'AA:BB:CC:00:00:01', site(LIBRARY))
    assert ok
    assert appmod._gateway_authenticate(tenant, EVERY, EVERY, 'AA:BB:CC:00:00:02', site(CAFE))[0]
    db.session.commit()
    # a phone coming back is let in again only where its code works
    assert appmod._returning_code(TID, 'AA:BB:CC:00:00:01', site(LIBRARY)) == CODE
    assert appmod._returning_code(TID, 'AA:BB:CC:00:00:01', site(CAFE)) is None
# the list shows where a code works; viewing one site shows the codes that work there
lst = html.unescape(c.get('/vouchers?batch=hostel-lib').text)
assert 'Hostel, Library' in lst

# edit one voucher: plan, validity (already in use: the end moves), price, devices, sites
with app.app_context():
    VID = Voucher.query.filter_by(code=CODE).one().id
e = html.unescape(c.get(f'/vouchers/edit?ids={VID}').text)
assert f'Edit voucher {CODE}' in e
r = html.unescape(c.post('/vouchers/edit', data={'csrf_token': tok(e), 'ids': VID, 'plan_id': FAST, 'validity_value': 3, 'validity_unit': 'days',
                                                 'price': '2500', 'max_devices': 2, 'sites_form': '1', 'sites': [CAFE]}, follow_redirects=True).text)
assert '1 vouchers updated' in r
with app.app_context():
    v = db.session.get(Voucher, VID)
    assert v.plan_id == FAST and RadUserGroup.query.filter_by(username=CODE).one().groupname == 'jriit-fast'
    assert v.validity_minutes == 3 * 1440 and v.expires_at == v.first_used_at + timedelta(days=3)
    assert v.price == 2500 and v.max_devices == 2 and [s.id for s in v.sites] == [CAFE] and v.site_id == CAFE
    assert appmod._gateway_authenticate(db.session.get(Tenant, TID), CODE, CODE, 'AA:BB:CC:00:00:01', db.session.get(Site, CAFE))[0]
# a bad value changes nothing
r = html.unescape(c.post('/vouchers/edit', data={'csrf_token': tok(e), 'ids': VID, 'plan_id': FAST, 'validity_value': 0, 'validity_unit': 'hours',
                                                 'price': '2500', 'max_devices': 2, 'sites_all': '1'}, follow_redirects=True).text)
assert 'between 1 hour and 366 days' in r
with app.app_context():
    assert db.session.get(Voucher, VID).validity_minutes == 3 * 1440

# many at once from the list's bulk bar: only the ticked fields change
with app.app_context():
    ids = [v.id for v in Voucher.query.filter_by(batch='everywhere')]
lst = c.get('/vouchers?batch=everywhere').text
r = c.post('/vouchers/bulk', data={'csrf_token': tok(lst), 'action': 'edit', 'scope': 'ticked', 'ids': ids, 'batch': 'everywhere'})
assert '/vouchers/edit' in r.headers['Location']
e = html.unescape(c.get(r.headers['Location']).text)
assert 'Edit 3 vouchers' in e and 'Tick what you want to change' in e
c.post('/vouchers/edit', data={'csrf_token': tok(e), 'ids': ','.join(map(str, ids)), 'change_price': '1', 'price': '700',
                               'change_sites': '1', 'sites_form': '1', 'sites': [LIBRARY], 'plan_id': FAST, 'validity_value': 9, 'validity_unit': 'hours'})
with app.app_context():
    for v in Voucher.query.filter(Voucher.id.in_(ids)):
        assert v.price == 700 and [s.id for s in v.sites] == [LIBRARY]
        assert v.plan_id == SLOW and v.validity_minutes == 1440       # not ticked: unchanged
    # back to all sites
e = html.unescape(c.get(f'/vouchers/edit?ids={ids[0]}').text)
c.post('/vouchers/edit', data={'csrf_token': tok(e), 'ids': ids[0], 'plan_id': SLOW, 'validity_value': 1, 'validity_unit': 'days',
                               'price': '700', 'max_devices': 1, 'sites_all': '1'})
with app.app_context():
    assert db.session.get(Voucher, ids[0]).sites == []
# deleting a voucher removes its sites too
lst = c.get('/vouchers').text
c.post(f'/vouchers/{VID}/delete', data={'csrf_token': tok(lst)})
with app.app_context():
    assert db.session.execute(db.text('SELECT COUNT(*) FROM voucher_sites WHERE voucher_id = :v'), {'v': VID}).scalar() == 0
print('VOUCHER SITES EDIT OK')
