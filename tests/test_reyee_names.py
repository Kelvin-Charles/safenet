"""Ruijie projects in SafeNet's account belong to the business they're named after ("USMART - TICD" is USMART's).
A business only ever sees its own projects: with exactly one it's connected by itself, with several it chooses
among them, and it can never take another business's project."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import ruijie
PROJECTS = [('1', 'USMART - TICD'), ('2', 'Kariakoo Spot Main'), ('3', 'Kariakoo Shop'), ('4', 'Random test'), ('5', 'usmart branch 2')]


class FakeCloud:
    def __init__(self, *a): pass
    def token(self): pass
    def projects(self): return list(PROJECTS)
    def packages(self, group_id): return [{'user_group': 'u', 'profile': 'p', 'minutes': 1440, 'name': '1 day'}]
    def create_package(self, *a, **k): pass


ruijie.Cloud = FakeCloud
ruijie.find_cloud = lambda appid, secret, preferred: 'https://cloud-eu.ruijienetworks.com'
import app as appmod
appmod.send_mail = lambda *a, **k: True
from app import app, db
import migrations
from models import Admin, Tenant, Site, Package
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    ids = {}
    for name, slug in (('USMART', 'usmart'), ('Kariakoo Spot', 'kspot'), ('Kariakoo', 'kariakoo')):
        t = Tenant(name=name, slug=slug, status='active'); db.session.add(t); db.session.flush(); ids[slug] = t.id
        a = Admin(username=slug, email=f'{slug}@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
        db.session.add(Site(tenant_id=t.id, name='Main site'))
        db.session.add(Package(tenant_id=t.id, name='Day', price=Decimal(1000), validity_minutes=1440))
    a = Admin(username='boss', email='b@x.tz', role='owner', is_superadmin=True, email_verified_at=now); a.set_password('password1'); db.session.add(a)
    db.session.commit()
    tenants = Tenant.query.all()
    owner = lambda n: (appmod._project_owner(n, tenants) or Tenant(name='-')).name
    assert owner('USMART - TICD') == 'USMART' and owner('usmart branch 2') == 'USMART'
    assert owner('Kariakoo Spot Main') == 'Kariakoo Spot'            # the longer name wins over "Kariakoo"
    assert owner('Kariakoo Shop') == 'Kariakoo' and owner('Random test') == '-' and owner('USMARTNESS') == '-'
    site_of = {slug: Site.query.filter_by(tenant_id=tid).first().id for slug, tid in ids.items()}


def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c


cb = login('boss')
p = cb.get('/platform/reyee').text
cb.post('/platform/reyee/keys', data={'csrf_token': tok(p), 'appid': 'openabc', 'secret': 'k'})
# Kariakoo Spot has exactly one project with its name: connected the moment it sends the serial number
ck = login('kspot'); s = ck.get('/sites').text
r = html.unescape(ck.post(f"/sites/{site_of['kspot']}/ruijie-cloud", data={'csrf_token': tok(s), 'action': 'managed', 'sn': 'G1UB16E017692'},
                          follow_redirects=True).text)
assert 'your project "Kariakoo Spot Main" was found' in r
with app.app_context():
    assert db.session.get(Site, site_of['kspot']).ruijie_group_id == '2'
# USMART has two: it chooses, and sees only its own
cu = login('usmart'); s = cu.get('/sites').text
r = html.unescape(cu.post(f"/sites/{site_of['usmart']}/ruijie-cloud", data={'csrf_token': tok(s), 'action': 'managed', 'sn': 'G1UB16E017700'},
                          follow_redirects=True).text)
assert 'USMART - TICD' in r and 'usmart branch 2' in r
for other in ('Kariakoo', 'Random test'):
    assert other not in r
with app.app_context():
    assert 'Kariakoo' not in (db.session.get(Site, site_of['usmart']).ruijie_packages or '')
# it can't take another business's project, even by sending the id
assert cu.post(f"/sites/{site_of['usmart']}/ruijie-cloud", data={'csrf_token': tok(s), 'action': 'project', 'group_id': '3'}).status_code == 403
r = html.unescape(cu.post(f"/sites/{site_of['usmart']}/ruijie-cloud", data={'csrf_token': tok(s), 'action': 'project', 'group_id': '5'},
                          follow_redirects=True).text)
assert 'connected' in r
with app.app_context():
    assert db.session.get(Site, site_of['usmart']).ruijie_group_id == '5'
# Kariakoo (shorter name) is waiting; the platform admin connects everyone waiting by name in one click
ka = login('kariakoo'); s = ka.get('/sites').text
ka.post(f"/sites/{site_of['kariakoo']}/ruijie-cloud", data={'csrf_token': tok(s), 'action': 'managed', 'sn': 'G1UB16E017711'})
with app.app_context():
    assert db.session.get(Site, site_of['kariakoo']).ruijie_group_id == '3'   # "Kariakoo Shop", never "Kariakoo Spot Main"
p = html.unescape(cb.get('/platform/reyee').text)
assert 'not named after any business' in p and 'Random test' in p
assert 'named for Kariakoo Spot' in p or 'used by' in p
print('REYEE NAMES OK')
