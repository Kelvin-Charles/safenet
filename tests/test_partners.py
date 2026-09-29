"""Partners / shareholders: read-only accounts for the whole business or one site."""
import os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations
from models import Admin, Tenant, Site, Payment, Voucher, RadAcct, BillingPlan
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    plan = BillingPlan.query.filter_by(name='Starter').one()          # 2 staff accounts, owner included
    plan.max_sites = 5
    t = Tenant(name='Morombo Net', slug='morombo', status='active', billing_plan_id=plan.id); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    a = Admin(username='manager', email='m@x.tz', tenant_id=t.id, role='admin', email_verified_at=now); a.set_password('password1')
    db.session.add_all([o, a]); db.session.commit()
    TID = t.id; MAIN = tenant_sites(TID)[0].id
    mw = Site(tenant_id=TID, name='Mwenge'); db.session.add(mw); db.session.commit(); MW = mw.id
    for ref, site, amount in (('SNMAIN0001', MAIN, 1000), ('SNMWENGE01', MW, 2000)):
        db.session.add(Payment(tenant_id=TID, reference=ref, package_name='1 Day', validity_minutes=1440, phone='255684000111',
                               amount=Decimal(amount), net_amount=Decimal(amount), fee_amount=0, status='paid', paid_at=now, site_id=site))
    for code, site in (('11110001', MAIN), ('22220002', MW)):
        db.session.add(Voucher(tenant_id=TID, code=code, validity_minutes=60, batch=f'b{site}', status='active', first_used_at=now,
                               expires_at=now + timedelta(hours=1), site_id=site))
    db.session.add(RadAcct(acctsessionid='m1', acctuniqueid='m1', username='22220002', nasipaddress='1.1.1.1', groupname='', acctterminatecause='',
                           calledstationid=f'omada-{MW}', callingstationid='AA-00-00-00-00-01', acctstarttime=now, acctupdatetime=now,
                           acctsessiontime=0, acctinputoctets=0, acctoutputoctets=5_000_000))
    db.session.add(RadAcct(acctsessionid='x1', acctuniqueid='x1', username='11110001', nasipaddress='1.1.1.1', groupname='', acctterminatecause='',
                           calledstationid=f'omada-{MAIN}', callingstationid='AA-00-00-00-00-02', acctstarttime=now, acctupdatetime=now,
                           acctsessiontime=0, acctinputoctets=0, acctoutputoctets=1_000_000))
    db.session.commit()

def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c

# --- the owner adds partners (partners don't count toward the plan's 2 staff accounts)
co = login('owner')
f = co.get('/team/add').text
assert 'Partner / shareholder' in f and 'The whole business (all sites)' in f and 'Only Mwenge' in f
add = lambda u, site: co.post('/team/add', data={'csrf_token': tok(f), 'username': u, 'email': f'{u}@x.tz', 'role': 'viewer',
                                                 'site_id': site, 'password': 'password1'}, follow_redirects=True).text
assert 'added as a partner' in add('investor', 0)
assert 'added as a partner' in add('mwengepartner', MW)
with app.app_context():
    assert Admin.query.filter_by(username='investor').one().site_id is None
    assert Admin.query.filter_by(username='mwengepartner').one().site_id == MW
team = co.get('/team').text
assert 'Partner · view only' in team and 'Whole business' in team and 'Only Mwenge' in team
# an admin (not the owner) can't add partners
ca = login('manager')
assert 'Partner / shareholder' not in ca.get('/team/add').text

# --- whole-business partner: sees everything, changes nothing
ci = login('investor')
d = ci.get('/dashboard').text
assert 'View only' in d and 'Morombo Net' in d and 'view-only' in d
for url in ('/sites', '/live', '/api/live', '/payments', '/earnings', '/vouchers', '/users', '/accounting', '/auth-logs'):
    assert ci.get(url).status_code == 200, url
p = ci.get('/payments').text
assert 'SNMAIN0001' in p and 'SNMWENGE01' in p
for url in ('/packages', '/settings', '/team', '/billing', '/vouchers/generate', '/users/add', '/gateways', '/settings/payments', f'/sites/{MW}/wifi'):
    r = ci.get(url); assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard'), (url, r.status_code)
assert 'can view but not change' in ci.get('/packages', follow_redirects=True).text
lv = ci.get('/live').text
for url, data in (('/live/disconnect', {'username': '22220002'}), ('/sites/add', {'name': 'X'}), ('/earnings/withdraw', {'amount': 1000})):
    r = ci.post(url, data={'csrf_token': tok(lv), **data}); assert r.status_code == 302, url
with app.app_context():
    from models import SessionKick, Withdrawal
    assert SessionKick.query.count() == 0 and Withdrawal.query.count() == 0 and Site.query.filter_by(name='X').count() == 0
assert ci.post('/api/live', data={}).status_code in (403, 405)
# the business partner may still pick a site in the top bar to look at it
ci.post('/sites/switch', data={'csrf_token': tok(lv), 'site_id': MW})
p = ci.get('/payments').text
assert 'SNMWENGE01' in p and 'SNMAIN0001' not in p

# --- one-site partner: only Mwenge, and no business-wide pages
cm = login('mwengepartner')
d = cm.get('/dashboard').text
assert 'View only' in d and 'Mwenge' in d and '22220002' in d and '11110001' not in d
assert 'TZS 3,000' not in d and 'Omada · Mwenge' in d          # no business-wide balance; readable place
p = cm.get('/payments').text
assert 'SNMWENGE01' in p and 'SNMAIN0001' not in p
v = cm.get('/vouchers').text
assert '22220002' in v and '11110001' not in v
live = cm.get('/api/live').get_json()
assert [x['user'] for x in live['online']] == ['22220002'], live['online']
acc = cm.get('/accounting').text
assert '22220002' in acc and '11110001' not in acc
with app.app_context(): other = RadAcct.query.filter_by(acctuniqueid='x1').one().radacctid
assert cm.get(f'/accounting/{other}').status_code in (302, 404)
for url in ('/earnings', '/sites', '/users', '/auth-logs'):
    assert cm.get(url).status_code == 302, url
# can't switch to another site or see everything
meta = re.search(r'name="csrf-token" content="([^"]+)"', d).group(1)
assert 'action="/sites/switch"' not in d                               # no site switcher for them
cm.post('/sites/switch', data={'csrf_token': meta, 'site_id': ''})
assert 'SNMAIN0001' not in cm.get('/payments').text
# sidebar only shows what they may open
side = cm.get('/dashboard').text
assert 'href="/earnings"' not in side and 'href="/users"' not in side and 'href="/payments"' in side

# --- owners also get their pages filtered by the site picked in the top bar
co.post('/sites/switch', data={'csrf_token': tok(f), 'site_id': MAIN})
p = co.get('/payments').text
assert 'SNMAIN0001' in p and 'SNMWENGE01' not in p
co.post('/sites/switch', data={'csrf_token': tok(f), 'site_id': ''})
assert 'SNMWENGE01' in co.get('/payments').text
print('PARTNERS OK')
