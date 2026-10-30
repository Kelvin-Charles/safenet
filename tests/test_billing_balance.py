"""A business pays its SafeNet plan from its SafeNet Pay balance: all of it when the balance is enough, otherwise the
balance first and a PIN prompt for the rest. What's being paid is held from the balance; a failed prompt gives it back."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PAYMENT_PROVIDER='snippe', SNIPPE_API_KEY='snp_platform', SNIPPE_FEE_PERCENT='2.5')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import snippe
pushes, state = [], {}
def create_payment(amount, phone, ref, creds, webhook_url=None, customer=None):
    pushes.append((amount, phone)); state[ref] = 'pending'
    return {'reference': 'snp-' + ref, 'status': 'pending'}
snippe.create_payment = create_payment
snippe.get_payment = lambda sid, creds: {'reference': sid, 'status': state[sid[4:]], 'amount': {'value': pushes[-1][0]}}
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
appmod.send_mail = lambda *a, **k: True
from app import app, db, tenant_balance
import migrations
from models import Admin, Tenant, Payment, BillingPlan, SubscriptionPayment
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    plan = BillingPlan(name='Business', price=Decimal(15000), sort_order=1); db.session.add(plan)
    t = Tenant(name='USMART', slug='usmart', status='trial', trial_ends_at=now, phone='0684000111', payment_mode='platform'); db.session.add(t); db.session.flush()
    TID, PID = t.id, plan.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    db.session.add(Payment(tenant_id=TID, reference='SNX1', package_name='Day', validity_minutes=1440, phone='255700000001',
                           amount=Decimal(20000), fee_amount=Decimal(600), net_amount=Decimal(19400), currency='TZS',
                           provider='snippe', provider_account='platform', status='paid', paid_at=now))
    db.session.commit()
    assert tenant_balance(TID)[0] == 19400

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
page = html.unescape(c.get('/billing').text)
assert 'Use my balance: TZS 19,400' in page
pay = lambda **d: html.unescape(c.post('/billing/pay', data={'csrf_token': tok(page), 'plan_id': PID, 'months': 1, **d}, follow_redirects=True).text)
# enough balance: paid at once, no PIN prompt, no phone needed
r = pay(use_balance='1', phone='')
assert 'Paid TZS 15,000 from your balance' in r and pushes == []
with app.app_context():
    sp = SubscriptionPayment.query.one()
    assert sp.status == 'paid' and sp.method == 'balance' and sp.balance_amount == 15000 and sp.period_end
    assert tenant_balance(TID)[0] == 4400
    assert appmod._platform_profit()['subs'] == 15000 and appmod._platform_profit()['subs_fees'] == 0
# not enough: the 4,400 left pays first, a PIN prompt for the other 10,600
r = pay(use_balance='1', phone='0684000111')
assert pushes == [(Decimal(10600), '255684000111')], pushes
assert '10,600' in r                                           # the PIN page shows what is asked
with app.app_context():
    sp = SubscriptionPayment.query.filter_by(status='pending').one(); REF = sp.reference
    assert sp.balance_amount == 4400 and sp.amount == 15000 and sp.pushed == 10600
    assert tenant_balance(TID)[0] == 0                        # held while the prompt is open: can't be withdrawn twice
state[REF] = 'completed'
with app.app_context():
    sp = appmod._refresh_subscription(REF, force=True)
    assert sp.status == 'paid'
    assert appmod._platform_profit()['subs_fees'] == 265      # Snippe's share only on the 10,600 it collected
# a prompt that fails gives the held balance back
with app.app_context():
    db.session.add(Payment(tenant_id=TID, reference='SNX2', package_name='Day', validity_minutes=1440, phone='255700000001',
                           amount=Decimal(5000), fee_amount=Decimal(150), net_amount=Decimal(4850), currency='TZS',
                           provider='snippe', provider_account='platform', status='paid', paid_at=now))
    db.session.commit()
pay(use_balance='1', phone='0684000111')
assert pushes[-1][0] == 10150
with app.app_context():
    REF2 = SubscriptionPayment.query.filter_by(status='pending').one().reference
    assert tenant_balance(TID)[0] == 0
state[REF2] = 'failed'
with app.app_context():
    appmod._refresh_subscription(REF2, force=True)
    assert tenant_balance(TID)[0] == 4850
# a tiny remainder is never asked by mobile money: at least 1,000 by prompt, the balance pays the rest
with app.app_context():
    db.session.add(Payment(tenant_id=TID, reference='SNX3', package_name='Day', validity_minutes=1440, phone='255700000001',
                           amount=Decimal(10000), fee_amount=Decimal(300), net_amount=Decimal(9850), currency='TZS',
                           provider='snippe', provider_account='platform', status='paid', paid_at=now))
    db.session.commit()
    assert tenant_balance(TID)[0] == 14700
pay(use_balance='1', phone='0684000111')
assert pushes[-1][0] == 1000
with app.app_context():
    assert SubscriptionPayment.query.filter_by(status='pending').one().balance_amount == 14000
# without ticking it, the whole price by PIN prompt as before
with app.app_context():
    SubscriptionPayment.query.filter_by(status='pending').update({'status': 'failed'}); db.session.commit()
pay(phone='0684000111')
assert pushes[-1][0] == 15000
# the balance part shows in Earnings
assert 'paid for your SafeNet plan' in html.unescape(c.get('/earnings').text)
print('BILLING BALANCE OK')
