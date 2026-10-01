"""Voucher SMS to guests cost the tenant TZS 30 each: from the SafeNet Pay balance, or on the monthly bill."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='platform-id', CLICKPESA_API_KEY='platform-key',
                  PLATFORM_FEE_PERCENT='3', SMS_PRICE='30')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa, secretbox
state = {'collected': '1000', 'status': 'SUCCESS'}
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['M-PESA']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': state['status'], 'collectedAmount': state['collected']}
import app as appmod
sent = []
appmod.sms_is_configured = lambda: True
appmod.send_sms_async = lambda to, text, ref=None: sent.append((to, text))
appmod.send_mail = lambda *a, **k: True
from app import app, db, _hash_key, tenant_balance, sms_parts
import migrations
from models import Admin, Tenant, Package, Gateway, SmsCharge, SubscriptionPayment, BillingPlan
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)

# how many SMS a message is billed as
assert sms_parts('x' * 160) == 1 and sms_parts('x' * 161) == 2 and sms_parts('x' * 306) == 2 and sms_parts('x' * 307) == 3
assert sms_parts('Karibu ☕' + 'x' * 62) == 1 and sms_parts('Karibu ☕' + 'x' * 63) == 2      # non-GSM: 70 per SMS

with app.app_context():
    db.create_all(); migrations.run()
    now = datetime.utcnow()
    pa = Tenant(name='Zulu', slug='zulu', status='active', paid_until=now + timedelta(days=20))      # SafeNet Pay
    ob = Tenant(name='Own', slug='own', status='active', payment_mode='own', own_provider='clickpesa', clickpesa_client_id='own-id',
                clickpesa_api_key_enc=secretbox.encrypt('own-key'), paid_until=now + timedelta(days=3))
    db.session.add_all([pa, ob]); db.session.flush()
    for t, key in ((pa, 'sgw_zulu'), (ob, 'sgw_own')):
        db.session.add(Package(tenant_id=t.id, name='Day', price=Decimal(1000), validity_minutes=1440))
        db.session.add(Gateway(tenant_id=t.id, name='gw', key_prefix=key[:8], key_hash=_hash_key(key)))
        a = Admin(username=f'owner_{t.slug}', email=f'{t.slug}@x.tz', tenant_id=t.id, role='owner', email_verified_at=now)
        a.set_password('password1'); db.session.add(a)
    db.session.commit()
    PA, OB = pa.id, ob.id
    pkg = {t: Package.query.filter_by(tenant_id=t).one().id for t in (PA, OB)}
    PLAN = BillingPlan.query.filter_by(is_active=True).order_by(BillingPlan.price).first()

api = app.test_client()
def buy(key, tid, phone, **extra):
    r = api.post('/api/portal/purchase', headers={'X-SafeNet-Key': key}, json={'package_id': pkg[tid], 'phone': phone, **extra})
    j = r.get_json()
    if r.status_code != 200:
        return j
    return api.get(f"/api/portal/purchase/{j['reference']}", headers={'X-SafeNet-Key': key}).get_json()
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c

# --- SafeNet Pay tenant: 1 SMS per paying guest, taken from the balance
assert buy('sgw_zulu', PA, '0684000001')['status'] == 'paid'
with app.app_context():
    ch = SmsCharge.query.filter_by(tenant_id=PA).one()
    assert ch.amount == 30 and ch.parts == 1 and ch.method == 'balance' and ch.kind == 'voucher' and ch.phone == '255684000001'
    assert tenant_balance(PA)[0] == Decimal('970') - Decimal('30')            # 1000 - 3 % fee - one SMS
assert len(sent) == 1 and len(sent[0][1]) <= 160, sent                       # the usual message fits in one SMS
# buy for a friend: 2 SMS
assert buy('sgw_zulu', PA, '0684000002', gift_phone='0712000002')['status'] == 'paid'
with app.app_context():
    kinds = sorted(c.kind for c in SmsCharge.query.filter_by(tenant_id=PA))
    assert kinds == ['gift', 'receipt', 'voucher'] and tenant_balance(PA)[0] == Decimal('1940') - Decimal('90')
co = login('owner_zulu')
e = html.unescape(co.get('/earnings').text)
assert 'Voucher SMS cost TZS 30 each' in e and 'taken from your balance' in e and 'This month: 3 SMS, TZS 90' in e and 'less TZS 90 for SMS' in e
s = html.unescape(co.get('/settings/payments').text)
assert 'Each SMS costs TZS 30' in s and 'checked' in s[s.find('id="sms_to_guests"') - 200:s.find('id="sms_to_guests"') + 100]
assert 'TZS 30 per SMS, paid by you' in html.unescape(co.get('/settings/portal').text)

# --- switched off: no SMS, no charge, no "buy for a friend"
co.post('/settings/payments', data={'csrf_token': tok(s), 'payment_mode': 'platform', 'own_provider': 'clickpesa'})
with app.app_context(): assert db.session.get(Tenant, PA).sms_to_guests is False
n = len(sent)
assert buy('sgw_zulu', PA, '0684000003')['status'] == 'paid'
assert len(sent) == n
with app.app_context(): assert SmsCharge.query.filter_by(tenant_id=PA).count() == 3
assert "isn't available" in buy('sgw_zulu', PA, '0684000004', gift_phone='0712000004')['error']
p = html.unescape(co.get('/portal?t=zulu&preview=1&view=buy').text)
assert 'Buy for a friend' not in p and 'your code is shown here' in p
assert 'SMS to guests is off' in html.unescape(co.get('/settings/portal').text)
cfg = api.get('/api/gateway/config', headers={'X-SafeNet-Key': 'sgw_zulu'}).get_json()['portal']
assert cfg['sms'] is False                                                       # the gateway box hides it too

# --- own-account tenant: SMS go on the next SafeNet bill
state['collected'] = '1000'
assert buy('sgw_own', OB, '0684000005')['status'] == 'paid'
with app.app_context():
    ch = SmsCharge.query.filter_by(tenant_id=OB).one(); assert ch.method == 'bill' and ch.subscription_payment_id is None
    assert tenant_balance(OB)[0] == 0                                            # nothing taken from a balance
cb = login('owner_own')
b = html.unescape(cb.get('/billing').text)
assert '1 voucher SMS sent to your guests' in b and '30' in b
e = html.unescape(cb.get('/earnings').text); assert 'added to your monthly SafeNet bill' in e
# a bill that fails gives the SMS back to the next one
state['status'] = 'FAILED'
r = cb.post('/billing/pay', data={'csrf_token': tok(b), 'plan_id': PLAN.id, 'months': 1, 'phone': '0684000005'})
with app.app_context():
    sp = SubscriptionPayment.query.filter_by(tenant_id=OB).one()
    assert sp.amount == PLAN.amount_for(1) + 30 and sp.sms_amount == 30
    assert SmsCharge.query.filter_by(tenant_id=OB).one().subscription_payment_id == sp.id
    ref = sp.reference
cb.get(f'/billing/payments/{ref}/status')
with app.app_context():
    assert db.session.get(SubscriptionPayment, sp.id).status == 'failed'
    assert SmsCharge.query.filter_by(tenant_id=OB).one().subscription_payment_id is None
# paid: the SMS stay on that bill and aren't charged again
state.update(status='SUCCESS', collected=str(int(PLAN.amount_for(1) + 30)))
cb.post('/billing/pay', data={'csrf_token': tok(b), 'plan_id': PLAN.id, 'months': 1, 'phone': '0684000005'})
with app.app_context():
    sp2 = SubscriptionPayment.query.filter_by(tenant_id=OB).order_by(SubscriptionPayment.id.desc()).first(); ref2 = sp2.reference
cb.get(f'/billing/payments/{ref2}/status')
with app.app_context():
    assert db.session.get(SubscriptionPayment, sp2.id).status == 'paid'
    assert SmsCharge.query.filter_by(tenant_id=OB).one().subscription_payment_id == sp2.id
b = html.unescape(cb.get('/billing').text)
assert 'voucher SMS sent to your guests' not in b and 'incl. 30 SMS' in b

# --- told up front
assert '30 TZS per SMS' in app.test_client().get('/').text
assert 'Each SMS costs TZS 30' in html.unescape(app.test_client().get('/docs/selling').text)
print('SMS CHARGES OK')
