"""Mobile app, Wi-Fi customers: buy a package inside the app (PIN prompt, wait, the code), and sign in with the phone
number by SMS only once: the phone is remembered after that, and no second SMS goes out while a code still works."""
import os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel,mpesa')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
pay = {'status': 'PROCESSING'}
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay['status'], 'collectedAmount': '1000'}
import app as appmod
texts = []
appmod.sms_is_configured = lambda: True
appmod.send_sms_async = lambda to, text, *a, **k: texts.append((to, text))
from app import app, db
import migrations
from models import Tenant, Package, Voucher, Payment, RateEvent
app.config.update(TESTING=True)
now = datetime.utcnow()
PHONE = '255780000001'
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='active'); other = Tenant(name='Other', slug='other', status='active')
    db.session.add_all([t, other]); db.session.flush(); TID, OID = t.id, other.id
    pk = Package(tenant_id=TID, name='1 Day', price=Decimal(1000), validity_minutes=1440); db.session.add(pk)
    db.session.add(Package(tenant_id=OID, name='Other day', price=Decimal(1000), validity_minutes=1440))
    v = Voucher(tenant_id=TID, code='31310001', validity_minutes=1440, batch='online-payments', status='active',
                first_used_at=now - timedelta(hours=2), expires_at=now + timedelta(hours=22))
    db.session.add(v); db.session.flush()
    db.session.add(Payment(tenant_id=TID, reference='OLD1', package_name='1 Day', validity_minutes=1440, phone=PHONE, amount=Decimal(1000),
                           net_amount=Decimal(970), currency='TZS', provider='clickpesa', provider_account='platform', status='paid',
                           paid_at=now - timedelta(hours=2), voucher_id=v.id))
    db.session.add(Voucher(tenant_id=TID, code='31310002', validity_minutes=60, batch='cash', price=Decimal(300), status='unused'))
    db.session.commit(); PKG, OPKG = pk.id, Package.query.filter_by(tenant_id=OID).one().id

c = app.test_client()
J = lambda r: r.get_json()

# ---- the phone number, the first time: one SMS
r = c.post('/api/m/guest/login', json={'phone': '0780000001', 'devices': []})
assert r.status_code == 401 and J(r)['need_code'], r.text                       # never signed in on this phone
r = c.post('/api/m/guest/send-code', json={'phone': '0780 000 001'})
assert r.status_code == 200 and J(r)['already_sent'] is False and len(texts) == 1, r.text
otp = re.search(r'\b(\d{6})\b', texts[-1][1]).group(1)
again = J(c.post('/api/m/guest/send-code', json={'phone': '0780000001'}))        # asked again: no second SMS while it works
assert again['already_sent'] and 0 < again['seconds_left'] <= 600 and len(texts) == 1, again
r = c.post('/api/m/guest/login', json={'phone': '0780000001', 'otp': otp})
assert r.status_code == 200 and J(r)['device'], r.text
DEVICE = J(r)['device']
# signed out and back in on the same phone: no SMS at all
r = c.post('/api/m/guest/login', json={'phone': '+255 780 000 001', 'devices': ['junk', DEVICE]})
assert r.status_code == 200 and J(r)['token'] and len(texts) == 1, r.text
G = {'Authorization': 'Bearer ' + J(r)['token']}
# that phone's remembered sign-in doesn't open another number
assert c.post('/api/m/guest/login', json={'phone': '0780000002', 'devices': [DEVICE]}).status_code == 401
# after the code was used, a new sign-in on a new phone gets a new code (the old one is gone)
r = c.post('/api/m/guest/send-code', json={'phone': '0780000001'})
assert J(r)['already_sent'] is False and len(texts) == 2

# ---- buying inside the app
shop = J(c.get(f'/api/m/guest/shop/{TID}', headers=G))
assert shop['can_buy'] and [p['name'] for p in shop['packages']] == ['1 Day'] and shop['phone'] == PHONE, shop
assert {n['id'] for n in shop['networks']} == {'airtel', 'mpesa'} and shop['networks'][0]['logo'].endswith('.png')
assert c.get(f'/api/m/guest/shop/{OID}', headers=G).status_code == 404            # a business they never bought from
assert c.post('/api/m/guest/buy', headers=G, json={'business_id': OID, 'package_id': OPKG, 'phone': PHONE}).status_code == 404
assert c.post('/api/m/guest/buy', headers=G, json={'business_id': TID, 'package_id': OPKG, 'phone': PHONE}).status_code == 400
r = c.post('/api/m/guest/buy', headers=G, json={'business_id': TID, 'package_id': PKG, 'phone': '0780000001', 'network': 'airtel'})
assert r.status_code == 200 and J(r)['reference'], r.text
ref = J(r)['reference']
with app.app_context():
    p = Payment.query.filter_by(reference=ref).one()
    assert p.nas_identifier == 'mobile-app' and p.phone == PHONE
assert J(c.get(f'/api/m/guest/pay/{ref}', headers=G))['status'] == 'pending'
pay['status'] = 'SUCCESS'
with app.app_context(): Payment.query.filter_by(reference=ref).update({'checked_at': None}); db.session.commit()
done = J(c.get(f'/api/m/guest/pay/{ref}', headers=G))
assert done['status'] == 'paid' and done['code'] and done['minutes'] == 1440 and 'token' not in done, done
codes = {x['code'] for x in J(c.get('/api/m/guest/home', headers=G))['codes']}
assert done['code'] in codes                                                       # in their list straight away
assert c.get(f'/api/m/guest/pay/{ref}').status_code == 401                         # not without signing in

# ---- signed in with a voucher code: buy, and the new code joins their list
pay['status'] = 'PROCESSING'
V = {'Authorization': 'Bearer ' + J(c.post('/api/m/guest/login', json={'code': '31310002'}))['token']}
shop = J(c.get(f'/api/m/guest/shop/{TID}', headers=V)); assert shop['can_buy'] and shop['phone'] is None
with app.app_context():
    Payment.query.update({'created_at': now - timedelta(minutes=5)}); db.session.commit()      # past the 90-second guard
r = c.post('/api/m/guest/buy', headers=V, json={'business_id': TID, 'package_id': PKG, 'phone': '0780000009', 'network': 'airtel'})
assert r.status_code == 200, r.text
ref2 = J(r)['reference']
pay['status'] = 'SUCCESS'
with app.app_context(): Payment.query.filter_by(reference=ref2).update({'checked_at': None}); db.session.commit()
done = J(c.get(f'/api/m/guest/pay/{ref2}', headers=V))
assert done['status'] == 'paid' and done['token'], done
V2 = {'Authorization': 'Bearer ' + done['token']}
assert {x['code'] for x in J(c.get('/api/m/guest/home', headers=V2))['codes']} == {'31310002', done['code']}
assert c.get(f'/api/m/guest/pay/{ref}', headers=V).status_code == 200            # same business: they may check it

# ---- on a SafeNet Wi-Fi: the app knows which one (the site's internet address), and buying there needs no account
from models import Site, SiteAddress
from tenancy import tenant_sites
SITE_IP, OTHER_IP = '41.59.10.20', '41.59.10.99'
with app.app_context():
    HOME = tenant_sites(TID)[0].id
with app.test_request_context('/omada/x', environ_base={'REMOTE_ADDR': SITE_IP}):
    appmod._site_seen(HOME)                              # a guest opened this site's login page
with app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.168.1.10'}):
    appmod._site_seen(HOME)                              # private addresses are not kept
with app.app_context():
    assert [(a.site_id, a.ip) for a in SiteAddress.query.all()] == [(HOME, SITE_IP)]
def at(ip):
    client = app.test_client(); client.environ_base['REMOTE_ADDR'] = ip; return client
h = J(at(SITE_IP).get('/api/m/here'))
assert h['found'] and h['business']['id'] == TID and h['site']['id'] == HOME and h['can_buy'] and h['here'], h
assert J(at(OTHER_IP).get('/api/m/here')) == {'found': False, 'ambiguous': False}
HERE = {'X-Here': h['here']}
anon = at(SITE_IP)
assert anon.get(f'/api/m/guest/shop/{TID}').status_code == 401                 # neither signed in nor on the Wi-Fi
shop = J(anon.get(f'/api/m/guest/shop/{TID}', headers=HERE)); assert shop['site_id'] == HOME and shop['phone'] is None
assert anon.get(f'/api/m/guest/shop/{OID}', headers=HERE).status_code == 404    # only the business whose Wi-Fi it is
assert anon.get(f'/api/m/guest/shop/{TID}', headers={'X-Here': 'forged'}).status_code == 401
pay['status'] = 'PROCESSING'
with app.app_context():
    Payment.query.update({'created_at': now - timedelta(minutes=5)}); db.session.commit()
r = anon.post('/api/m/guest/buy', headers=HERE, json={'business_id': TID, 'package_id': PKG, 'phone': '0780000077', 'network': 'airtel'})
assert r.status_code == 200, r.text
ref3 = J(r)['reference']
pay['status'] = 'SUCCESS'
with app.app_context(): Payment.query.filter_by(reference=ref3).update({'checked_at': None}); db.session.commit()
done = J(anon.get(f'/api/m/guest/pay/{ref3}', headers=HERE))
assert done['status'] == 'paid' and done['code'] and done['token'], done        # signed in with the code just bought
mine = J(anon.get('/api/m/guest/home', headers={'Authorization': 'Bearer ' + done['token']}))
assert [x['code'] for x in mine['codes']] == [done['code']]
# an address two businesses were seen from (e.g. one ISP's shared address): no guess
with app.app_context():
    OSITE = tenant_sites(OID)[0].id
with app.test_request_context('/', environ_base={'REMOTE_ADDR': SITE_IP}):
    appmod._site_seen_cache.clear(); appmod._site_seen(OSITE)
assert J(at(SITE_IP).get('/api/m/here')) == {'found': False, 'ambiguous': True}
print('mobile buy ok')
