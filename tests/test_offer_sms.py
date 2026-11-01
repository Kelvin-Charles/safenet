"""A business sends an offer by SMS to its customers (phones that paid before): it sees who gets it and the cost first;
each SMS starts with the business name and ends with a stop link; customers who stopped, or got an offer in the last
24 hours, are left out; only SMS the gateway accepted are charged, from the SafeNet Pay balance."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, SMS_PRICE='30')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
config.Config.SMS_PRICE = 30
import sms
outbox = []
def fake_send(to, text, reference=None):
    outbox.append((to, text))
    return to != '255700000009'            # the gateway refuses this one
sms.send_sms = fake_send
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
appmod.send_mail = lambda *a, **k: True
appmod.sms_is_configured = lambda: True


class SyncThread:                           # send at once in the test
    def __init__(self, target, args=(), daemon=None): self.target, self.args = target, args
    def start(self): self.target(*self.args)


class FakeThreading:
    Thread = SyncThread


from app import app, db, tenant_balance
import migrations
from models import Admin, Tenant, Site, Payment, Offer, SmsCampaign, SmsCharge, SmsContact
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kpstar', slug='kpstar', status='active', payment_mode='platform'); db.session.add(t); db.session.flush(); TID = t.id
    a = Site(tenant_id=TID, name='Olasiti'); b = Site(tenant_id=TID, name='Town'); db.session.add_all([a, b]); db.session.flush()
    SA, SB = a.id, b.id
    o = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); o.set_password('password1'); db.session.add(o)
    other = Tenant(name='Other', slug='other', status='active'); db.session.add(other); db.session.flush()
    rows = [('255700000001', SA, 0), ('255700000001', SA, 2), ('255700000002', SA, 10), ('255700000003', SB, 5),
            ('255700000004', SA, 200), ('255700000009', SA, 1)]
    for i, (phone, site, ago) in enumerate(rows):
        db.session.add(Payment(tenant_id=TID, site_id=site, reference=f'P{i}', package_name='Day', validity_minutes=1440, phone=phone,
                               amount=Decimal(1000), fee_amount=Decimal(30), net_amount=Decimal(970), currency='TZS',
                               provider='snippe', provider_account='platform', status='paid', paid_at=now - timedelta(days=ago)))
    db.session.add(Payment(tenant_id=TID, site_id=SA, reference='PF', package_name='Day', validity_minutes=1440, phone='255700000005',
                           amount=Decimal(1000), currency='TZS', provider='snippe', provider_account='platform', status='failed'))
    db.session.add(Payment(tenant_id=other.id, reference='PO', package_name='Day', validity_minutes=1440, phone='255700000006',
                           amount=Decimal(1000), net_amount=Decimal(970), currency='TZS', provider='snippe', provider_account='platform', status='paid', paid_at=now))
    off = Offer(tenant_id=TID, name='Buy 3 days, get 1 free', bonus_minutes=1440); db.session.add(off)
    db.session.commit(); OFF = off.id
    start_balance = tenant_balance(TID)[0]

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
assert 'Send by SMS' in c.get('/offers').text
page = html.unescape(c.get(f'/offers/sms?offer={OFF}').text)
assert 'Offer: Buy 3 days, get 1 free.' in page                     # the offer's message, ready to change
assert 'SMS cost is taken from your SafeNet Pay balance.' in page and 'Each SMS costs TZS 30. Your balance now: TZS 5,820.' in page
post = lambda **d: html.unescape(c.post('/offers/sms', data={'csrf_token': tok(page), **d}, follow_redirects=True).text)
# preview: who gets it and the cost, nothing sent yet (failed payments and other businesses' customers don't count)
r = post(text='Wi-Fi 50% off this weekend!', action='preview')
assert 'Check before sending' in r and '5 customers × 1 SMS × TZS 30 = TZS 150' in r
assert 'Balance after sending: TZS 5,670.' in r and 'TZS 150 will be taken from your SafeNet Pay balance. Send?' in r
assert 'Kpstar: Wi-Fi 50% off this weekend! Stop: ' in r and outbox == []
r = post(text='Wi-Fi 50% off this weekend!', site_id=SA, days=30, action='preview')
assert '3 customers × 1 SMS' in r                                    # Olasiti, paid in the last 30 days
assert 'Write the message' in post(text='', action='preview')
assert 'up to 300 characters' in post(text='x' * 301, action='preview')
# send
appmod.threading = FakeThreading
r = post(text='Wi-Fi 50% off this weekend!', site_id=SA, days=30, offer=OFF, action='send')
assert 'Sending your offer to 3 customers' in r and 'Up to TZS 90 is taken from your SafeNet Pay balance' in r
assert sorted(p for p, _ in outbox) == ['255700000001', '255700000002', '255700000009']
assert all(t.startswith('Kpstar: Wi-Fi 50% off this weekend! Stop: http') and '/stop/' in t for _, t in outbox)
with app.app_context():
    camp = SmsCampaign.query.one()
    assert camp.status == 'done' and camp.recipients == 3 and camp.sent == 2 and camp.amount == 60 and camp.offer_id == OFF
    assert SmsCharge.query.filter_by(kind='offer').count() == 2                     # the refused one isn't charged
    assert tenant_balance(TID)[0] == start_balance - 60
    assert SmsContact.query.filter_by(tenant_id=TID).count() == 3
assert '2/3' in html.unescape(c.get('/offers/sms').text)
# within 24 hours the customers who got it are left out (no double sends); the one the gateway refused can still get it
r = post(text='Again', site_id=SA, days=30, action='preview')
assert '1 customers × 1 SMS' in r and '2 left out: they got an offer in the last 24 hours' in r
# a customer opens the stop link
link = next(t for p, t in outbox if p == '255700000002').split('Stop: ')[1]
token = link.rsplit('/', 1)[1]
guest = app.test_client()
s = guest.get(f'/stop/{token}')
assert s.status_code == 200 and 'Kpstar' in s.text and 'Stop' in s.text
guest.post(f'/stop/{token}', data={'csrf_token': tok(s.text), 'action': 'stop'})
assert "won't get offers" in html.unescape(guest.get(f'/stop/{token}').text)
assert guest.get('/stop/nothere').status_code == 404
with app.app_context():
    SmsCharge.query.update({'created_at': now - timedelta(days=2)}); db.session.commit()   # a day later
r = post(text='Again', site_id=SA, days=30, action='preview')
assert '2 customers × 1 SMS' in r and '1 left out: they asked to stop' in r
# they can start again
s = guest.get(f'/stop/{token}')
guest.post(f'/stop/{token}', data={'csrf_token': tok(s.text), 'action': 'start'})
assert '3 customers × 1 SMS' in post(text='Again', site_id=SA, days=30, action='preview')
# not enough balance: refused
with app.app_context():
    config.Config.SMS_PRICE = 100000
assert 'balance' in post(text='Again', action='send') and len(outbox) == 3
config.Config.SMS_PRICE = 30
print('OFFER SMS OK')
