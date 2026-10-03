"""'My Wi-Fi' guest app: add a code, see time and data, buy more (the phone reconnects with it), buy for a friend."""
import html, json, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
pay = {'status': 'PROCESSING'}
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay['status'], 'collectedAmount': '1000'}
import app as appmod
appmod.sms_is_configured = lambda: True
appmod.send_sms_async = lambda *a, **k: None
from app import app, db, _returning_code
import migrations
from models import Tenant, Package, Voucher, RadAcct, RadCheck, Payment
app.config.update(TESTING=True)
now = datetime.utcnow()
MAC = 'AA-BB-CC-00-00-07'
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='active', portal_color='#0F766E'); other = Tenant(name='Other', slug='other', status='active')
    db.session.add_all([t, other]); db.session.flush(); TID, OID = t.id, other.id
    db.session.add(Package(tenant_id=TID, name='1 Day', price=Decimal(1000), validity_minutes=1440))
    v = Voucher(tenant_id=TID, code='55667788', validity_minutes=360, batch='cash', status='active', first_used_at=now - timedelta(hours=1),
                expires_at=now + timedelta(hours=5), first_mac=MAC.lower().replace('-', ':'))
    db.session.add_all([v, RadCheck(username='55667788', attribute='Cleartext-Password', op=':=', value='55667788'),
                        Voucher(tenant_id=OID, code='99990000', validity_minutes=60, batch='x', status='unused')])
    db.session.add(RadAcct(acctsessionid='s1', acctuniqueid='s1', username='55667788', nasipaddress='1.1.1.1', groupname='', acctterminatecause='',
                           calledstationid='gw', callingstationid=MAC, acctstarttime=now - timedelta(hours=1), acctupdatetime=now,
                           acctsessiontime=3600, acctinputoctets=20_000_000, acctoutputoctets=300_000_000))
    db.session.commit(); PKG = Package.query.filter_by(tenant_id=TID).one().id

c = app.test_client()
# the app page: installable, branded, in Kiswahili on request
page = c.get('/app/zulu?lang=sw').text
assert 'rel="manifest" href="/app/zulu/manifest.webmanifest"' in page and '--brand:#0F766E' in page and 'Wi-Fi Yangu' in page
m = c.get('/app/zulu/manifest.webmanifest')
assert m.headers['Content-Type'].startswith('application/manifest+json')
mf = json.loads(m.data); assert mf['start_url'] == '/app/zulu' and mf['display'] == 'standalone' and {i['sizes'] for i in mf['icons']} == {'192x192', '512x512'}
assert c.get(mf['icons'][1]['src']).status_code == 200
sw = c.get('/app/sw.js'); assert sw.headers['Service-Worker-Allowed'] == '/app/' and 'caches' in sw.text
assert c.get('/app/nobody').status_code == 404

# adding a code: wrong ones are refused (and limited), another business's codes don't work here
assert c.post('/app/zulu/api/link', json={'code': '11112222'}).status_code == 404
assert c.post('/app/zulu/api/link', json={'code': '99990000'}).status_code == 404
r = c.post('/app/zulu/api/link', json={'code': '5566 7788'}).get_json()
TOKEN = r['token']; assert r['voucher']['code'] == '55667788'
assert c.post('/app/other/api/me', json={'tokens': [TOKEN]}).get_json()['vouchers'] == []          # token only for its business
me = c.post('/app/zulu/api/me', json={'tokens': [TOKEN, 'forged.token']}).get_json()
v = me['vouchers'][0]
assert v['state'] == 'active' and v['online'] == 1 and 17000 < v['seconds_left'] <= 18000 and v['down'] == 300_000_000 and v['up'] == 20_000_000
assert me['can_buy'] and me['can_gift'] and [p['name'] for p in me['packages']] == ['1 Day'] and me['networks'][0]['id'] == 'airtel'

# buy more for this phone: the new code waits for this phone and connects it when the current time ends
b = c.post('/app/zulu/api/buy', json={'tokens': [TOKEN], 'package_id': PKG, 'phone': '0684 000 111', 'network': 'airtel'}).get_json()
ref = b['reference']; assert b['phone'] == '255684000111' and not b['gift_phone']
assert c.get(f'/app/zulu/api/pay/{ref}').get_json()['status'] == 'pending'
pay['status'] = 'SUCCESS'
with app.app_context(): Payment.query.filter_by(reference=ref).update({'checked_at': None}); db.session.commit()
p = c.get(f'/app/zulu/api/pay/{ref}').get_json()
assert p['status'] == 'paid' and p['code'] and p['token']
NEW = p['code']
with app.app_context():
    nv = Voucher.query.filter_by(code=NEW).one(); assert nv.first_mac == MAC.lower().replace('-', ':') and nv.status == 'unused'
    assert _returning_code(TID, MAC) == '55667788'                     # current package still has time
    Voucher.query.filter_by(code='55667788').update({'expires_at': datetime.utcnow() - timedelta(minutes=1)}); db.session.commit()
    assert _returning_code(TID, MAC) == NEW                            # then the new one, without typing it
    assert _returning_code(TID, 'AA-BB-CC-00-00-99') is None           # only for that phone
# the app now lists both (the new one first: it has time), and the purchase history by the same number
me = c.post('/app/zulu/api/me', json={'tokens': [TOKEN, p['token']]}).get_json()
assert [x['code'] for x in me['vouchers']] == [NEW, '55667788'] and me['vouchers'][0]['state'] == 'unused'

# buy for a friend: needs SMS; the friend's code doesn't show the buyer's history
pay['status'] = 'PROCESSING'
with app.app_context(): Payment.query.update({'created_at': datetime.utcnow() - timedelta(minutes=5)}); db.session.commit()
g = c.post('/app/zulu/api/buy', json={'tokens': [TOKEN], 'package_id': PKG, 'phone': '0684000111', 'network': 'airtel',
                                       'gift': True, 'gift_phone': '0712000222'}).get_json()
assert g.get('gift_phone') == '255712000222', g
pay['status'] = 'SUCCESS'
with app.app_context(): Payment.query.filter_by(reference=g['reference']).update({'checked_at': None}); db.session.commit()
gp = c.get(f"/app/zulu/api/pay/{g['reference']}").get_json()
assert gp['status'] == 'paid' and gp['gift_phone'] == '255712000222' and 'token' not in gp
friend = c.post('/app/zulu/api/link', json={'code': gp['code']}).get_json()['token']
fme = c.post('/app/zulu/api/me', json={'tokens': [friend]}).get_json()
assert [x['code'] for x in fme['vouchers']] == [gp['code']]          # not the buyer's packages
with app.app_context():
    db.session.get(Tenant, TID).sms_to_guests = False; db.session.commit()
assert c.post('/app/zulu/api/me', json={'tokens': [TOKEN]}).get_json()['can_gift'] is False

# the connected screen links to the app with the code
from gateway import portal_ui as ui
s = ui.status_page(ui.theme({}), 'en', user='55667788', remaining=3600, app_url='/app/zulu#code=55667788')
assert 'Get the Wi-Fi app' in s and 'href="/app/zulu#code=55667788"' in s
assert 'Get the Wi-Fi app' not in ui.status_page(ui.theme({}), 'en', user='x', remaining=3600)

# too many wrong codes from one connection: blocked for a while
for i in range(12):
    last = c.post('/app/zulu/api/link', json={'code': f'1000{i:04d}'})
assert last.status_code == 429
print('GUEST APP OK')
