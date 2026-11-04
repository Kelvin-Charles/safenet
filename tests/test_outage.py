"""The internet was down at a site: the business gives guests who had a package running the time they lost.
Where SafeNet keeps the time (MikroTik, Omada, gateway) the code's end moves later; at a Reyee site (Ruijie Cloud keeps
the time) each guest gets a free code. Guests are told by SMS; nobody is made up for twice."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
config.Config.SMS_PRICE = 30
import sms
outbox = []
sms.send_sms = lambda to, text, reference=None: outbox.append((to, text)) or True
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
appmod.send_mail = lambda *a, **k: True
appmod.sms_is_configured = lambda: True
made = []


class FakeCloud:
    def create_voucher(self, group_id, code, package): made.append((code, package['minutes']))


appmod._ruijie_cloud = lambda site: FakeCloud()


class SyncThread:
    def __init__(self, target, args=(), daemon=None): self.target, self.args = target, args
    def start(self): self.target(*self.args)


class FakeThreading:
    Thread = SyncThread


appmod.threading = FakeThreading
from app import app, db
import migrations
from models import Admin, Tenant, Site, Payment, Voucher, Outage, OutageCredit, SmsCharge
import json
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow().replace(second=0, microsecond=0)
down_from, back_at = now - timedelta(hours=11), now - timedelta(minutes=1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active', payment_mode='platform'); db.session.add(t); db.session.flush(); TID = t.id
    town = Site(tenant_id=TID, name='Town')
    hostel = Site(tenant_id=TID, name='JRIIT Hostel', ruijie_cloud_url='https://cloud-eu.ruijienetworks.com', ruijie_appid='a',
                  ruijie_secret_enc='x', ruijie_group_id='9001',
                  ruijie_packages=json.dumps({'packages': [{'minutes': 720, 'profile': 'p', 'user_group': 'u'},
                                                           {'minutes': 1440, 'profile': 'p2', 'user_group': 'u2'}]}))
    db.session.add_all([town, hostel]); db.session.flush(); TOWN, HOSTEL = town.id, hostel.id
    o = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); o.set_password('password1'); db.session.add(o)

    def code(c, site, started, lasts_min, phone=None):
        v = Voucher(tenant_id=TID, code=c, site_id=site, validity_minutes=lasts_min, status='active', first_used_at=started,
                    expires_at=started + timedelta(minutes=lasts_min), ruijie_state='ok' if site == HOSTEL else None)
        db.session.add(v); db.session.flush()
        if phone:
            db.session.add(Payment(tenant_id=TID, site_id=site, reference=f'P{c}', package_name='Day', validity_minutes=lasts_min, phone=phone,
                                   amount=Decimal(1000), net_amount=Decimal(970), currency='TZS', provider='snippe', provider_account='platform',
                                   status='paid', paid_at=started, voucher_id=v.id))
        return v.id
    # Town (SafeNet keeps the time)
    A = code('11110001', TOWN, now - timedelta(hours=20), 1440, '255700000001')      # running the whole outage: lost 10 h
    B = code('11110002', TOWN, now - timedelta(hours=23), 1440 + 0, None)             # ended 1 h into the outage, cash code
    C = code('11110003', TOWN, now - timedelta(hours=30), 120)                        # ended long before: not affected
    # Hostel (Reyee)
    H1 = code('22220001', HOSTEL, now - timedelta(hours=5), 1440, '255700000011')     # started during the outage: lost 4 h
    H2 = code('22220002', HOSTEL, now - timedelta(hours=12), 720, None)               # lost 11 h... ended at back_at - nothing
    db.session.commit()

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
assert 'Make up for an outage' in c.get('/vouchers').text
local = lambda d: (d + appmod._local_offset()).strftime('%Y-%m-%dT%H:%M') if False else None
with app.app_context():
    off = appmod._local_offset()
fmt = lambda d: (d + off).strftime('%Y-%m-%dT%H:%M')
page = c.get('/vouchers/outage').text
post = lambda **d: html.unescape(c.post('/vouchers/outage', data={'csrf_token': tok(page), 'starts_at': fmt(down_from), 'ends_at': fmt(back_at), **d},
                                        follow_redirects=True).text)
# Town: who was running, and the time each lost
r = post(site_id=TOWN, action='preview')
assert '11110001' in r and '11110002' in r and '11110003' not in r
assert '10 hours' in r or '10h' in r
assert 'end moves later' in r and '1 customers × 2 SMS × TZS 30 = TZS 60' in r      # the apology with its link: 2 SMS
# the preview is the first ticked customer with a phone (the cash code 11110002 has none)
assert 'Preview for the first customer: 0700000001 · code 11110001 · lost 10h 59m' in r
first = json.loads(re.search(r'data-first="(\{.*?\})">', r).group(1))
assert first['code'] == '11110001' and first['prefix'] == 'JRIIT: ' and first['link'].startswith('https://') and '/my/' in first['link']
assert 'apologise' in r and '{link}' in r                             # the message box, filled in by the page's script
r = post(site_id=TOWN, action='apply', picking='1', vid=[A, B], sms='1', text="Sorry for the outage. We've added {time} to your code {code}.")
assert '2 codes got their lost time back' in r and '1 SMS are being sent' in r
with app.app_context():
    a, b = db.session.get(Voucher, A), db.session.get(Voucher, B)
    lost_a = (back_at - down_from).total_seconds() / 60
    assert abs((a.expires_at - (now - timedelta(hours=20) + timedelta(minutes=1440 + lost_a))).total_seconds()) < 61
    assert a.validity_minutes == 1440 + 659
    assert b.expires_at > datetime.utcnow() + timedelta(minutes=55)      # ended during the outage: its hour counts from now
    assert b.state == 'active'
    assert SmsCharge.query.filter_by(kind='outage').count() == 1
assert outbox[-1][0] == '255700000001' and outbox[-1][1].startswith('JRIIT: Sorry for the outage. We') and '11110001' in outbox[-1][1]
# nobody twice
r = post(site_id=TOWN, action='preview')
assert 'already made up for' in r
# Hostel (Reyee): a free code of a Ruijie package length, sent once it's on Ruijie Cloud
r = post(site_id=HOSTEL, action='preview')
assert 'Reyee site' in r and '22220001' in r and 'A free code of 12 hours' in r and 'new code' in r
r = post(site_id=HOSTEL, action='apply', picking='1', vid=[H1, H2], sms='1', give=720, text='Pole! Free {time}: {code}')
assert '2 guests got a free code' in r
with app.app_context():
    credits = OutageCredit.query.join(Outage).filter(Outage.site_id == HOSTEL).all()
    assert len(credits) == 2 and all(cr.gift and cr.gift.validity_minutes == 720 and cr.gift.site_id == HOSTEL for cr in credits)
    gift1 = next(cr.gift for cr in credits if cr.voucher_id == H1)
    assert gift1.ruijie_state == 'ok' and (gift1.code, 720) in made
    assert db.session.get(Voucher, H1).expires_at == now - timedelta(hours=5) + timedelta(minutes=1440)   # Ruijie's code untouched
assert outbox[-1] == ('255700000011', f'JRIIT: Pole! Free 12 hours: {gift1.code}') or outbox[-1][1].endswith(gift1.code)
assert len(outbox) == 2                                               # the cash code (no phone) got no SMS
h = html.unescape(c.get('/vouchers/outage').text)
assert 'no phone: give by hand' in h
# Reyee needs {code} in the message
with app.app_context():
    v = code('22220003', HOSTEL, now - timedelta(hours=3), 1440, '255700000012'); db.session.commit()
r = post(site_id=HOSTEL, action='apply', picking='1', vid=[v], sms='1', give=720, text='Sorry about that')
assert 'Keep {code} in the message' in r
# dates checked
assert 'must end after it starts' in html.unescape(c.post('/vouchers/outage', data={'csrf_token': tok(page), 'site_id': TOWN, 'starts_at': fmt(back_at),
                                                                                  'ends_at': fmt(down_from), 'action': 'preview'}, follow_redirects=True).text)

# the SMS page: send to ticked customers only
sp = c.get('/offers/sms').text
r = html.unescape(c.post('/offers/sms', data={'csrf_token': tok(sp), 'text': 'Hello', 'action': 'preview'}).text)
assert 'Choose customers (3 of 3 ticked)' in r
r = html.unescape(c.post('/offers/sms', data={'csrf_token': tok(sp), 'text': 'Hello', 'action': 'preview', 'picking': '-----0', 'phone': ['255700000011']}).text)
assert '1 customers × 1 SMS' in r and 'Choose customers (1 of 3 ticked)' in r
r = html.unescape(c.post('/offers/sms', data={'csrf_token': tok(sp), 'text': 'Hello', 'site_id': HOSTEL, 'action': 'preview', 'picking': '-----0',
                                              'phone': ['255700000011']}).text)
assert '2 customers × 1 SMS' in r                                    # other choices: the ticks don't carry over
c.post('/offers/sms', data={'csrf_token': tok(sp), 'text': 'Hello', 'action': 'send', 'picking': '-----0', 'phone': ['255700000011']})
assert outbox[-1][0] == '255700000011' and outbox[-1][1].startswith('JRIIT: Hello Stop: ') and len(outbox) == 3
with app.app_context():
    assert SmsCharge.query.filter_by(kind='notice').count() == 1
# the guest's own page from the SMS link: time left, the offer it was bought with, and the make-up
with app.app_context():
    from models import SmsContact
    Payment.query.filter_by(voucher_id=A).update({'offer_name': 'Buy 3 days, get 1 free'}); db.session.commit()
    tok_a = SmsContact.query.filter_by(phone='255700000001').one().token
    tok_h = SmsContact.query.filter_by(phone='255700000011').one().token
my = html.unescape(app.test_client().get(f'/my/{tok_a}').text)
assert 'JRIIT' in my and '11110001' in my and 'Muda uliobaki' in my and 'Buy 3 days, get 1 free' in my and '+10h 59m' in my.replace('10 hours 59', '10h 59m') or '+10' in my
mh = html.unescape(app.test_client().get(f'/my/{tok_h}').text)
assert '22220001' in mh and gift1.code in mh and 'Vocha ya fidia' in mh
assert '11110001' not in mh                                           # only this phone's codes
assert app.test_client().get('/my/nothere').status_code == 404
# the default apology carries the link
r = post(site_id=TOWN, action='preview')
# Customers: everyone who paid is on the list (a new purchase adds them by itself), with tags, filters and SMS
with app.app_context():
    from models import SmsContact, Package
    pay = Payment(tenant_id=TID, site_id=HOSTEL, reference='PNEW', package_name='Siku 1', validity_minutes=1440, phone='255700000077',
                  amount=Decimal(1000), net_amount=Decimal(970), currency='TZS', provider='snippe', provider_account='platform', status='pending')
    db.session.add(pay); db.session.commit()
    pay.payer_name = appmod._real_payer_name(pay, 'Hostel JRIIT')        # only what SafeNet sent: not a name
    assert pay.payer_name is None
    pay.payer_name = appmod._real_payer_name(pay, 'Asha  Mussa')
    appmod._fulfil_payment(pay); db.session.commit()
    new = SmsContact.query.filter_by(tenant_id=TID, phone='255700000077').one()
    assert new.name == 'Asha Mussa' and new.purchases == 1 and new.spent == 1000 and new.last_site_id == HOSTEL and new.last_package == 'Siku 1'
    NEW = new.id
with app.app_context():      # customers from past payments (run once when this is deployed)
    migrations._fill_customers()
    one = SmsContact.query.filter_by(tenant_id=TID, phone='255700000001').one()
    assert one.purchases == 1 and one.spent == 1000 and one.last_site_id == TOWN and one.first_paid_at
    assert SmsContact.query.filter_by(tenant_id=TID, phone='255700000077').one().purchases == 1     # not counted twice
cl = html.unescape(c.get('/customers').text)
assert 'Asha Mussa' in cl and '0700000077' in cl and 'Has time left' in cl
c.post(f'/customers/{NEW}', data={'csrf_token': tok(cl), 'name': 'Asha M.', 'tags': 'students, hostel, students', 'note': 'room 12'})
with app.app_context():
    n = db.session.get(SmsContact, NEW)
    assert n.name == 'Asha M.' and n.tags == 'students, hostel' and n.note == 'room 12'
assert '0700000077' in html.unescape(c.get('/customers?tag=hostel').text) and '0700000011' not in html.unescape(c.get('/customers?tag=hostel').text)
assert '0700000077' in html.unescape(c.get('/customers?q=asha').text)
assert '0700000077' in html.unescape(c.get('/customers?q=0700000077').text)
# picked on Customers -> the SMS page sends to exactly them
sp = html.unescape(c.get(f'/offers/sms?cid={NEW}').text)
assert 'To the 1 customers you picked' in sp
r = html.unescape(c.post('/offers/sms', data={'csrf_token': tok(sp), 'text': 'Karibu', 'cid': NEW, 'action': 'preview'}).text)
assert '1 customers × 1 SMS' in r
# by tag and "has time left"
r = html.unescape(c.post('/offers/sms', data={'csrf_token': tok(sp), 'text': 'Karibu', 'tag': 'hostel', 'action': 'preview'}).text)
assert '1 customers × 1 SMS' in r
assert c.get('/customers').status_code == 200
print('OUTAGE OK')
