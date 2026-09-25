import os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='mixx:1000,airtel,halopesa')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
sys.path.insert(0, 'gateway')
import portal_ui as ui
assert [n['id'] for n in ui.parse_networks('mixx:1000,airtel,bogus,halopesa,airtel')] == ['mixx', 'airtel', 'halopesa']
assert ui.parse_networks('mixx:1000')[0]['min_amount'] == 1000 and ui.parse_networks('airtel')[0]['min_amount'] == 0
assert ui.network_for_phone('0754123456') == 'mpesa' and ui.network_for_phone('255684123456') == 'airtel'
assert ui.network_for_phone('712345678') == 'mixx' and ui.network_for_phone('0621000000') == 'halopesa' and ui.network_for_phone('0731000000') is None
assert ui.network_for_method('TIGO-PESA') == 'mixx' and ui.network_for_method('AIRTEL-MONEY') == 'airtel' and ui.network_for_method('HALOPESA') == 'halopesa' and ui.network_for_method('M-PESA') == 'mpesa'
import clickpesa
state = {'available': ['AIRTEL-MONEY'], 'pushes': 0}
clickpesa.preview_ussd_push = lambda a, p, r, c=None: state['available']
def push(a, p, r, c=None):
    state['pushes'] += 1; return {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.initiate_ussd_push = push
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Package, Gateway, BillingPlan
app.config.update(TESTING=True)
with app.app_context():
    db.create_all(); migrations.run(); __import__("models").BillingPlan.query.delete(); db.session.commit()
    t = Tenant(name='A', slug='a', status='active'); db.session.add(t); db.session.flush()
    db.session.add_all([Package(tenant_id=t.id, name='1h', price=Decimal(500), validity_minutes=60),
                        Package(tenant_id=t.id, name='1d', price=Decimal(1000), validity_minutes=1440),
                        Gateway(tenant_id=t.id, name='gw', key_prefix='sgw_a', key_hash=_hash_key('sgw_a')),
                        BillingPlan(name='Starter', price=Decimal(20000))])
    a = Admin(username='owner1', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    db.session.commit()
    cheap, day = [p.id for p in Package.query.order_by(Package.price)]
api = app.test_client(); H = {'X-SafeNet-Key': 'sgw_a'}
d = api.get('/api/portal/packages', headers=H).get_json()
assert [n['id'] for n in d['networks']] == ['mixx', 'airtel', 'halopesa'] and d['networks'][0]['min_amount'] == 1000
buy = lambda pkg, phone, net: api.post('/api/portal/purchase', headers=H, json={'package_id': pkg, 'phone': phone, 'network': net})
r = buy(cheap, '0712345678', 'mixx'); assert r.status_code == 400 and 'start from TZS 1,000' in r.get_json()['error']
r = buy(cheap, '0712345678', 'airtel'); assert r.status_code == 400 and 'looks like a Mixx by Yas number' in r.get_json()['error']
r = buy(cheap, '0754123456', 'airtel'); assert r.status_code == 400 and "M-Pesa isn't available yet" in r.get_json()['error']
r = buy(cheap, '0684123456', 'mpesa'); assert r.status_code == 400 and 'Choose your mobile-money network' in r.get_json()['error']
r = api.post('/api/portal/purchase', headers=H, json={'package_id': cheap, 'phone': '0754123456'})    # old gateway, no network
assert r.status_code == 400 and "M-Pesa numbers can't pay yet" in r.get_json()['error']
assert state['pushes'] == 0                                              # nothing reached ClickPesa
r = buy(cheap, '0684123456', 'airtel'); assert r.status_code == 200 and state['pushes'] == 1
state['available'] = ['TIGO-PESA']
r = buy(day, '0685123456', 'airtel'); assert r.status_code == 502 and "Airtel Money isn't available for this number" in r.get_json()['error'] and state['pushes'] == 1
state['available'] = ['TIGO-PESA']
r = buy(day, '0713123456', 'mixx'); assert r.status_code == 200 and state['pushes'] == 2
# Billing: M-Pesa numbers get a clear message
tok = lambda h: re.search(r'name="csrf-token" content="([^"]+)"', h).group(1)
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner1', 'password': 'password1', 'csrf_token': re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text).group(1)})
with app.app_context(): plan = BillingPlan.query.one().id
r = c.post('/billing/pay', data={'csrf_token': tok(c.get('/billing').text), 'plan_id': plan, 'months': 1, 'phone': '0754000000'}, follow_redirects=True)
assert "M-Pesa numbers can&#39;t pay yet" in r.text or "M-Pesa numbers can't pay yet" in r.text
# preview shows tiles with static logos, landing lists networks
r = app.test_client().get('/portal?t=a&preview=1&view=buy'); assert 'name="network"' in r.text and '/static/img/airtel.png' in r.text and 'From TZS 1,000' in r.text
assert 'M-Pesa' not in r.text
r = app.test_client().get('/'); assert 'Airtel Money' in r.text and 'M-Pesa' not in r.text
print('NETWORKS CLOUD OK')
