"""The SafeNet Android app on the Wi-Fi login pages: the platform admin uploads the .apk, phones download it,
and the login page's 'Get the SafeNet app' card is there (hidden, shown by its script on Android only)."""
import io, os, re, sys, tempfile
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PUBLIC_URL='https://radius.example.tz',
                  APP_FILES_DIR=tempfile.mkdtemp())
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
from app import app, db
import migrations
from models import Admin, Tenant, Package
from tenancy import tenant_sites
from decimal import Decimal
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    boss = Admin(username='platform', email='p@x.tz', tenant_id=migrations.default_tenant().id, role='owner', is_superadmin=True, email_verified_at=now)
    boss.set_password('password1')
    t = Tenant(name='Kpstar', slug='kpstar', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    o = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add_all([boss, o, Package(tenant_id=TID, name='6 Hours', price=Decimal(1000), validity_minutes=360)])
    db.session.commit(); SID = tenant_sites(TID)[0].id
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c

def login_page():
    with app.test_request_context('/'):
        site = db.session.get(appmod.Site, SID); tenant = db.session.get(Tenant, TID)
        return appmod._hotspot_page(site, tenant, '/x').get_data(as_text=True)

# nothing uploaded: no download, no card
assert app.test_client().get('/app/android').status_code == 404
assert 'appcard android-app' not in login_page()

# only the platform admin sees the upload page
assert login('owner').get('/platform/app').status_code == 404
pc = login('platform'); p = pc.get('/platform/app').text
assert 'No app uploaded yet' in p
# not an app
r = pc.post('/platform/app', data={'csrf_token': tok(p), 'apk': (io.BytesIO(b'hello'), 'x.apk')}, content_type='multipart/form-data', follow_redirects=True).text
assert 'not an Android app' in r
r = pc.post('/platform/app', data={'csrf_token': tok(p), 'apk': (io.BytesIO(b'PK\x03\x04data'), 'x.zip')}, content_type='multipart/form-data', follow_redirects=True).text
assert 'Choose the .apk' in r
APK = b'PK\x03\x04' + b'\x00' * 2048
r = pc.post('/platform/app', data={'csrf_token': tok(p), 'version': '1.0.0', 'apk': (io.BytesIO(APK), 'app-release.apk')},
            content_type='multipart/form-data', follow_redirects=True).text
assert 'Android app uploaded' in r and 'version 1.0.0' in r, r[-2000:]

# anyone (a guest before paying) downloads it, as an Android app
d = app.test_client().get('/app/android')
assert d.status_code == 200 and d.data == APK
assert d.mimetype == 'application/vnd.android.package-archive'
assert 'SafeNet-1.0.0.apk' in d.headers['Content-Disposition']

# the login page offers it: an absolute link (pages on Ruijie / routers aren't on our site), hidden until the script sees Android
h = login_page()
card = re.search(r'<a class="appcard android-app" href="([^"]+)" download hidden>', h)
assert card and card.group(1).startswith('https://radius.example.tz/app/android?v='), h[-3000:]
assert "/Android/i.test(navigator.userAgent)" in h
assert 'Get the SafeNet app' in h
# gateway boxes are told where to fetch their own copy
with app.app_context():
    db.session.add(appmod.Gateway(tenant_id=TID, name='box', key_prefix='sgw_k', key_hash=appmod._hash_key('sgw_k'))); db.session.commit()
cfg = app.test_client().get('/api/gateway/config', headers={'X-SafeNet-Key': 'sgw_k'}).get_json()
assert cfg['android_app'].startswith('https://radius.example.tz/app/android?v='), cfg
# Ruijie pages carry it too
with app.test_request_context('/'):
    pages = appmod._ruijie_portal_pages(db.session.get(appmod.Site, SID), db.session.get(Tenant, TID),
                                        appmod.portal_ui.theme(appmod.portal_config(db.session.get(Tenant, TID))))
assert 'appcard android-app' in str(pages)
print('ok')
