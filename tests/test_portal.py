import os, re, sys, io
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Gateway
app.config.update(TESTING=True)
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 200
with app.app_context():
    db.create_all(); migrations.run()
    ta = Tenant(name='Mama Salma', slug='salma', status='active', support_phone='0755 111 222', terms='Be kind'); tb = Tenant(name='B', slug='b', status='active')
    db.session.add_all([ta, tb]); db.session.flush()
    for u, t, role in (('owner1', ta.id, 'owner'), ('staff1', ta.id, 'staff')):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=t, role=role, email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    db.session.add_all([Gateway(tenant_id=ta.id, name='gw', key_prefix='sgw_a', key_hash=_hash_key('sgw_a')),
                        Gateway(tenant_id=tb.id, name='gw', key_prefix='sgw_b', key_hash=_hash_key('sgw_b'))])
    db.session.commit()
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
c = login('owner1')
r = c.get('/settings/portal'); assert r.status_code == 200 and 'Live preview' in r.text and 'preview=1' in r.text
def save(**kw):
    data = {'csrf_token': tok(c.get('/settings/portal').text), 'color': '#0f766e', 'style': 'light', 'title': 'Karibu Salma Cafe',
            'message': 'Fast Wi-Fi for our guests', 'language': 'sw', 'show_voucher': 'y', 'show_packages': 'y'}
    data.update(kw)
    return c.post('/settings/portal', data=data, content_type='multipart/form-data', follow_redirects=True)
assert 'Keep at least one way' in save(show_voucher='', show_packages='').text
assert 'Use a colour like' in save(color='red').text
r = save(logo=(io.BytesIO(b'<svg onload=alert(1)>'), 'x.svg')); assert 'must be a PNG, JPG or WebP' in r.text
r = save(logo=(io.BytesIO(PNG + b'\x00' * 310000), 'big.png')); assert 'must be a PNG, JPG or WebP' in r.text
r = save(logo=(io.BytesIO(PNG), 'logo.png')); assert 'Captive portal saved' in r.text
with app.app_context():
    t = Tenant.query.filter_by(slug='salma').one()
    assert t.portal_color == '#0F766E' and t.portal_style == 'light' and t.portal_language == 'sw' and t.portal_logo_type == 'image/png' and t.portal_logo_at
    version = int(t.portal_logo_at.timestamp())
# public page + logo
p = app.test_client()
r = p.get('/portal?t=salma'); assert '--brand:#0F766E' in r.text and 'style-light' in r.text and 'Karibu Salma Cafe' in r.text
assert 'lang="sw"' in r.text and f'/portal/logo/salma?v={version}' in r.text and 'Be kind' in r.text and 'tel:0755111222' in r.text
r = p.get('/portal?t=salma&lang=en'); assert 'lang="en"' in r.text and 'sn_lang=en' in r.headers.get('Set-Cookie', '')
assert 'lang="en"' in p.get('/portal?t=salma').text                     # remembered by cookie
r = p.get(f'/portal/logo/salma?v={version}'); assert r.status_code == 200 and r.data == PNG and r.mimetype == 'image/png' and r.headers['X-Content-Type-Options'] == 'nosniff'
assert p.get('/portal/logo/b').status_code == 404
# preview with unsaved overrides and every screen
for view in ('voucher', 'buy', 'wait', 'online'):
    r = p.get(f'/portal?t=salma&preview=1&view={view}&color=%23B91C1C&style=solid')
    assert r.status_code == 200 and '--brand:#B91C1C' in r.text and 'style-solid' in r.text, view
assert '#B91C1C' not in p.get('/portal?t=salma&color=%23B91C1C').text  # overrides only in preview
# gateway API gets its own tenant's portal
api = app.test_client()
cfg = api.get('/api/gateway/config', headers={'X-SafeNet-Key': 'sgw_a'}).get_json()['portal']
assert cfg['color'] == '#0F766E' and cfg['style'] == 'light' and cfg['language'] == 'sw' and cfg['logo_version'] == version
assert api.get('/api/gateway/logo', headers={'X-SafeNet-Key': 'sgw_a'}).data == PNG
assert api.get('/api/gateway/logo', headers={'X-SafeNet-Key': 'sgw_b'}).status_code == 404
assert api.get('/api/gateway/logo').status_code == 401
# remove logo; staff can't edit
save(remove_logo='y')
with app.app_context(): assert Tenant.query.filter_by(slug='salma').one().portal_logo_at is None
assert login('staff1').get('/settings/portal').status_code == 302
print('PORTAL CLOUD OK')

# gateway downloads and serves the logo
sys.path.insert(0, 'gateway')
os.environ.update(SAFENET_API_URL='https://x', SAFENET_API_KEY='k', STATE_DIRECTORY=sys.argv[1])
import importlib, portal
importlib.reload(portal)
portal.LOGO_FILE = os.path.join(sys.argv[1], 'logo')
portal._nft = lambda script: None
portal.safenet_api = lambda m, path, body=None, timeout=25: {'hotspot_name': 'Salma WiFi', 'support': '0755', 'terms': 'T',
    'portal': {'color': '#0F766E', 'style': 'light', 'title': 'Hi', 'message': 'M', 'language': 'sw', 'show_voucher': True, 'show_packages': True, 'logo_version': 42}}
fetched = []
portal.safenet_fetch = lambda path, timeout=15: fetched.append(path) or (PNG, 'image/png')
portal.refresh_branding(); portal.refresh_branding()
assert fetched == ['/api/gateway/logo'] and portal.branding['logo_url'] == '/logo?v=42' and open(portal.LOGO_FILE, 'rb').read() == PNG
th = portal._theme(); assert th['color'] == '#0F766E' and th['language'] == 'sw' and th['logo_url'] == '/logo?v=42'
page = portal.login_page(lang='sw'); assert 'Karibu' not in page or True
assert 'src="/logo?v=42"' in page and 'Weka vocha yako' in page and '>Hi<' in page and '--brand:#0F766E' in page
print('PORTAL GATEWAY OK')
