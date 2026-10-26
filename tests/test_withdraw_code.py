"""Withdrawals without the platform admin: the owner's password, then a code by SMS to the business phone, then the
payout goes out. The business phone can only be changed with the platform admin's approval."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, SNIPPE_API_KEY='snp_platform', PAYMENT_PROVIDER='snippe')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import snippe
paid_out = []
snippe.create_payout = lambda amount, ref, creds, name, narration=None, webhook_url=None, **target: \
    paid_out.append((amount, target)) or {'reference': 'sp-1', 'status': 'pending', 'fees': {'value': 0}}
import app as appmod
texts, mails = [], []
appmod.sms_is_configured = lambda: True
appmod.send_sms_async = lambda phone, text, *a, **k: texts.append((phone, text))
appmod.send_mail = lambda to, subject, body, *a, **k: mails.append((to, subject))
from app import app, db
import migrations
from models import Admin, Tenant, Payment, Withdrawal
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu', slug='zulu', status='active', phone='0684 000 111'); db.session.add(t); db.session.flush(); TID = t.id
    for u, role, sa in (('owner', 'owner', False), ('boss', 'owner', True)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=None if sa else TID, role=role, is_superadmin=sa, email_verified_at=now)
        a.set_password('password1'); db.session.add(a)
    db.session.add(Payment(tenant_id=TID, reference='SNP1', package_name='Day', validity_minutes=1440, phone='255700000001',
                           amount=Decimal(20000), fee_amount=Decimal(600), net_amount=Decimal(19400), currency='TZS',
                           provider='snippe', provider_account='platform', status='paid', paid_at=now))
    db.session.commit()


def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c


co = login('owner')
e = co.get('/earnings').text
assert 'Your SafeNet password' in e
ask = lambda **d: html.unescape(co.post('/earnings/withdraw', data={'csrf_token': tok(e), 'amount': 10000, 'phone': '0684000222',
                                                                    'method': 'mobile', **d}, follow_redirects=True).text)
# the password first
assert 'Your password is not right' in ask(password='wrong')
with app.app_context():
    assert Withdrawal.query.count() == 0
# then a code by SMS to the business phone (not the payout number)
r = ask(password='password1')
assert 'Enter the code we sent' in r and '0684 ••• 111' in r
phone, sms = texts[-1]
assert phone == '255684000111' and 'TZS 10,000' in sms and 'Never share it' in sms
code = re.search(r'is (\d{6})\.', sms).group(1)
with app.app_context():
    w = Withdrawal.query.one(); WID = w.id
    assert w.status == 'verifying' and w.otp_hash and code not in (w.otp_hash or '')
    from app import tenant_balance
    assert tenant_balance(TID)[0] == Decimal(19400)                 # not taken from the balance until confirmed
page = co.get(f'/earnings/withdraw/{WID}/confirm').text
post = lambda **d: html.unescape(co.post(f'/earnings/withdraw/{WID}/confirm', data={'csrf_token': tok(page), **d}, follow_redirects=True).text)
assert 'That code is not right' in post(code='000000' if code != '000000' else '111111')
# a new code replaces the old one
post(action='resend')
old, code = code, re.search(r'is (\d{6})\.', texts[-1][1]).group(1)
if old != code:
    assert 'That code is not right' in post(code=old)
# the right code: the money goes out at once, no platform admin
r = post(code=code)
assert 'on its way to' in r and paid_out == [(Decimal(10000), {'phone': '255684000222'})]
with app.app_context():
    w = db.session.get(Withdrawal, WID)
    assert w.status == 'sending' and w.payout_provider == 'snippe' and w.otp_hash is None
    assert tenant_balance(TID)[0] == Decimal(9400)
assert co.get(f'/earnings/withdraw/{WID}/confirm').status_code == 302      # done: back to earnings
# expired code
r = ask(password='password1', amount=5000)
with app.app_context():
    w2 = Withdrawal.query.filter_by(status='verifying').one(); W2 = w2.id
    w2.otp_expires_at = datetime.utcnow() - timedelta(minutes=1); db.session.commit()
code = re.search(r'is (\d{6})\.', texts[-1][1]).group(1)
page = co.get(f'/earnings/withdraw/{W2}/confirm').text
assert 'expired' in html.unescape(co.post(f'/earnings/withdraw/{W2}/confirm', data={'csrf_token': tok(page), 'code': code},
                                          follow_redirects=True).text)
# more than the balance by the time the code is entered (another withdrawal went first): refused
assert 'Withdrawal cancelled' in html.unescape(co.post(f'/earnings/withdraw/{W2}/confirm', data={'csrf_token': tok(page), 'action': 'cancel'},
                                                       follow_redirects=True).text)

# Lipa Namba goes through ClickPesa only: off until the platform admin switches ClickPesa payouts on
assert 'Lipa Namba (merchant till)' not in html.unescape(co.get('/earnings').text)
assert "Lipa Namba isn't available" in ask(password='password1', amount=3000, method='lipa', lipa_namba='48001268', lipa_network='Vodacom M-Pesa', account_name='ACME')
with app.app_context():
    w_ = Withdrawal(tenant_id=TID, amount=Decimal(3000), phone='255684000222', method='mobile')
    assert appmod._payout_options(w_) == ['snippe']                  # mobile money: Snippe only while it's off
cb = login('boss')
pb = html.unescape(cb.get('/platform/billing').text)
assert 'ClickPesa payouts (Lipa Namba withdrawals)' in pb
cb.post('/platform/settings', data={'csrf_token': tok(pb), 'CLICKPESA_PAYOUTS': '1'})
assert appmod.Config.CLICKPESA_PAYOUTS == 1 and 'Lipa Namba (merchant till)' in html.unescape(co.get('/earnings').text)
cb.post('/platform/settings', data={'csrf_token': tok(pb), 'CLICKPESA_PAYOUTS': '0'})
assert appmod.Config.CLICKPESA_PAYOUTS == 0

# the business phone: a change waits for the platform admin, codes keep going to the old one
s = co.get('/settings').text
co.post('/settings', data={'csrf_token': tok(s), 'name': 'Zulu', 'phone': '0699 999 999', 'currency': 'TZS'})
with app.app_context():
    t = db.session.get(Tenant, TID)
    assert t.phone == '0684 000 111' and t.phone_pending == '0699 999 999'
assert any('Phone change request' in subject for _, subject in mails)
assert 'waiting for approval' in html.unescape(co.get('/settings').text)
# saving the settings again doesn't cancel it
s = co.get('/settings').text
co.post('/settings', data={'csrf_token': tok(s), 'name': 'Zulu Ltd', 'phone': '0684 000 111', 'currency': 'TZS'})
with app.app_context():
    assert db.session.get(Tenant, TID).phone_pending == '0699 999 999'
r = ask(password='password1', amount=5000)
assert texts[-1][0] == '255684000111'                               # still the approved phone
# the platform admin approves: both numbers are told
cb = login('boss')
p = html.unescape(cb.get('/platform/tenants').text)
assert 'Business phone changes to approve (1)' in p and '0699 999 999' in p
cb.post(f'/platform/tenants/{TID}/phone', data={'csrf_token': tok(p), 'action': 'approve'})
with app.app_context():
    t = db.session.get(Tenant, TID)
    assert t.phone == '0699 999 999' and t.phone_pending is None
assert {n for n, txt in texts[-2:]} == {'255684000111', '255699999999'}
print('WITHDRAW CODE OK')
