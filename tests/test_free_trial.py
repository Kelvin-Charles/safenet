import os, sys, time
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS'}
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Voucher, Gateway, Package
app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='A', slug='a', status='active'); db.session.add(t); db.session.flush()
    db.session.add_all([Gateway(tenant_id=t.id, name='gw', key_prefix='sgw_a', key_hash=_hash_key('sgw_a')),
                        Package(tenant_id=t.id, name='Day', price=Decimal(1000), validity_minutes=1440)])
    a = Admin(username='owner1', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    db.session.commit(); pkg = Package.query.one().id; TID = t.id

web = app.test_client()
web.post('/login', data={'username': 'owner1', 'password': 'password1'})
r = web.post('/vouchers/generate', data={'plan_id': 0, 'count': 3, 'validity_value': 2, 'validity_unit': 'hours',
                                          'price': '500', 'max_devices': 1, 'is_free': 'y'}, follow_redirects=True)
assert r.status_code == 200 and b'3 vouchers created in batch &#34;Free trial' in r.data, r.data[-3000:]
with app.app_context():
    free = Voucher.query.order_by(Voucher.id).all()
    assert len(free) == 3 and all(v.is_free and v.price is None and v.validity_minutes == 120 for v in free)
    codes = [v.code for v in free]
    batch = free[0].batch
assert b'Free trial</span>' in web.get('/vouchers').data
page = web.get(f'/vouchers/print?batch={batch}').data
assert page.count(b'FREE TRIAL') == 3 and b'TZS 500' not in page

api = app.test_client(); H = {'X-SafeNet-Key': 'sgw_a'}
auth = lambda code, mac: api.post('/api/gateway/auth', headers=H, json={'username': code, 'password': code, 'mac': mac, 'ip': '10.10.0.9'}).get_json()
assert auth(codes[0], 'AA-BB-CC-00-00-01')['ok']                       # first free trial on this phone
assert auth(codes[0], 'aa:bb:cc:00:00:01')['ok']                       # same code, same phone: fine
d = auth(codes[1], 'aa:bb:cc:00:00:01')                                # a second free code on the same phone
assert not d['ok'] and 'already had a free trial' in d['message'], d
with app.app_context(): assert Voucher.query.filter_by(code=codes[1]).one().status == 'unused'   # not burnt
assert auth(codes[1], 'aa:bb:cc:00:00:02')['ok']                       # another phone can use it

# The first phone then buys a package: counted as a conversion
ref = api.post('/api/portal/purchase', headers=H, json={'package_id': pkg, 'phone': '0684000111', 'network': 'airtel',
                                                        'mac': 'aa:bb:cc:00:00:01'}).get_json()['reference']
paid = api.get(f'/api/portal/purchase/{ref}', headers=H).get_json()['code']
assert auth(paid, 'aa:bb:cc:00:00:01')['ok']                           # paid codes are never blocked by the trial rule
html = web.get('/vouchers').data.decode()
assert 'Free trials: <strong>2</strong> phones tried' in html and '<strong>1</strong> bought a package' in html and '(50%)' in html, html[html.find('Free trials'):][:300]
with app.app_context():
    from app import _free_trial_stats
    assert _free_trial_stats(TID) == {'free_used': 2, 'free_bought': 1}
print('FREE TRIAL OK')
