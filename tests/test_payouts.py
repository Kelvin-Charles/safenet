"""Withdrawals to a mobile number, Lipa Namba or bank, and payouts sent through SafeNet's ClickPesa account."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', CLICKPESA_CLIENT_ID='platform-id', CLICKPESA_API_KEY='platform-key', MIN_WITHDRAWAL='500',
                  SECRET_KEY='test-secret-key-long-enough')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
# request shapes from ClickPesa's docs (the calls below are faked)
cr = clickpesa.Credentials('id', 'key', '')
assert clickpesa._payout_path('create', '4800') == '/third-parties/payouts/create-lipa-namba-payout'
assert clickpesa._payout_path('preview', None) == '/third-parties/payouts/preview-mobile-money-payout'
assert clickpesa._payout_payload(Decimal('10000.00'), 'WD1XAB', cr, lipa_namba='48001268', provider_code='503') == \
    {'amount': 10000, 'currency': 'TZS', 'orderReference': 'WD1XAB', 'lipaNamba': '48001268', 'providerCode': '503'}
assert clickpesa._payout_payload(5000, 'WD2XAB', cr, phone='255712345678') == \
    {'amount': 5000, 'currency': 'TZS', 'orderReference': 'WD2XAB', 'phoneNumber': '255712345678'}
assert 'checksum' in clickpesa._payout_payload(5000, 'WD2XAB', clickpesa.Credentials('id', 'key', 'secret'), phone='255712345678')
calls = []
cp = {'status': 'AUTHORIZED', 'fail': None, 'query': 'AUTHORIZED'}
PROVIDERS = [('Vodacom M-Pesa', '503'), ('Mixx by Yas', '504'), ('CRDB Bank', '003')]
def fake_preview(amount, ref, phone=None, lipa_namba=None, provider_code=None, creds=None):
    calls.append(('preview', ref, phone, lipa_namba, provider_code))
    return {'amount': amount + 100, 'fee': 100, 'balance': 250000, 'channelProvider': 'Vodacom M-Pesa',
            'receiver': {'accountName': 'ACME TRADERS LTD' if lipa_namba else 'ASHA JUMA'}}
def fake_create(amount, ref, phone=None, lipa_namba=None, provider_code=None, creds=None):
    calls.append(('create', ref, phone, lipa_namba, provider_code))
    if cp['fail']: raise clickpesa.ClickPesaError(cp['fail'])
    return {'id': 'CPOUT1', 'status': cp['status'], 'fee': '100', 'orderReference': ref,
            'beneficiary': {'accountName': 'ACME TRADERS LTD' if lipa_namba else 'ASHA JUMA'}}
clickpesa.preview_payout = fake_preview
clickpesa.create_payout = fake_create
clickpesa.query_payout = lambda ref, creds=None: calls.append(('query', ref)) or {'id': 'CPOUT1', 'status': cp['query']}
clickpesa.lipa_namba_providers = lambda creds=None: PROVIDERS
outbox, sms = [], []
import app as appmod
appmod.send_mail = lambda to, subj, body: outbox.append((to, subj, body)) or True
appmod.send_sms_async = lambda to, text, ref=None: sms.append((to, text))
from app import app, db, tenant_balance, _lipa_provider_code
import migrations
from models import Admin, Tenant, Payment, Withdrawal
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu Connect', slug='zulu', status='active', phone='0684000001'); db.session.add(t); db.session.flush(); TID = t.id
    db.session.add(Payment(tenant_id=TID, reference='SNP1', package_name='Day', validity_minutes=1440, phone='255684000111', amount=Decimal(50000),
                           net_amount=Decimal(50000), fee_amount=0, status='paid', paid_at=now, provider_account='platform'))
    for u, tid, sa in (('owner', TID, False), ('boss', 1, True)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=tid, role='owner', is_superadmin=sa, email_verified_at=now); a.set_password('password1')
        db.session.add(a)
    db.session.commit()

def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
co, cs = login('owner'), login('boss')

# --- the tenant chooses where the money goes
e = co.get('/earnings').text
assert 'Lipa Namba (merchant till)' in e and 'Bank account' in e and 'Vodacom M-Pesa' in e
w = lambda **d: html.unescape(co.post('/earnings/withdraw', data={'csrf_token': tok(e), 'amount': 10000, 'phone': '0684000001', **d},
                                      follow_redirects=True).text)
assert 'Enter the Lipa Namba' in w(method='lipa', lipa_namba='')
assert 'Choose the network' in w(method='lipa', lipa_namba='48001268')
assert 'Enter the bank' in w(method='bank', bank_name='CRDB', bank_account='0150123')
assert 'requested' in w(method='lipa', lipa_namba='4800 1268', lipa_network='Vodacom M-Pesa', account_name='ACME')
assert 'requested' in w(method='bank', bank_name='CRDB', bank_account='0150123456', account_name='Zulu Connect Ltd')
assert 'requested' in w(method='mobile', phone='0712345678')
with app.app_context():
    lipa, bank, mob = Withdrawal.query.order_by(Withdrawal.id).all()
    assert lipa.method == 'lipa' and lipa.lipa_namba == '48001268' and lipa.destination == 'Lipa Namba 48001268 (Vodacom M-Pesa)'
    assert bank.destination == 'CRDB account 0150123456' and mob.destination == 'mobile money 255712345678'
    assert tenant_balance(TID)[0] == Decimal(20000)
    LIPA, BANK, MOB = lipa.id, bank.id, mob.id
assert any('Lipa Namba 48001268' in m[2] for m in outbox)                 # platform admin is emailed where to pay
e = co.get('/earnings').text
assert 'Lipa Namba 48001268 (Vodacom M-Pesa)' in e and 'CRDB account 0150123456' in e

# --- platform: provider matching
assert _lipa_provider_code(PROVIDERS, 'Vodacom M-Pesa') == '503' and _lipa_provider_code(PROVIDERS, 'Mixx by Yas') == '504'
assert _lipa_provider_code(PROVIDERS, 'Other') is None and _lipa_provider_code(PROVIDERS, 'Other', '003') == '003'

p = cs.get('/platform/payouts').text
assert len(re.findall(r'/platform/payouts/\d+/send', p)) == 2                               # not for the bank one
assert cs.get(f'/platform/payouts/{BANK}/send', follow_redirects=True).text.count('paid by hand') == 1

# Lipa Namba: preview shows the till's registered name, fee and balance, then send
s = cs.get(f'/platform/payouts/{LIPA}/send').text
assert 'ACME TRADERS LTD' in s and 'TZS 100' in s and '250,000' in s and 'value="503" selected' in s, s[-2500:]
prev = [c for c in calls if c[0] == 'preview'][-1]
assert prev[3] == '48001268' and prev[4] == '503' and re.fullmatch(r'WD\d+X[0-9A-F]{6}', prev[1])
r = cs.post(f'/platform/payouts/{LIPA}/send', data={'csrf_token': tok(s), 'provider': '503'}, follow_redirects=True).text
assert 'accepted by ClickPesa' in html.unescape(r)
create = [c for c in calls if c[0] == 'create'][-1]
assert create[1] == prev[1] and create[3] == '48001268' and create[4] == '503'                  # same reference as the preview
with app.app_context():
    x = db.session.get(Withdrawal, LIPA); assert x.status == 'sending' and x.payout_receiver == 'ACME TRADERS LTD' and x.payout_fee == 100
    assert tenant_balance(TID)[0] == Decimal(20000)                  # still counted as withdrawn
# can't be sent twice
assert 'already processed' in cs.post(f'/platform/payouts/{LIPA}/send', data={'csrf_token': tok(s)}, follow_redirects=True).text
# ClickPesa settles it: the payouts page picks it up and tells the tenant
cp['query'] = 'SUCCESS'
cs.get('/platform/payouts')
with app.app_context():
    x = db.session.get(Withdrawal, LIPA); assert x.status == 'paid' and x.reference == 'CPOUT1' and x.processed_at
assert any('Lipa Namba 48001268' in t and 'CPOUT1' in t for _, t in sms), sms
assert any('was sent' in b and 'Lipa Namba 48001268' in b for _, _, b in outbox)

# mobile number: ClickPesa rate limit shows clearly, then it fails later and goes back to the queue
cp.update(fail='400: Payout request is already in progress, please retry after 42 seconds')
s = cs.get(f'/platform/payouts/{MOB}/send').text
assert 'ASHA JUMA' in s
assert 'retry after 42 seconds' in cs.post(f'/platform/payouts/{MOB}/send', data={'csrf_token': tok(s)}, follow_redirects=True).text
with app.app_context(): assert db.session.get(Withdrawal, MOB).status == 'requested'
cp.update(fail=None, query='REVERSED')
s = cs.get(f'/platform/payouts/{MOB}/send').text
cs.post(f'/platform/payouts/{MOB}/send', data={'csrf_token': tok(s)})
with app.app_context(): assert db.session.get(Withdrawal, MOB).status == 'sending'
r = cs.post(f'/platform/payouts/{MOB}/check', data={'csrf_token': tok(s)}, follow_redirects=True).text
assert 'did not go through' in r
with app.app_context():
    x = db.session.get(Withdrawal, MOB); assert x.status == 'requested' and 'reversed' in x.payout_error and x.payout_ref is None
assert 'payout reversed' in cs.get('/platform/payouts').text
# webhook for a payout reference: re-checked with ClickPesa
cp.update(query='SUCCESS')
s = cs.get(f'/platform/payouts/{MOB}/send').text
cs.post(f'/platform/payouts/{MOB}/send', data={'csrf_token': tok(s)})
with app.app_context(): ref = db.session.get(Withdrawal, MOB).payout_ref
app.test_client().post('/api/clickpesa/webhook', json={'event': 'PAYOUT SUCCESS', 'data': {'orderReference': ref}})
with app.app_context(): assert db.session.get(Withdrawal, MOB).status == 'paid'

# bank: paid by hand as before
p = cs.get('/platform/payouts').text
cs.post(f'/platform/payouts/{BANK}', data={'csrf_token': tok(p), 'action': 'paid', 'reference': 'CRDB-778'})
with app.app_context():
    assert db.session.get(Withdrawal, BANK).status == 'paid'
    assert tenant_balance(TID)[0] == Decimal(20000)
# tenants can't send payouts
assert co.get(f'/platform/payouts/{BANK}/send').status_code == 404
print('PAYOUTS OK')
