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
assert cs.get(f'/platform/payouts/{BANK}/send', follow_redirects=True).text.count('Pay it by hand') == 1

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

# --- Snippe: the platform admin pastes the key in Platform: Billing; mobile money and banks then go through Snippe
import hashlib, hmac, json, time, snippe
from models import PlatformSetting
GOOD = 'snp_' + 'a' * 40
snp = {'calls': [], 'status': 'pending'}
def fake_test(creds):
    if creds.api_key != GOOD: raise snippe.SnippeError('401: Invalid API key')
snippe.test_credentials = fake_test
snippe.payout_fee = lambda amount, creds: {'fee_amount': 1500, 'total_amount': int(amount) + 1500}
snippe.balance = lambda creds: {'available': {'value': 90000, 'currency': 'TZS'}}
def snp_create(amount, ref, creds, name, phone=None, bank=None, account=None, narration='', webhook_url=None):
    snp['calls'].append(dict(ref=ref, key=creds.api_key, name=name, phone=phone, bank=bank, account=account, webhook=webhook_url))
    return {'reference': f'snp-ref-{len(snp["calls"])}', 'status': 'pending', 'fees': {'value': 1500}}
snippe.create_payout = snp_create
snippe.get_payout = lambda ref, creds: {'reference': ref, 'status': snp['status'], 'failure_reason': 'Wallet not found'}
b = html.unescape(cs.get('/platform/billing').text)
assert 'Snippe keys for SafeNet Pay' in b and 'No key yet' in b
assert 'rejected the key' in html.unescape(cs.post('/platform/billing/snippe', data={'csrf_token': tok(b), 'api_key': 'snp_' + 'b' * 40, 'use': '1'},
                                                   follow_redirects=True).text)
assert 'look like a Snippe API key' in cs.post('/platform/billing/snippe', data={'csrf_token': tok(b), 'api_key': 'hello'}, follow_redirects=True).text
r = html.unescape(cs.post('/platform/billing/snippe', data={'csrf_token': tok(b), 'api_key': GOOD, 'webhook_key': 'whk-secret', 'use': '1'},
                          follow_redirects=True).text)
assert 'Snippe accepted the key' in r and 'Key saved here' in r and 'Webhook key set' in r
with app.app_context():
    row = db.session.get(PlatformSetting, 'snippe_api_key'); assert row.value and GOOD not in row.value     # stored encrypted
    assert appmod.platform_provider() == 'snippe' and appmod._platform_account().creds.api_key == GOOD

e = co.get('/earnings').text
for d in (dict(method='mobile', phone='0754000111', account_name='Asha Juma'),
          dict(method='bank', bank_name='NMB', bank_account='2041000111', account_name='Zulu Connect Ltd'),
          dict(method='lipa', lipa_namba='55667788', lipa_network='Airtel Money')):
    assert 'requested' in html.unescape(co.post('/earnings/withdraw', data={'csrf_token': tok(e), 'amount': 5000, **{'phone': '0684000001', **d}},
                                                follow_redirects=True).text), d
with app.app_context():
    SM, SB, SL = [x.id for x in Withdrawal.query.filter_by(status='requested').order_by(Withdrawal.id)]
p = cs.get('/platform/payouts').text
assert re.search(rf'payouts/{SM}/send\?via=snippe".*?Send with Snippe.*?payouts/{SM}/send\?via=clickpesa', p, re.S)   # Snippe first
assert f'payouts/{SL}/send?via=clickpesa' in p and f'payouts/{SL}/send?via=snippe' not in p                    # Lipa Namba: ClickPesa only
assert f'payouts/{SB}/send?via=snippe' in p and f'payouts/{SB}/send?via=clickpesa' not in p                    # bank: Snippe only
# mobile money through Snippe
s = html.unescape(cs.get(f'/platform/payouts/{SM}/send').text)
assert 'Pay Zulu Connect with Snippe' in s and 'TZS 1,500' in s and '90,000' in s and 'Asha Juma' in s
cs.post(f'/platform/payouts/{SM}/send', data={'csrf_token': tok(s), 'via': 'snippe'})
c1 = snp['calls'][-1]
assert c1['key'] == GOOD and c1['phone'] == '255754000111' and c1['name'] == 'Asha Juma' and c1['bank'] is None
assert c1['webhook'].endswith('/webhooks/snippe') and re.fullmatch(r'WD\d+X[0-9A-F]{6}', c1['ref'])
with app.app_context():
    x = db.session.get(Withdrawal, SM); assert x.status == 'sending' and x.payout_provider == 'snippe' and x.payout_id == 'snp-ref-1' and x.payout_fee == 1500
# Snippe's webhook (signed) settles it
snp['status'] = 'completed'
raw = json.dumps({'type': 'payout.completed', 'data': {'reference': 'snp-ref-1', 'status': 'completed'}})
ts = str(int(time.time()))
sig = hmac.new(b'whk-secret', f'{ts}.{raw}'.encode(), hashlib.sha256).hexdigest()
assert app.test_client().post('/webhooks/snippe', data=raw, content_type='application/json',
                              headers={'X-Webhook-Timestamp': ts, 'X-Webhook-Signature': 'bad'}).status_code == 401
app.test_client().post('/webhooks/snippe', data=raw, content_type='application/json', headers={'X-Webhook-Timestamp': ts, 'X-Webhook-Signature': sig})
with app.app_context():
    x = db.session.get(Withdrawal, SM); assert x.status == 'paid' and x.reference == 'snp-ref-1'
# bank through Snippe; it fails and goes back to the queue with Snippe's reason
snp['status'] = 'pending'
s = html.unescape(cs.get(f'/platform/payouts/{SB}/send').text)
assert 'value="NMB" selected' in s and 'Zulu Connect Ltd' in s
cs.post(f'/platform/payouts/{SB}/send', data={'csrf_token': tok(s), 'via': 'snippe', 'bank': 'NMB'})
assert snp['calls'][-1]['bank'] == 'NMB' and snp['calls'][-1]['account'] == '2041000111' and snp['calls'][-1]['phone'] is None
snp['status'] = 'failed'
r = html.unescape(cs.post(f'/platform/payouts/{SB}/check', data={'csrf_token': tok(s)}, follow_redirects=True).text)
assert 'did not go through' in r and 'Snippe: payout Wallet not found' in r
with app.app_context():
    x = db.session.get(Withdrawal, SB); assert x.status == 'requested' and x.payout_id is None and x.payout_ref is None
# Lipa Namba can't go through Snippe
assert 'Pay it by hand' in cs.get(f'/platform/payouts/{SL}/send?via=snippe', follow_redirects=True).text or \
       'No payout service' in cs.get(f'/platform/payouts/{SL}/send?via=snippe', follow_redirects=True).text
assert 'Pay Zulu Connect with ClickPesa' in html.unescape(cs.get(f'/platform/payouts/{SL}/send').text)
print('PAYOUTS OK')
