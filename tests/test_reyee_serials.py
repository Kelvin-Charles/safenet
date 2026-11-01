"""Reyee projects in SafeNet's account are found by the access point's serial number: Ruijie Cloud says which project
holds it, and that project is connected. Never a project another site uses, nor one named after another business
(someone typing a serial number that isn't theirs); a serial number registered at one site can't be sent by another."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import ruijie
PROJECTS = [('1', 'Olasiti'), ('2', 'USMART - TICD'), ('3', 'Split A'), ('4', 'Split B')]
DEVICES = {'1': ['G1UC09S02030A'], '2': ['G1USMART00001'], '3': ['G1SPLIT00001'], '4': ['G1SPLIT00002']}
calls = []


class FakeCloud:
    def __init__(self, *a): self.base, self.appid = (list(a) + ['', ''])[:2]
    def token(self): pass
    def projects(self): return list(PROJECTS)
    def devices(self, gid): calls.append(gid); return list(DEVICES.get(gid, []))
    where = ruijie.Cloud.where
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
    for name, slug in (('Kpstar', 'kpstar'), ('USMART', 'usmart'), ('Thief', 'thief'), ('Split', 'split')):
        t = Tenant(name=name, slug=slug, status='active'); db.session.add(t); db.session.flush(); ids[slug] = t.id
        a = Admin(username=slug, email=f'{slug}@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
        db.session.add(Site(tenant_id=t.id, name='Main site'))
        db.session.add(Package(tenant_id=t.id, name='Day', price=Decimal(1000), validity_minutes=1440))
    a = Admin(username='boss', email='b@x.tz', role='owner', is_superadmin=True, email_verified_at=now); a.set_password('password1'); db.session.add(a)
    db.session.commit()
    site_of = {slug: Site.query.filter_by(tenant_id=tid).first().id for slug, tid in ids.items()}


def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c


def send(slug, sn):
    c = login(slug); s = c.get('/sites').text
    return c, s, html.unescape(c.post(f"/sites/{site_of[slug]}/ruijie-cloud", data={'csrf_token': tok(s), 'action': 'managed', 'sn': sn},
                                      follow_redirects=True).text)


group = lambda slug: db.session.get(Site, site_of[slug]).ruijie_group_id
cb = login('boss')
p = cb.get('/platform/reyee').text
cb.post('/platform/reyee/keys', data={'csrf_token': tok(p), 'appid': 'openabc', 'secret': 'k'})
# Kpstar's project is called "Olasiti" (not its name): found by the serial number and connected at once
_, _, r = send('kpstar', 'g1uc09s02030a')
assert 'your project "Olasiti" was found' in r
with app.app_context():
    assert group('kpstar') == '1'
# another business typing Kpstar's serial number is refused before anything is looked up
_, _, r = send('thief', 'G1UC09S02030A')
assert 'already registered at another site' in r
with app.app_context():
    assert group('thief') is None and db.session.get(Site, site_of['thief']).ruijie_sn is None
# ... and a project named after another business is never given, even with its serial number
_, _, r = send('thief', 'G1USMART00001')
assert 'belongs to another business' in r
with app.app_context():
    assert group('thief') is None
# access points split over two projects: held for the platform admin
_, _, r = send('split', 'G1SPLIT00001\nG1SPLIT00002')
assert 'different Ruijie projects' in r
with app.app_context():
    assert group('split') is None
# a serial number not added yet: waiting; once the platform admin adds it, one click connects it
_, _, r = send('usmart', 'G1USMARTNEW01')
assert 'Waiting for SafeNet' in r
with app.app_context():
    assert group('usmart') is None
DEVICES['2'].append('G1USMARTNEW01')
appmod._ruijie_cache.clear()                       # (read again: Ruijie is asked at most every few minutes)
p = html.unescape(cb.get('/platform/reyee').text)
assert 'Found in USMART - TICD' in p and 'its access point is here' in p
r = html.unescape(cb.post('/platform/reyee/match', data={'csrf_token': tok(p)}, follow_redirects=True).text)
assert '1 connected by their serial numbers' in r
with app.app_context():
    assert group('usmart') == '2'
# businesses never choose a project themselves
c = login('split'); s = c.get('/sites').text
assert c.post(f"/sites/{site_of['split']}/ruijie-cloud", data={'csrf_token': tok(s), 'action': 'project', 'group_id': '3'}).status_code == 403
# Ruijie's rate limit: the platform page never offers to disconnect a site when projects can't be read
appmod._ruijie_cache.clear()
FakeCloud.projects = lambda self: (_ for _ in ()).throw(ruijie.RuijieError('Ruijie Cloud: Too many requests'))
p = html.unescape(cb.get('/platform/reyee').text)
assert "can't be read from Ruijie Cloud right now" in p and 'disconnect' not in p
with app.app_context():                             # ... and every worker stops asking for a while
    assert appmod._ruijie_paused('openabc') > 10
asked = []
FakeCloud.projects = lambda self: asked.append(1) or []
p = html.unescape(cb.get('/platform/reyee').text)
assert not asked and 'asks again in about' in p
with app.app_context():                             # the guest sync waits too
    db.session.get(Site, site_of['kpstar']).ruijie_synced_at = None; db.session.commit()
    calls.clear(); appmod._ruijie_sync_due()
    assert db.session.get(Site, site_of['kpstar']).ruijie_synced_at is None
assert ruijie.busy('Ruijie Cloud: Too many requests') and ruijie.busy('Ruijie Cloud answered 429: x') and not ruijie.busy('Login failed')
print('REYEE SERIALS OK')
