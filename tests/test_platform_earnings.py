"""Platform: Earnings: the platform admin takes out SafeNet's own profit (its fee on guest payments, SMS charged to
balances, subscriptions, less Snippe's fees) through Snippe, with the password and a code sent to PLATFORM_PHONE.
Businesses' balances are never part of it."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PAYMENT_PROVIDER='snippe', SNIPPE_API_KEY='snp_platform',
                  SNIPPE_FEE_PERCENT='2.5', PLATFORM_PHONE='0755 111 222')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import snippe
sent, payouts = [], {}
def create_payout(amount, ref, creds, name, narration=None, webhook_url=None, **target):
    sent.append((amount, ref, target)); payouts['po-' + ref] = 'pending'
    return {'reference': 'po-' + ref, 'status': 'pending', 'fees': {'value': 500}}
snippe.create_payout = create_payout
snippe.get_payout = lambda sid, creds: {'status': payouts[sid]}
import app as appmod
texts, mails = [], []
appmod.sms_is_configured = lambda: True
appmod.send_sms_async = lambda phone, text, *a, **k: texts.append((phone, text))
appmod.send_mail = lambda to, subject, body, *a, **k: mails.append(subject)
from app import app, db, tenant_balance
import migrations
from models import Admin, Tenant, Payment, SubscriptionPayment, SmsCharge, Withdrawal, PlatformWithdrawal
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='boss', email='b@x.tz', role='owner', is_superadmin=True, email_verified_at=now); a.set_password('password1'); db.session.add(a)
    db.session.add(Payment(tenant_id=TID, reference='SN1', package_name='Day', validity_minutes=1440, phone='255712000001',
                           amount=Decimal(100000), customer_fee=Decimal(2565), currency='TZS', provider='snippe', provider_account='platform',
                           status='paid', fee_amount=Decimal(3000), net_amount=Decimal(97000), paid_at=now))
    db.session.add(SubscriptionPayment(tenant_id=TID, plan_name='Pro', months=1, amount=Decimal(20000), method='snippe', reference='SB1', status='paid'))
    db.session.add(SubscriptionPayment(tenant_id=TID, plan_name='Pro', months=1, amount=Decimal(20000), method='manual', reference='SB2', status='paid'))
    db.session.add(SmsCharge(tenant_id=TID, phone='255712000001', kind='voucher', amount=Decimal(1500), method='balance'))
    db.session.add(Withdrawal(tenant_id=TID, amount=Decimal(10000), phone='255712000002', status='paid', payout_provider='snippe', payout_fee=Decimal(400)))
    db.session.commit()
    p = appmod._platform_profit()
    # 3,000 fee + 1,500 SMS + 20,000 subscription (online only) - 500 Snippe's share of it - 400 payout fee
    assert (p['fees'], p['sms'], p['subs'], p['subs_fees'], p['payout_fees']) == (3000, 1500, 20000, 500, 400), p
    assert p['earned'] == p['available'] == 23600
    owed_before = tenant_balance(TID)[0]

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'boss', 'password': 'password1', 'csrf_token': tok(r.text)})
page = html.unescape(c.get('/platform/earnings').text)
assert 'Available to take out' in page and '23,600' in page and '0755 ••• 222' in page
post = lambda **d: html.unescape(c.post('/platform/earnings/withdraw', data={'csrf_token': tok(page), 'method': 'mobile', 'phone': '0712 999 888',
                                                                            'password': 'password1', **d}, follow_redirects=True).text)
assert 'password is not right' in post(amount=5000, password='nope')
assert 'You can take up to TZS 23,600' in post(amount=30000)        # never more than SafeNet's own earnings
r = post(amount=20000)
assert 'platform phone 0755 ••• 222' in r
phone, sms = texts[-1]
assert phone == '255755111222' and 'TZS 20,000' in sms
code = re.search(r'is (\d{6})\.', sms).group(1)
with app.app_context():
    pw = PlatformWithdrawal.query.one(); PID = pw.id
    assert pw.status == 'verifying' and appmod._platform_profit()['available'] == 23600       # nothing taken before the code
assert any('SafeNet earnings withdrawal' in m for m in mails)
cp = c.get(f'/platform/earnings/{PID}/confirm').text
confirm = lambda **d: html.unescape(c.post(f'/platform/earnings/{PID}/confirm', data={'csrf_token': tok(cp), **d}, follow_redirects=True).text)
assert 'That code is not right' in confirm(code='000000' if code != '000000' else '111111') and sent == []
r = confirm(code=code)
assert 'on its way' in r and sent[0][0] == Decimal(20000) and sent[0][2] == {'phone': '255712999888'} and sent[0][1].startswith(f'PW{PID}X')
with app.app_context():
    pw = db.session.get(PlatformWithdrawal, PID)
    assert pw.status == 'sending' and pw.payout_fee == 500
    assert appmod._platform_profit()['available'] == 23600 - 20500
    assert tenant_balance(TID)[0] == owed_before                    # the business's balance isn't touched
# Snippe finishes it
payouts['po-' + sent[0][1]] = 'completed'
page = html.unescape(c.get('/platform/earnings').text)
with app.app_context():
    assert db.session.get(PlatformWithdrawal, PID).status == 'paid'
# a failed payout gives the money back to "available"
with app.app_context():
    db.session.add(PlatformWithdrawal(amount=Decimal(1000), method='mobile', phone='255712999888', status='sending', payout_id='po-x'))
    db.session.commit()
payouts['po-x'] = 'failed'
c.get('/platform/earnings')
with app.app_context():
    assert PlatformWithdrawal.query.filter_by(payout_id='po-x').one().status == 'failed'
    assert appmod._platform_profit()['available'] == 3100
# without PLATFORM_PHONE it can't be done at all
appmod.Config.PLATFORM_PHONE = ''
assert 'PLATFORM_PHONE' in html.unescape(c.get('/platform/earnings').text)
assert 'PLATFORM_PHONE' in post(amount=1000)
print('PLATFORM EARNINGS OK')
