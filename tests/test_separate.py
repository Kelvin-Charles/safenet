"""The platform admin's login can be separated from the business it belonged to: the business gets its own owner
login, the platform login keeps only the platform, and nothing of the business moves."""
import html, os, re, sys
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations
from models import Admin, Tenant, Site, Voucher
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='SafeNet WiFi', slug='safenet-wifi', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    db.session.add(Site(tenant_id=TID, name='JRIIT Hostel'))
    tenant_sites(TID)
    db.session.add(Voucher(tenant_id=TID, code='12345678', validity_minutes=60, batch='x'))
    boss = Admin(username='boss', email='boss@x.tz', tenant_id=TID, role='owner', is_superadmin=True, email_verified_at=datetime.utcnow())
    boss.set_password('password1'); db.session.add(boss)
    other = Admin(username='taken', email='taken@x.tz', tenant_id=TID, role='staff', email_verified_at=datetime.utcnow())
    other.set_password('password1'); db.session.add(other)
    db.session.commit()


def login(u, pw='password1'):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': pw, 'csrf_token': tok(r.text)}); return c


c = login('boss')
p = html.unescape(c.get('/platform/tenants').text)
assert 'Your login is both the platform and the business "SafeNet WiFi"' in p
send = lambda **d: html.unescape(c.post('/platform/separate', data={'csrf_token': tok(p), **d}, follow_redirects=True).text)
assert 'at least 10 characters' in send(username='jriit', email='j@x.tz', password='short')
assert 'already used' in send(username='taken', email='new@x.tz', password='a-long-password')
assert 'Choose a username' in send(username='a b', email='j@x.tz', password='a-long-password')
r = send(username='JRIIT', email='JRIIT@x.tz', password='a-long-password')
assert 'Your login is now for the platform only' in r and '"jriit"' in r and 'Your login is both the platform' not in r
with app.app_context():
    b = Admin.query.filter_by(username='boss').one()
    o = Admin.query.filter_by(username='jriit').one()
    assert b.tenant_id is None and b.is_superadmin and o.tenant_id == TID and o.role == 'owner' and not o.is_superadmin
    assert [s.name for s in tenant_sites(TID)][-1] == 'JRIIT Hostel' and Voucher.query.filter_by(tenant_id=TID).count() == 1
# the platform login: business pages send it to the platform; it can open the business as its owner
assert c.get('/dashboard').status_code == 302 and '/platform/tenants' in c.get('/dashboard').headers['Location']
assert c.get('/platform/billing').status_code == 200
p = c.get('/platform/tenants').text
r = c.post(f'/platform/impersonate/{TID}', data={'csrf_token': tok(p)}, follow_redirects=True)
assert 'You are logged in as jriit' in html.unescape(r.text)
# the business login runs the business, and sees no platform pages
o = login('jriit', 'a-long-password')
d = html.unescape(o.get('/sites').text)
assert 'JRIIT Hostel' in d and o.get('/platform/tenants').status_code in (302, 403, 404)
print('SEPARATE OK')
