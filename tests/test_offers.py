"""Offers: a business gives extra free time and/or a discount on its packages ("buy 3 days, get 1 day free"), for one
package or all, at one site or all, between dates. Guests see it on the login pages and in the guest app, and a
purchase gets it: the voucher lasts longer, the price is lower."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PAYMENT_PROVIDER='snippe', SNIPPE_API_KEY='snp', SNIPPE_FEE_PERCENT='2.5',
                  PUBLIC_URL='https://radius.example.tz')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import snippe
asked, state = [], {}
def create_payment(amount, phone, ref, creds, webhook_url=None, customer=None):
    asked.append(amount); state[ref] = 'pending'
    return {'reference': 'snp-' + ref, 'status': 'pending'}
snippe.create_payment = create_payment
snippe.get_payment = lambda sid, creds: {'reference': sid, 'status': state[sid[4:]], 'amount': {'value': asked[-1]}}
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
from app import app, db, _start_purchase, _refresh_payment
import migrations
from models import Admin, Tenant, Site, Package, Payment, Offer
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='USMART', slug='usmart', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    main = Site(tenant_id=TID, name='Main', portal_token='mktok'); other = Site(tenant_id=TID, name='Cafe', portal_token='cafetok')
    db.session.add_all([main, other]); db.session.flush(); MAIN, CAFE = main.id, other.id
    db.session.add_all([Package(tenant_id=TID, name='Siku 3', price=Decimal(3000), validity_minutes=3 * 1440, sort_order=1),
                        Package(tenant_id=TID, name='Siku 1', price=Decimal(1000), validity_minutes=1440, sort_order=2)])
    db.session.commit()
    P3, P1 = (p.id for p in Package.query.order_by(Package.sort_order))

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
f = c.get('/offers/add').text
assert 'Extra free time' in html.unescape(f)
save = lambda **d: html.unescape(c.post('/offers/add', data={'csrf_token': tok(f), 'is_active': '1', 'bonus_unit': 'days', **d}, follow_redirects=True).text)
assert 'Give extra time, a discount, or both' in save(name='Nothing', package_id=P3, bonus_value=0, discount_percent=0)
assert 'up to 90%' in save(name='Too much', discount_percent=95)
r = save(name='Nunua siku 3 upate siku 1 bure', package_id=P3, bonus_value=1, discount_percent=0, site_id=MAIN)
assert 'saved' in r and 'Nunua siku 3 upate siku 1 bure' in r and 'On now' in r
with app.app_context():
    tenant = db.session.get(Tenant, TID)
    pk = {p['id']: p for p in appmod._guest_packages(tenant, MAIN)}
    assert pk[P3]['validity_minutes'] == 4 * 1440 and pk[P3]['price'] == '3000' and 'Nunua siku 3' in pk[P3]['description']
    assert pk[P1]['validity_minutes'] == 1440 and not pk[P1]['offer']               # another package: no offer
    assert not {p['id']: p for p in appmod._guest_packages(tenant, CAFE)}[P3]['offer']   # another site: no offer
    # buying it: the voucher lasts 4 days
    pay, err, _ = _start_purchase(tenant, MAIN, db.session.get(Package, P3), '0712000001')
    assert err is None and pay.validity_minutes == 4 * 1440 and pay.amount == 3000 and pay.offer_name.startswith('Nunua')
    REF = pay.reference
state[REF] = 'completed'
with app.app_context():
    p = _refresh_payment(REF, force=True)
    assert p.status == 'paid' and p.voucher.validity_minutes == 4 * 1440

# a discount on all packages, newest offer wins where both fit
r = save(name='Weekend 20% off', bonus_value=0, discount_percent=20)
with app.app_context():
    tenant = db.session.get(Tenant, TID)
    pk = {p['id']: p for p in appmod._guest_packages(tenant, MAIN)}
    assert pk[P1]['price'] == '800' and pk[P1]['old_price'] == '1000'
    assert pk[P3]['price'] == '2400' and pk[P3]['validity_minutes'] == 3 * 1440          # the newer offer
    pay, err, _ = _start_purchase(tenant, CAFE, db.session.get(Package, P1), '0712000002')
    assert err is None and pay.amount == 800 and pay.customer_fee == 21 and asked[-1] == 821     # Snippe's share on the lower price
    assert pay.fee_amount == pay.amount * appmod._fee_percent(tenant) / 100
# guests see it: the MikroTik login page shows the old price struck out and the offer
g = app.test_client()
g.get('/mikrotik/mktok?link-login-only=http://10.5.50.1/login&mac=AA:BB:CC:00:00:01', base_url='https://radius.example.tz')
page = html.unescape(g.get('/mikrotik/mktok', base_url='https://radius.example.tz').text)
assert 'Weekend 20% off' in page and '<s ' in page and '800' in page
# switch it off: back to normal prices; offers that ended or haven't started don't count
lst = c.get('/offers').text
with app.app_context():
    WEEKEND = Offer.query.filter_by(name='Weekend 20% off').one().id
c.post(f'/offers/{WEEKEND}/toggle', data={'csrf_token': tok(lst)})
with app.app_context():
    tenant = db.session.get(Tenant, TID)
    assert {p['id']: p for p in appmod._guest_packages(tenant, MAIN)}[P1]['price'] == '1000'
    Offer.query.filter(Offer.id != WEEKEND).update({'ends_at': datetime.utcnow() - timedelta(minutes=1)}); db.session.commit()
    assert not {p['id']: p for p in appmod._guest_packages(tenant, MAIN)}[P3]['offer']
assert 'Ended' in html.unescape(c.get('/offers').text) and '1' in c.get('/offers').text
# the payments list shows which offer a sale used
assert 'Nunua siku 3 upate siku 1 bure' in html.unescape(c.get('/payments').text)
# deleting an offer keeps it on past payments
c.post(f'/offers/{WEEKEND}/delete', data={'csrf_token': tok(lst)})
with app.app_context():
    assert Offer.query.filter_by(id=WEEKEND).first() is None
    assert Payment.query.filter_by(offer_name='Weekend 20% off').count() == 1
# Reyee: Ruijie Cloud gets a package for the longer time an offer gives (codes are made in a package of that length)
class Cloud:
    made = []
    def create_package(self, group, name, minutes, **kw): self.made.append(minutes)
with app.app_context():
    Offer.query.update({'ends_at': None, 'is_active': True}); db.session.commit()
    site = db.session.get(Site, MAIN); site.ruijie_group_id = '9001'
    appmod._ruijie_make_packages(site, Cloud(), [{'minutes': 1440}, {'minutes': 3 * 1440}])
    assert Cloud.made == [4 * 1440], Cloud.made
print('OFFERS OK')
