"""Every admin page loads (HTTP 200) for a tenant owner and a platform admin."""
import os, re, sys
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations
from models import Admin, Tenant, Site
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Shop', slug='shop', status='trial', trial_ends_at=now + timedelta(days=3)); db.session.add(t); db.session.flush()
    db.session.add(Site(tenant_id=t.id, name='Second'))
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    p = Admin(username='platform', email='p@x.tz', tenant_id=migrations.default_tenant().id, role='owner', is_superadmin=True, email_verified_at=now); p.set_password('password1')
    db.session.add_all([o, p]); db.session.commit()

def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c

pages = ['/dashboard', '/sites', '/live', '/users', '/users/add', '/vouchers', '/vouchers/generate', '/payments', '/earnings',
         '/packages', '/packages/add', '/plans', '/gateways', '/routers', '/nas', '/nas/add', '/accounting', '/auth-logs', '/billing',
         '/settings/portal', '/settings/payments', '/plans/add', '/settings', '/team', '/team/add', '/radius-features', '/api/live']
rules = {r.rule for r in app.url_map.iter_rules()}
pages = [p for p in pages if p in rules]
missing = [p for p in ['/dashboard', '/sites', '/packages', '/gateways', '/routers', '/live'] if p not in rules]
assert not missing, missing
bad = []
for who in ('owner', 'platform'):
    c = login(who)
    for url in pages + (['/platform/tenants', '/platform/billing', '/platform/payouts'] if who == 'platform' else []):
        r = c.get(url)
        if r.status_code != 200:
            bad.append((who, url, r.status_code))
    # also with a site picked in the top bar
    s = c.get('/sites').text
    with app.app_context(): sid = Site.query.filter_by(name='Second').first().id if who == 'owner' else ''
    c.post('/sites/switch', data={'csrf_token': tok(s), 'site_id': sid})
    for url in ('/dashboard', '/gateways', '/packages', '/routers'):
        r = c.get(url)
        if r.status_code != 200:
            bad.append((who, url + ' (site picked)', r.status_code))
assert not bad, bad
print(f'PAGES OK ({len(pages)} pages)')
