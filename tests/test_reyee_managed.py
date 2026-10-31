"""Reyee access points managed by SafeNet: the business only gives the serial number; the platform admin adds it to
SafeNet's own Ruijie Cloud account and picks the project. Businesses never see the account's other projects, and can
still use their own Ruijie Cloud account instead."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import ruijie
made_pkgs = []


class FakeCloud:
    def __init__(self, base, appid, secret): self.secret = secret
    def token(self):
        if self.secret != 'platform-secret':
            raise ruijie.RuijieError('Ruijie Cloud refused the App ID or secret: Login failed')
    def projects(self): return [('111', 'Other client shop'), ('222', 'Kariakoo')]
    def packages(self, group_id): return [{'user_group': 'u1', 'profile': 'p1', 'minutes': 1440, 'name': 'SafeNet 1 day'}]
    def create_package(self, group_id, name, minutes, **kw): made_pkgs.append((group_id, minutes))


ruijie.Cloud = FakeCloud
ruijie.find_cloud = lambda appid, secret, preferred: (FakeCloud(preferred, appid, secret).token(), 'https://cloud-eu.ruijienetworks.com')[1]
import app as appmod
mails = []
appmod.send_mail = lambda to, subject, body, *a, **k: mails.append((to, subject)) or True
from app import app, db
import migrations
from models import Admin, Tenant, Site, Package, PlatformSetting
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kariakoo Spot', slug='kariakoo', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    for u, sa in (('owner', False), ('boss', True)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=None if sa else TID, role='owner', is_superadmin=sa, email_verified_at=now)
        a.set_password('password1'); db.session.add(a)
    db.session.add(Package(tenant_id=TID, name='Siku 3', price=Decimal(3000), validity_minutes=3 * 1440))
    db.session.commit()
    SID = Site.query.filter_by(tenant_id=TID).first().id if Site.query.filter_by(tenant_id=TID).first() else None
    if SID is None:
        s = Site(tenant_id=TID, name='Main site'); db.session.add(s); db.session.commit(); SID = s.id


def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c


with app.app_context():      # a site connected earlier with SafeNet's own keys
    early = Site(tenant_id=TID, name='TICD', ruijie_cloud_url='https://cloud-eu.ruijienetworks.com', ruijie_appid='openabc',
                 ruijie_secret_enc=appmod.secretbox.encrypt('platform-secret'), ruijie_group_id='111', ruijie_group_name='Other client shop')
    db.session.add(early); db.session.commit(); EARLY = early.id
co, cb = login('owner'), login('boss')
# no platform account yet: businesses see only the own-account form
assert 'let SafeNet set it up' not in html.unescape(co.get('/sites').text)
p = cb.get('/platform/reyee').text
assert 'Not set' in p
assert 'refused' in html.unescape(cb.post('/platform/reyee/keys', data={'csrf_token': tok(p), 'appid': 'openabc', 'secret': 'wrong'}, follow_redirects=True).text)
r = html.unescape(cb.post('/platform/reyee/keys', data={'csrf_token': tok(p), 'appid': 'openabc', 'secret': 'platform-secret'}, follow_redirects=True).text)
assert 'accepted the keys' in r and 'Connected · Europe' in r
with app.app_context():
    assert 'platform-secret' not in (db.session.get(PlatformSetting, 'ruijie_secret').value or '')        # stored encrypted
    e = db.session.get(Site, EARLY)
    assert e.ruijie_managed and e.ruijie_group_id == '111'           # became SafeNet-managed, keeping its project
# the business asks SafeNet: only the serial number (and a Wi-Fi name)
s = html.unescape(co.get('/sites').text)
assert 'Recommended: let SafeNet set it up' in s and 'Or use your own Ruijie Cloud account' in s
send = lambda **d: html.unescape(co.post(f'/sites/{SID}/ruijie-cloud', data={'csrf_token': tok(s), 'action': 'managed', **d}, follow_redirects=True).text)
assert 'Enter the serial number' in send(sn='hello there!')
r = send(sn='g1ub16e017692\nG1UB16E017700', ssid='Kariakoo WiFi')
assert 'SafeNet will add your access point' in r and 'Waiting for SafeNet' in r
assert 'openabc' not in r and 'value="111"' not in r          # never another client's project, nor SafeNet's keys
assert any('Reyee to set up: Kariakoo Spot' in subj for _, subj in mails)
with app.app_context():
    site = db.session.get(Site, SID)
    assert site.ruijie_managed and site.ruijie_sn == 'G1UB16E017692, G1UB16E017700' and site.ruijie_ssid == 'Kariakoo WiFi'
    assert site.ruijie_group_id is None                              # not given a project by itself
# the business can't pick a project in SafeNet's account
assert co.post(f'/sites/{SID}/ruijie-cloud', data={'csrf_token': tok(s), 'action': 'project', 'group_id': '111'}).status_code == 403
# the platform admin sees it waiting and picks the project
p = html.unescape(cb.get('/platform/reyee').text)
assert 'Kariakoo Spot' in p and 'G1UB16E017692' in p and 'Waiting for you' in p
r = html.unescape(cb.post(f'/platform/reyee/{SID}', data={'csrf_token': tok(p), 'group_id': '222'}, follow_redirects=True).text)
assert 'uses project Kariakoo' in r
assert made_pkgs == [('222', 3 * 1440)]                              # SafeNet made the 3-day package on Ruijie Cloud
assert any(to == 'owner@x.tz' and 'connected to SafeNet' in subj for to, subj in mails)
with app.app_context():
    assert db.session.get(Site, SID).ruijie_ready
assert 'Connected. Guests see your login page' in html.unescape(co.get('/sites').text)
# its login page .zip for the platform admin to upload
z = cb.get(f'/platform/reyee/{SID}/portal.zip')
assert z.status_code == 200 and z.mimetype == 'application/zip'
# a project already used by another site can't be given twice
with app.app_context():
    other = Site(tenant_id=TID, name='Second', ruijie_managed=True, ruijie_sn='G1UB00000001'); db.session.add(other); db.session.commit(); OID = other.id
assert 'already used' in html.unescape(cb.post(f'/platform/reyee/{OID}', data={'csrf_token': tok(p), 'group_id': '222'}, follow_redirects=True).text)
assert 'already used' in html.unescape(cb.post(f'/platform/reyee/{OID}', data={'csrf_token': tok(p), 'group_id': '111'}, follow_redirects=True).text)
# businesses can't open the platform page
assert co.get('/platform/reyee').status_code == 404
print('REYEE MANAGED OK')
