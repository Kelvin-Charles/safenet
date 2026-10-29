"""SafeNet stays in step with Snippe: a payment whose request timed out isn't failed (Snippe may have sent the PIN
prompt and taken the money); it's found later by our reference and settled, unfinished payments are checked every
minute, and Snippe's webhook finds a payment by our reference too."""
import json, os, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PAYMENT_PROVIDER='snippe', SNIPPE_API_KEY='snp_platform',
                  SNIPPE_WEBHOOK_KEY='whsec', PUBLIC_URL='https://radius.example.tz')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import snippe
remote = {}           # our reference -> Snippe's record


def create_payment(amount, phone, ref, creds, webhook_url=None, customer=None):
    remote[ref] = {'reference': 'snp-' + ref, 'status': 'pending', 'metadata': {'order_reference': ref}, 'amount': {'value': int(amount)}}
    raise snippe.SnippeError('Snippe unreachable: The read operation timed out')       # it went through, the answer didn't


snippe.create_payment = create_payment
snippe.get_payment = lambda sid, creds: next((r for r in remote.values() if r['reference'] == sid), None)
snippe.find_payment = lambda ref, creds, pages=5: remote.get(ref)
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
from app import app, db, _start_purchase
import migrations
from models import Tenant, Package, Payment
from tenancy import tenant_sites
app.config.update(TESTING=True)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='USMART', slug='usmart', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    db.session.add(Package(tenant_id=TID, name='EMERGENCY', price=Decimal(500), validity_minutes=360)); db.session.commit()
    pkg = Package.query.filter_by(tenant_id=TID).one(); site = tenant_sites(TID)[0]

    # the request times out: the guest waits for the PIN, the payment stays pending (not failed)
    p, error, status = _start_purchase(t, site.id, pkg, '0712765209', None)
    assert error is None and status == 200 and p.status == 'pending' and p.provider_id is None, (error, p.status)
    REF = p.reference
    remote[REF]['status'] = 'completed'
    # the guest's page asks: found at Snippe by our reference, paid, voucher made
    p = appmod._refresh_payment(REF, force=True)
    assert p.status == 'paid' and p.provider_id == 'snp-' + REF and p.voucher and p.message is None

    # an older payment marked failed only because Snippe didn't answer in time: the sync finds it was paid
    old = Payment(tenant_id=TID, reference='SN1D614AFEE042', package_id=pkg.id, package_name='EMERGENCY', validity_minutes=360,
                  phone='255712765209', amount=Decimal(500), customer_fee=Decimal(13), currency='TZS', provider='snippe',
                  provider_account='platform', status='failed', message='Snippe unreachable: The read operation timed out',
                  site_id=site.id, created_at=datetime.utcnow() - timedelta(hours=3), net_amount=Decimal(485), fee_amount=Decimal(15))
    db.session.add(old); db.session.commit()
    remote['SN1D614AFEE042'] = {'reference': 'SN179325', 'status': 'completed', 'metadata': {'order_reference': 'SN1D614AFEE042'},
                                'amount': {'value': 513}}
    # a guest who left before entering the PIN: Snippe says it expired
    p2, _, _ = _start_purchase(t, site.id, pkg, '0712765210', None)
    remote[p2.reference]['status'] = 'expired'
    # a request that never reached Snippe at all, half an hour ago
    lost = Payment(tenant_id=TID, reference='SNNEVERARRIVED', package_name='EMERGENCY', validity_minutes=360, phone='255712765211',
                   amount=Decimal(500), currency='TZS', provider='snippe', provider_account='platform', status='pending',
                   created_at=datetime.utcnow() - timedelta(minutes=45))
    db.session.add(lost); db.session.commit()
    appmod._payments_sync_due()
    o = Payment.query.filter_by(reference='SN1D614AFEE042').one()
    assert o.status == 'paid' and o.voucher is not None and o.provider_id == 'SN179325', (o.status, o.message)
    e = Payment.query.filter_by(reference=p2.reference).one()
    assert e.status == 'failed' and 'expired' in e.message
    n = Payment.query.filter_by(reference='SNNEVERARRIVED').one()
    assert n.status == 'failed' and 'did not reach' in n.message
    # only what needs it: a recent pending payment that was just checked isn't asked again
    p3, _, _ = _start_purchase(t, site.id, pkg, '0712765212', None)
    Payment.query.filter_by(reference=p3.reference).update({'checked_at': datetime.utcnow()}); db.session.commit()
    calls = []
    snippe.find_payment = lambda ref, creds, pages=5: calls.append(ref) or remote.get(ref)
    appmod._payments_sync_due()
    assert p3.reference not in calls

# Snippe's webhook for a payment we never got Snippe's id for: found by our reference, but only when it's signed
c = app.test_client()
with app.app_context():
    p4, _, _ = _start_purchase(db.session.get(Tenant, TID), tenant_sites(TID)[0].id, Package.query.first(), '0712765213', None)
    REF4 = p4.reference
remote[REF4]['status'] = 'completed'
body = json.dumps({'type': 'payment.completed', 'data': {'reference': 'snp-' + REF4, 'metadata': {'order_reference': REF4}}})
assert c.post('/webhooks/snippe', data=body, headers={'Content-Type': 'application/json'}).status_code == 401
with app.app_context():
    assert Payment.query.filter_by(reference=REF4).one().provider_id is None          # a forged one changes nothing
appmod.snippe.verify_webhook = lambda *a, **k: True
assert c.post('/webhooks/snippe', data=body, headers={'Content-Type': 'application/json'}).status_code == 200
with app.app_context():
    p4 = Payment.query.filter_by(reference=REF4).one()
    assert p4.status == 'paid' and p4.provider_id == 'snp-' + REF4
print('PAYMENT SYNC OK')
