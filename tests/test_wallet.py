"""A business deposits money by mobile money for SMS: credited once, fee on top, not withdrawable, spent before sales."""
import hashlib, hmac, html, json, os, re, sys, time
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PAYMENT_PROVIDER='snippe', SNIPPE_API_KEY='snp_platform', SNIPPE_FEE_PERCENT='2.5', SNIPPE_WEBHOOK_KEY='whk')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import snippe
pushes, state = [], {}
def create_payment(amount, phone, ref, creds, webhook_url=None, customer=None):
    pushes.append((amount, phone, ref)); state[ref] = 'pending'
    return {'reference': 'snp-' + ref, 'status': 'pending'}
amounts = {}
snippe.create_payment = create_payment
snippe.get_payment = lambda sid, creds: {'reference': sid, 'status': state[sid[4:]],
                                         'amount': {'value': amounts.get(sid[4:]) or next(p[0] for p in pushes if p[2] == sid[4:])}}
snippe.payout_fee = lambda amount, creds: {'fee_amount': 1500}
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
appmod.send_mail = lambda *a, **k: True
appmod._push_async = lambda *a, **k: None
from app import app, db, tenant_balance, unspent_deposits, withdrawable
import migrations
from models import Admin, Tenant, Payment, SmsCharge, WalletDeposit, Notification, Withdrawal
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    for slug, mode in (('kp', 'platform'), ('zz', 'platform'), ('own', 'own')):
        t = Tenant(name=slug, slug=slug, status='trial', trial_ends_at=now + timedelta(days=9), phone='0684000111', payment_mode=mode); db.session.add(t); db.session.flush()
        if slug == 'kp': T = t.id
        for role in ('owner', 'staff'):
            a = Admin(username=f'{slug}{role}', email=f'{slug}{role}@x.tz', tenant_id=t.id, role=role, email_verified_at=now)
            a.set_password('password1'); db.session.add(a)
    db.session.add(Payment(tenant_id=T, reference='SNX1', package_name='Day', validity_minutes=1440, phone='255700000001', amount=Decimal(7000),
                           fee_amount=0, net_amount=Decimal(7000), currency='TZS', provider='snippe', provider_account='platform', status='paid', paid_at=now))
    db.session.commit()
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
c = login('kpowner')
page = c.get('/wallet?amount=500').text
assert 'value="1000"' in page                                    # a small shortfall: the least that can be deposited
dep = lambda cl=c, **d: html.unescape(cl.post('/wallet/deposit', data={'csrf_token': tok(page), 'phone': '0684000111', **d}, follow_redirects=True).text)
for bad in ('', '-5', 'abc', '999', '1000001', 'nan'):
    assert 'Enter an amount from 1,000 to 1,000,000' in dep(amount=bad), bad
assert 'valid mobile money number' in dep(amount='5000', phone='12')
assert pushes == []
r = dep(amount='5,000')
assert '5,129' in r and pushes[0][:2] == (Decimal(5129), '255684000111')       # 2.5% on top
REF = pushes[0][2]
with app.app_context():
    assert tenant_balance(T)[0] == 7000                          # nothing until it is paid
# the webhook settles it (signed), once
state[REF] = 'completed'
raw = json.dumps({'type': 'payment.completed', 'data': {'reference': 'snp-' + REF, 'status': 'completed'}}); ts = str(int(time.time()))
hook = lambda sig: app.test_client().post('/webhooks/snippe', data=raw, content_type='application/json',
                                         headers={'X-Webhook-Timestamp': ts, 'X-Webhook-Signature': sig}).status_code
assert hook('bad') == 401
good = hmac.new(b'whk', f'{ts}.{raw}'.encode(), hashlib.sha256).hexdigest()
assert hook(good) == 200 and hook(good) == 200
with app.app_context():
    assert tenant_balance(T)[0] == 12000 and unspent_deposits(T) == 5000 and withdrawable(T) == 7000
    assert Notification.query.filter(Notification.title == 'Deposit received: TZS 5,000').count() == 1
    assert appmod._platform_profit()['earned'] == 0              # a deposit isn't SafeNet's earnings
assert c.get(f'/wallet/payments/{REF}/status').get_json() == {'status': 'paid', 'message': '', 'balance': 'TZS 12,000'}
assert REF in c.get('/wallet').text
# deposits can't be withdrawn: 7,000 of sales less the 1,500 fee
e = html.unescape(c.get('/earnings').text)
assert '+ 5,000 deposited' in e
r = html.unescape(c.post('/earnings/withdraw', data={'csrf_token': tok(e), 'password': 'password1', 'amount': 6000, 'phone': '0684000111', 'method': 'mobile'}, follow_redirects=True).text)
assert 'withdraw up to TZS 5,500' in r
# SMS uses the deposit first, then sales
def sms(n):
    with app.app_context():
        db.session.add(SmsCharge(tenant_id=T, phone='255700000001', kind='offer', amount=Decimal(n), method='balance')); db.session.commit()
        return tenant_balance(T)[0], unspent_deposits(T), withdrawable(T)
assert sms(2000) == (10000, 3000, 7000)
assert sms(4000) == (6000, 0, 6000)
# failed, short, and one settled by the sync after a closed page
dep(amount='2000'); state[pushes[-1][2]] = 'failed'
dep(amount='3000'); amounts[pushes[-1][2]] = Decimal(1000); state[pushes[-1][2]] = 'completed'
dep(amount='4000'); state[pushes[-1][2]] = 'completed'
with app.app_context():
    appmod._payments_sync_due()
    assert [d.status for d in WalletDeposit.query.order_by(WalletDeposit.id)] == ['paid', 'failed', 'review', 'paid']
    assert tenant_balance(T)[0] == 10000
# only its own business's managers; not for own-account businesses
assert login('zzowner').get(f'/wallet/payments/{REF}/status').status_code == 404
s = login('kpstaff'); assert 'Deposit money' not in s.get('/wallet', follow_redirects=True).text
o = login('ownowner'); assert 'do not need to deposit' in html.unescape(o.get('/wallet', follow_redirects=True).text)
assert '/wallet' in c.get('/offers/sms').text
print('WALLET OK')
