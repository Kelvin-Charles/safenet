"""Printable 'scan to join our Wi-Fi' QR codes per site (poster and table cards)."""
import html, os, re, sys
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db, _wifi_qr_text
import migrations
from models import Admin, Tenant, Site
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)

# what phones' cameras read: open network, WPA, and special characters escaped
assert _wifi_qr_text('Zulu Free WiFi') == 'WIFI:T:nopass;S:Zulu Free WiFi;;'
assert _wifi_qr_text('Cafe;Bar', 'pa:ss,"x"') == 'WIFI:T:WPA;S:Cafe\;Bar;P:pa\\:ss\\,\\"x\\";;'

with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu-connect', status='active', portal_color='#0F766E', support_phone='0684 000 001')
    db.session.add(t); db.session.flush()
    for u, role in (('owner', 'owner'), ('staffer', 'staff')):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=t.id, role=role, email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    db.session.commit(); TID = t.id
    SID = tenant_sites(TID)[0].id
    om = Site(tenant_id=TID, name='Camp', omada_hosted=True, omada_ssid='Camp Guest'); db.session.add(om); db.session.commit(); OM = om.id
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
c = login('owner')
p = c.get('/sites').text
assert f'/sites/{SID}/wifi-qr' in p and 'Guest Wi-Fi name (for the QR code)' in p
# no Wi-Fi name yet: asked to add it
r = c.get(f'/sites/{SID}/wifi-qr', follow_redirects=True)
assert 'Add the Wi-Fi name' in html.unescape(r.text)
# a too-short password is refused; then saved
assert 'has 8 to 63 characters' in html.unescape(c.post(f'/sites/{SID}/edit', data={'csrf_token': tok(p), 'name': 'Main site', 'wifi_ssid': 'Zulu Free WiFi',
                                                                                    'wifi_password': 'short'}, follow_redirects=True).text)
c.post(f'/sites/{SID}/edit', data={'csrf_token': tok(p), 'name': 'Main site', 'wifi_ssid': 'Zulu Free WiFi', 'wifi_password': ''})
with app.app_context():
    s = db.session.get(Site, SID); assert s.wifi_ssid == 'Zulu Free WiFi' and s.wifi_password is None and s.join_ssid == 'Zulu Free WiFi'
q = html.unescape(c.get(f'/sites/{SID}/wifi-qr').text)
assert '"WIFI:T:nopass;S:Zulu Free WiFi;;"' in q and 'Scan to join our Wi-Fi' in q and 'Changanua' in q and 'Zulu Connect Wi-Fi' in q
assert '"https://radius.safezonetz.com/app/zulu-connect"' in q and 'qrcode.min.js' in q and 'Password / Nenosiri' not in q
cards = html.unescape(c.get(f'/sites/{SID}/wifi-qr?layout=cards').text)
assert cards.count('class="card"') == 6 and 'Zulu Free WiFi' in cards
# with a password: on the poster and in the QR
c.post(f'/sites/{SID}/edit', data={'csrf_token': tok(p), 'name': 'Main site', 'wifi_ssid': 'Zulu Staff', 'wifi_password': 'karibu2026'})
q = html.unescape(c.get(f'/sites/{SID}/wifi-qr').text)
assert '"WIFI:T:WPA;S:Zulu Staff;P:karibu2026;;"' in q and 'Password / Nenosiri' in q and 'karibu2026' in q
# Omada sites use the network SafeNet created, without typing it
assert '"WIFI:T:nopass;S:Camp Guest;;"' in html.unescape(c.get(f'/sites/{OM}/wifi-qr').text)
# staff can print; other businesses' sites are not reachable
assert login('staffer').get(f'/sites/{SID}/wifi-qr').status_code == 200
with app.app_context():
    o = Tenant(name='Other', slug='other', status='active'); db.session.add(o); db.session.flush()
    x = Site(tenant_id=o.id, name='X', wifi_ssid='Other'); db.session.add(x); db.session.commit(); XID = x.id
assert c.get(f'/sites/{XID}/wifi-qr').status_code == 404
print('WIFI QR OK')
