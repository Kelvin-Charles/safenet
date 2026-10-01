"""Provider errors never show keys, tokens or account IDs (ClickPesa echoed its client id in a payout error)."""
import os, re, sys
CID = 'ID1y5EcPESL9cDfaSXu1saR0aFnuZKsC'
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID=CID, CLICKPESA_API_KEY='SKtestKey0987654321abc')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import safetext, clickpesa, snippe

payout = f'400: Application {CID} has no access to PAYOUT API. Enable it on your application.'
e = str(clickpesa.ClickPesaError(payout))
assert CID not in e and "enable the Payout API" in e and e.startswith('400: '), e
for raw, gone in ((f'401: bad client {CID}', CID),                                  # configured secrets, wherever they appear
                  ('401: api-key SKtestKey0987654321abc rejected', 'SKtestKey0987654321abc'),
                  ('403: key snp_bae92103479f6f89d64511db647d1cb84be26b578d22c8 lacks scope', 'snp_bae92103'),
                  ('401: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig expired', 'eyJhbGci'),
                  ('400: client_id=AbCdEf1234567890XyZ invalid', 'AbCdEf1234567890XyZ'),
                  ('400: merchant 7f3c9a1b2d4e5f60718293a4b5c6d7e8 unknown', '7f3c9a1b2d4e5f60718293a4b5c6d7e8')):
    for err in (clickpesa.ClickPesaError(raw), snippe.SnippeError(raw)):
        assert gone not in str(err) and '[hidden]' in str(err), (raw, str(err))
# useful details stay
for keep in ('400: Insufficient balance: available balance is 4520 TZS',
             '400: Payout request is already in progress, please retry after 42 seconds',
             '409: Order reference WD12XA1B2C3 already used: Create a different reference',
             '422: Phone number 255712345678 is not registered for mobile money'):
    assert str(clickpesa.ClickPesaError(keep)) == keep, str(clickpesa.ClickPesaError(keep))

# end to end: a payout error on the Payouts page and an old saved one
from datetime import datetime
from decimal import Decimal
from app import app, db
import migrations
from models import Admin, Tenant, Withdrawal, Payment
from sqlalchemy import text
app.config.update(TESTING=True)
def boom(*a, **k): raise clickpesa.ClickPesaError(payout)
clickpesa.lipa_namba_providers = lambda creds=None: [('Vodacom M-Pesa', '503')]
clickpesa.preview_payout = lambda *a, **k: {'fee': 0, 'amount': 5000, 'balance': 9000, 'receiver': {'accountName': 'X'}}
clickpesa.create_payout = boom
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    a = Admin(username='boss', email='b@x.tz', tenant_id=1, role='owner', is_superadmin=True, email_verified_at=datetime.utcnow()); a.set_password('password1')
    db.session.add(a)
    db.session.add(Payment(tenant_id=1, reference='SNP1', package_name='Day', validity_minutes=1440, phone='255684000111', amount=Decimal(9000),
                           net_amount=Decimal(9000), fee_amount=0, status='paid', paid_at=datetime.utcnow(), provider_account='platform'))
    w = Withdrawal(tenant_id=1, amount=Decimal(5000), phone='255615898768', method='lipa', lipa_namba='36252113', lipa_network='Vodacom M-Pesa')
    db.session.add(w); db.session.commit(); WID = w.id
    db.session.execute(text("INSERT INTO withdrawals (tenant_id, amount, phone, status, method, payout_error, created_at) "
                            f"VALUES (1, 100, '255', 'rejected', 'mobile', 'ClickPesa: {payout}', :now)"), {'now': datetime.utcnow()})
    db.session.commit()
    migrations.run()
    assert all(CID not in (v or '') for (v,) in db.session.execute(text('SELECT payout_error FROM withdrawals')))
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'boss', 'password': 'password1', 'csrf_token': tok(r.text)})
s = c.get(f'/platform/payouts/{WID}/send').text
page = c.post(f'/platform/payouts/{WID}/send', data={'csrf_token': tok(s), 'via': 'clickpesa', 'provider': '503'}, follow_redirects=True).text
assert CID not in page and "enable the Payout API" in page, page[:3000]
assert CID not in c.get('/platform/payouts?status=').text
print('SAFETEXT OK')
