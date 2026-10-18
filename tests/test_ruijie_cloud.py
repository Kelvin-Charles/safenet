"""Ruijie Cloud vouchers (Reyee RG-RAP access points): connect a site, codes SafeNet makes or sells are created on
Ruijie Cloud in the package with the same duration, and the guest app sells for the site in its link."""
import html, os, re, sys
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS', 'collectedAmount': '1000'}
import ruijie
from datetime import datetime
made, down = [], [False]


class FakeCloud:
    def __init__(self, base, appid, secret):
        assert ruijie.valid_cloud(base) and secret == 'shh'

    def projects(self):
        return [('9001', 'JRIIT Hostel')]

    def packages(self, group_id):
        assert group_id == '9001'
        return [{'user_group': 'ug1', 'profile': 'pf1', 'minutes': 60, 'name': '1 Hour'},
                {'user_group': 'ug2', 'profile': 'pf2', 'minutes': 1440, 'name': '1 Day'}]

    def create_voucher(self, group_id, code, package):
        if down[0]:
            raise ruijie.RuijieError('Ruijie Cloud could not be reached: timed out')
        made.append((group_id, code, package['user_group']))


ruijie.Cloud = FakeCloud
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
from app import app, db
import migrations
from models import Admin, Tenant, Package, Voucher, Site
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    SID = tenant_sites(TID)[0].id
    other = Site(tenant_id=TID, name='Town'); db.session.add(other); db.session.flush(); OTHER = other.id
    db.session.add_all([Package(tenant_id=TID, name='Saa 1', price=Decimal(500), validity_minutes=60, site_id=SID),
                        Package(tenant_id=TID, name='Siku 1', price=Decimal(1000), validity_minutes=1440),
                        Package(tenant_id=TID, name='Wiki 1', price=Decimal(5000), validity_minutes=10080, site_id=SID),
                        Package(tenant_id=TID, name='Town only', price=Decimal(700), validity_minutes=120, site_id=OTHER)])
    db.session.commit()
    PKG_DAY = Package.query.filter_by(name='Siku 1').one().id

assert not ruijie.valid_cloud('https://evil.example.com') and not ruijie.valid_cloud('http://cloud-as.ruijienetworks.com')
assert ruijie.valid_cloud('https://cloud-as.ruijienetworks.com')

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = c.get('/sites').text
post = lambda **d: c.post(f'/sites/{SID}/ruijie-cloud', data={'csrf_token': tok(p), **d}, follow_redirects=True)
# only Ruijie's own servers
assert 'Choose the Ruijie Cloud server' in html.unescape(post(action='save', cloud='https://evil.example.com', appid='a', secret='shh').text)
r = html.unescape(post(action='save', cloud='https://cloud-as.ruijienetworks.com', appid='app1', secret='shh').text)
assert 'Ruijie Cloud connected' in r and 'Project: JRIIT Hostel' in r and '1 Hour · 1 hour' in r
assert 'Wiki 1' in r[r.index('no Ruijie package with the same duration'):][:400]           # 1 week has no Ruijie package
with app.app_context():
    s = db.session.get(Site, SID)
    assert s.ruijie_ready and s.ruijie_secret_enc and 'shh' not in s.ruijie_secret_enc and s.portal_token
    TOKEN = s.portal_token
assert f'/app/jriit?s={TOKEN}' in r and 'shh' not in r
# saving again without the secret keeps it
assert 'Ruijie Cloud connected' in html.unescape(post(action='save', cloud='https://cloud-as.ruijienetworks.com', appid='app1').text)

# generated vouchers wait for Ruijie Cloud, then are made there in the package with the same duration
r = c.get('/vouchers/generate')
c.post('/vouchers/generate', data={'csrf_token': tok(r.text), 'count': 3, 'validity_value': 1, 'validity_unit': 'hours', 'max_devices': 1, 'plan_id': 0})
with app.app_context():
    codes = [v.code for v in Voucher.query.filter_by(ruijie_state='pending')]
    assert len(codes) == 3
    appmod._ruijie_push_due()
    assert made == [('9001', code, 'ug1') for code in sorted(codes, key=lambda x: Voucher.query.filter_by(code=x).one().id)]
    assert Voucher.query.filter_by(ruijie_state='ok').count() == 3
# Ruijie Cloud down: the codes wait and the site shows why; they go once it's back
with app.app_context():
    v = appmod._create_vouchers(1, None, 1440, None, 'x', tenant=TID, site_id=SID)[0]; db.session.commit(); CODE = v.code
    down[0] = True; appmod._ruijie_push_due()
    assert Voucher.query.filter_by(code=CODE).one().ruijie_state == 'pending' and 'could not be reached' in db.session.get(Site, SID).ruijie_error
    down[0] = False; appmod._ruijie_push_due()
    assert Voucher.query.filter_by(code=CODE).one().ruijie_state == 'ok' and db.session.get(Site, SID).ruijie_error is None
    # a duration with no Ruijie package fails, and says what to create
    w = appmod._create_vouchers(1, None, 10080, None, 'x', tenant=TID, site_id=SID)[0]; db.session.commit()
    appmod._ruijie_push_due()
    assert Voucher.query.filter_by(code=w.code).one().ruijie_state == 'failed' and 'No Ruijie package lasts 7 days' in db.session.get(Site, SID).ruijie_error
    # another site's codes aren't copied
    o = appmod._create_vouchers(1, None, 60, None, 'x', tenant=TID, site_id=OTHER)[0]; db.session.commit()
    assert o.ruijie_state is None
p = html.unescape(c.get('/sites').text)
assert '4 codes made on Ruijie Cloud, 0 waiting, 1 failed' in p and 'Try failed codes again' in p

# the guest app from the Ruijie login page link: this site's packages, buy straight away, the code to type on Ruijie's page
g = app.test_client()
me = g.post('/app/jriit/api/me', json={'tokens': [], 'site': TOKEN}).get_json()
assert me['ruijie'] and me['can_buy'] and sorted(x['name'] for x in me['packages']) == ['Saa 1', 'Siku 1', 'Wiki 1']
b = g.post('/app/jriit/api/buy', json={'tokens': [], 'site': TOKEN, 'package_id': PKG_DAY, 'phone': '0684000111', 'network': 'airtel'}).get_json()
paid = g.get(f'/app/jriit/api/pay/{b["reference"]}').get_json()
assert paid['status'] == 'paid' and paid['ruijie'] and paid['code']
with app.app_context():
    v = Voucher.query.filter_by(code=paid['code']).one()
    assert v.site_id == SID and v.ruijie_state == 'pending'
    appmod._ruijie_push_due()
    assert made[-1] == ('9001', paid['code'], 'ug2')

# removing it stops the copying
assert 'Ruijie Cloud removed' in html.unescape(post(action='remove').text)
with app.app_context():
    assert not db.session.get(Site, SID).ruijie_ready and Voucher.query.filter(Voucher.ruijie_state.in_(('pending', 'sending'))).count() == 0
print('RUIJIE CLOUD OK')
