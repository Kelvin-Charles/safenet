"""Platform: Reconcile: SafeNet's transactions at Snippe against SafeNet's records. The Snippe account is shared with
other projects: only SafeNet's references count. A payment Snippe completed but SafeNet missed can be fixed."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PAYMENT_PROVIDER='snippe', SNIPPE_API_KEY='snp_platform')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import snippe
now = datetime.utcnow()
iso = lambda d: d.strftime('%Y-%m-%dT%H:%M:%S.000000Z')
money = lambda v: {'currency': 'TZS', 'value': v}
pay = lambda ref, gross, fee, status='completed', when=now: {
    'reference': 'snp-' + ref, 'status': status, 'created_at': iso(when), 'metadata': {'order_reference': ref} if ref else {},
    'amount': money(gross), 'settlement': {'gross': money(gross), 'fees': money(fee), 'net': money(gross - fee)}}
PAYS = [pay('SNAAAAAAAAAAA1', 1025, 25), pay('SNAAAAAAAAAAA2', 2050, 50), pay('SBAAAAAAAAAAA1', 10000, 250),
        pay('SNAAAAAAAAAAA3', 1025, 25),                       # Snippe completed it, SafeNet has it failed
        pay('ORDER-77', 50000, 1250), pay('', 9000, 200),      # other projects on the same account
        pay('SNAAAAAAAAAAA4', 1025, 25, 'failed')]
OUTS = [{'reference': 'po-1', 'status': 'completed', 'created_at': iso(now), 'metadata': {'order_reference': 'WD1XAAAAAA'},
         'amount': money(1500), 'fees': money(500), 'total': money(2000)},
        {'reference': 'po-x', 'status': 'completed', 'created_at': iso(now), 'metadata': {'payroll': 'P1'},
         'amount': money(300000), 'fees': money(1500), 'total': money(301500)}]
snippe.list_payments = lambda creds, since=None, pages=25: (PAYS, True)
snippe.list_payouts = lambda creds, since=None, pages=25: (OUTS, True)
snippe.balance = lambda creds: {'balance': money(500000)}
snippe.get_payment = lambda sid, creds: next((p for p in PAYS if p['reference'] == sid), None)
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
from app import app, db
import migrations
from models import Admin, Tenant, Payment, SubscriptionPayment, Withdrawal
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='boss', email='b@x.tz', role='owner', is_superadmin=True, email_verified_at=now); a.set_password('password1'); db.session.add(a)
    for ref, status, price in (('SNAAAAAAAAAAA1', 'paid', 1000), ('SNAAAAAAAAAAA2', 'paid', 2000), ('SNAAAAAAAAAAA3', 'failed', 1000),
                               ('SNAAAAAAAAAAA4', 'paid', 1000)):
        db.session.add(Payment(tenant_id=TID, reference=ref, package_name='Day', validity_minutes=1440, phone='255712000001',
                               amount=Decimal(price), customer_fee=Decimal(price) * Decimal('0.025'), currency='TZS', provider='snippe',
                               provider_account='platform', status=status, provider_id='snp-' + ref, created_at=now - timedelta(hours=2),
                               fee_amount=Decimal(30), net_amount=Decimal(price - 30), paid_at=now if status == 'paid' else None))
    db.session.add(SubscriptionPayment(tenant_id=TID, plan_name='Pro', months=1, amount=Decimal(10000), method='snippe',
                                       reference='SBAAAAAAAAAAA1', status='paid', created_at=now - timedelta(hours=2)))
    db.session.add(Withdrawal(tenant_id=TID, amount=Decimal(1500), phone='255712000002', status='paid', payout_ref='WD1XAAAAAA',
                              payout_provider='snippe', payout_fee=Decimal(500), created_at=now - timedelta(hours=2)))
    db.session.commit()

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'boss', 'password': 'password1', 'csrf_token': tok(r.text)})
page = html.unescape(c.get('/platform/reconcile?period=30').text)
assert 'Platform: Reconcile' in page
with app.app_context():
    rep = appmod._reconcile_snippe(30)
s, o = rep['snippe'], rep['ours']
# only SafeNet's: guest payments 1, 2, 3 (completed), the subscription and the payout; other projects left out
assert (s['guest_n'], s['guest'], s['sub'], s['fees'], s['out'], s['out_total']) == (3, 4100, 10000, 350, 1500, 2000), s
assert rep['in_snippe'] == 4100 + 10000 - 350 - 2000
assert o['guest_n'] == 3 and o['out'] == 1500
whats = {p['ref']: p for p in rep['problems']}
assert set(whats) == {'SNAAAAAAAAAAA3', 'SNAAAAAAAAAAA4'}, whats
assert whats['SNAAAAAAAAAAA3']['fix'] == 'SNAAAAAAAAAAA3' and 'not paid in SafeNet' in whats['SNAAAAAAAAAAA3']['what']
assert whats['SNAAAAAAAAAAA4']['fix'] is None and 'not at Snippe' in whats['SNAAAAAAAAAAA4']['what']
assert 'ORDER-77' not in page and 'SNAAAAAAAAAAA3' in page and 'Fix' in page
# all time: what SafeNet owes the businesses and its own share
page = html.unescape(c.get('/platform/reconcile?period=all').text)
assert 'Owed to businesses' in page and "SafeNet's own share" in page
# fix: Snippe says completed, so the payment is settled and the guest's code made
c.post('/platform/reconcile/fix', data={'csrf_token': tok(page), 'ref': 'SNAAAAAAAAAAA3', 'period': '30'})
with app.app_context():
    p = Payment.query.filter_by(reference='SNAAAAAAAAAAA3').one()
    assert p.status == 'paid' and p.voucher is not None
    # a payment Snippe didn't complete can't be "fixed"
c.post('/platform/reconcile/fix', data={'csrf_token': tok(page), 'ref': 'SNAAAAAAAAAAA4', 'period': '30'})
with app.app_context():
    assert Payment.query.filter_by(reference='SNAAAAAAAAAAA4').one().status == 'paid'
# Snippe's lists are read page by page, newest first, until the start of the period
items = [{'created_at': f'2026-10-{30 - i // 100:02d}T10:00:00Z'} for i in range(350)]
asked = []
snippe._request = lambda method, path, creds, *a, **k: asked.append(path) or {
    'items': items[int(path.split('offset=')[1]):int(path.split('offset=')[1]) + 100]}
got, complete = snippe._list('/v1/payments', None, since='2026-10-29T00:00:00')
assert complete and len(got) == 300 and len(asked) == 3          # stops at the page that reaches back past the 29th
asked.clear()
got, complete = snippe._list('/v1/payments', None, pages=2)
assert not complete and len(got) == 200
asked.clear()
assert snippe._list('/v1/payments', None)[1] and len(asked) == 4
print('RECONCILE OK')
