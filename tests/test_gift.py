"""Buy for a friend: the payer gets the PIN prompt, the friend gets the code by SMS, the payer's phone isn't let in."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel',
                  PUBLIC_URL='https://radius.example.tz', WIFIDOG_BASE='http://radius.example.tz:5001')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
pay = {'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay['status'], 'collectedAmount': '1000'}
import app as appmod
from app import app, db
import migrations
from models import Admin, Tenant, Package, Payment, Voucher, WifidogSession, Gateway
from tenancy import tenant_sites
from gateway import portal_ui
sms = []
appmod.send_sms_async = lambda to, text, ref=None: sms.append((to, text))
appmod.sms_is_configured = lambda: True
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add_all([o, Package(tenant_id=t.id, name='1 Day', price=Decimal(1000), validity_minutes=1440)])
    db.session.commit(); TID = t.id; SID = tenant_sites(TID)[0].id
    PKG = Package.query.filter_by(tenant_id=TID).one().id

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
c.post(f'/sites/{SID}/wifidog', data={'csrf_token': tok(c.get('/sites').text), 'action': 'enable'})
with app.app_context(): TOKEN = db.session.get(__import__('models').Site, SID).portal_token

# the buy form offers "buy for a friend", in both languages
H = 'https://radius.example.tz'
g = app.test_client()
g.get(f'/wifidog/{TOKEN}/login/?' + urlencode(dict(gw_address='192.168.110.1', gw_port='2060', gw_id='RG', mac='aa:bb:cc:00:00:04',
                                                   ip='192.168.110.23', url='http://example.com/')), base_url=H)
page = html.unescape(g.get(f'/wifidog/{TOKEN}/guest', base_url=H).text)
assert 'Buy for a friend' in page and 'name="gift_phone"' in page and 'id="gift-box" hidden' in page, page[-3000:]
assert 'Nunulia rafiki' in html.unescape(g.get(f'/wifidog/{TOKEN}/guest?lang=sw', base_url=H).text)
g.get(f'/wifidog/{TOKEN}/guest?lang=en', base_url=H)

buy = lambda **d: g.post(f'/wifidog/{TOKEN}/guest/buy', data={'package_id': PKG, 'phone': '684000111', 'network': 'airtel', 'agree': '1', **d}, base_url=H)
# ticked without a (valid) number: refused, nothing charged
for bad in ('', '12345'):
    assert "Enter your friend's mobile number" in html.unescape(buy(gift='1', gift_phone=bad).text)
with app.app_context(): assert Payment.query.count() == 0
# a number without the tick is ignored (normal purchase for yourself) — checked through the API below

r = buy(gift='1', gift_phone='0712 345 678')
assert r.status_code == 302 and '/guest/buy/wait?ref=SN' in r.headers['Location'], r.headers.get('Location')
wait = r.headers['Location']; ref = wait.split('ref=')[1]
with app.app_context():
    pm = Payment.query.filter_by(reference=ref).one(); assert pm.phone == '255684000111' and pm.gift_phone == '255712345678'
w = html.unescape(g.get(wait, base_url=H).text)
assert 'Check your phone' in w and 'send the code to 0712 345 678 by SMS' in w, w[-2000:]

pay['status'] = 'SUCCESS'
with app.app_context(): Payment.query.filter_by(reference=ref).update({'checked_at': None}); db.session.commit()
r = g.get(wait, base_url=H)
done = html.unescape(r.text)
assert r.status_code == 200 and 'The code is on its way' in done and '0712 345 678' in done, done[-2000:]
with app.app_context():
    code = Payment.query.filter_by(reference=ref).one().voucher.code
    assert WifidogSession.query.count() == 0                     # the payer's phone was not let in
    assert Voucher.query.filter_by(code=code).one().status == 'unused'
assert code in done
friend = [x for x in sms if x[0] == '255712345678']; payer = [x for x in sms if x[0] == '255684000111']
assert len(friend) == 1 and code in friend[0][1] and '0684000111 bought you 1 Day' in friend[0][1], sms
assert len(payer) == 1 and code in payer[0][1] and 'to 0712345678' in payer[0][1], sms
# the owner sees who it was for
assert 'for 255712345678' in c.get('/payments').text

# gateway API (SafeNet gateway box): gift_phone passed through and reported back
api_key = 'gw-test-key-0123456789'
with app.app_context():
    db.session.add(Gateway(tenant_id=TID, name='gw', site_id=SID, key_prefix=api_key[:8], key_hash=appmod._hash_key(api_key)))
    db.session.commit()
a = app.test_client()
hdr = {'X-SafeNet-Key': api_key}
body = {'package_id': PKG, 'phone': '0684000222', 'network': 'airtel', 'mac': 'aa:bb:cc:00:00:05', 'ip': '10.10.0.9'}
j = a.post('/api/portal/purchase', json={**body, 'gift_phone': '0754000333'}, headers=hdr)
assert j.status_code == 200 and j.get_json()['gift_phone'] == '255754000333', (j.status_code, j.text[:300])
j = a.post('/api/portal/purchase', json={**body, 'phone': '0684000444', 'gift_phone': ''}, headers=hdr)
assert j.status_code == 400 and "friend's" in j.get_json()['error']
j = a.post('/api/portal/purchase', json={**body, 'phone': '0684000555'}, headers=hdr)
assert j.status_code == 200 and j.get_json()['gift_phone'] == ''                         # older gateways: no gift
j = a.post('/api/portal/purchase', json={**body, 'phone': '0684000666', 'gift_phone': '0684000666'}, headers=hdr)
assert j.status_code == 200 and j.get_json()['gift_phone'] == ''                         # own number = for yourself

# Kiswahili gift page
th = portal_ui.theme({})
sw = html.unescape(portal_ui.gift_page(th, 'sw', code='12345678', friend='255712345678', package='1 Day'))
assert 'Vocha imetumwa' in sw and '0712 345 678' in sw and '12345678' in sw
print('GIFT OK')
