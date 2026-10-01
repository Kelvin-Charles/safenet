"""Snippe as a second payment provider: platform switch, SafeNet Pay fee, own accounts, webhooks, subscriptions."""
import hashlib, hmac, json, os, re, sys, threading, time
from datetime import datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='cp', CLICKPESA_API_KEY='cpk',
                  SNIPPE_API_KEY='snp_platform', SNIPPE_WEBHOOK_KEY='whsec_platform', PLATFORM_FEE_PERCENT='3',
                  PUBLIC_URL='https://radius.example.tz')
sys.path.insert(0, os.getcwd())

sn = {'payments': {}, 'calls': []}
class FakeSnippe(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def key(self):
        return (self.headers.get('Authorization') or '').replace('Bearer ', '')
    def do_GET(self):
        if self.key() not in ('snp_platform', 'snp_tenant'):
            return self.out(401, {'status': 'error', 'code': 401, 'error_code': 'unauthorized', 'message': 'invalid or missing API key'})
        if self.path == '/v1/payments/balance':
            return self.out(200, {'status': 'success', 'code': 200, 'data': {'available': {'value': 0, 'currency': 'TZS'}}})
        m = re.match(r'/v1/payments/([0-9a-f-]+)$', self.path)
        p = sn['payments'].get(m.group(1)) if m else None
        if not p or p['key'] != self.key():
            return self.out(404, {'status': 'error', 'code': 404, 'error_code': 'not_found', 'message': 'payment not found'})
        return self.out(200, {'status': 'success', 'code': 200, 'data': {'reference': m.group(1), 'status': p['status'], 'object': 'payment',
                        'amount': {'currency': 'TZS', 'value': p['amount']}, 'channel': {'provider': 'mpesa', 'type': 'mobile_money'}}})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if self.key() not in ('snp_platform', 'snp_tenant'):
            return self.out(401, {'status': 'error', 'code': 401, 'error_code': 'unauthorized', 'message': 'invalid or missing API key'})
        assert self.path == '/v1/payments', self.path
        idem = self.headers.get('Idempotency-Key') or ''
        assert idem and len(idem) <= 30, idem
        assert body['payment_type'] == 'mobile' and body['details']['currency'] == 'TZS' and isinstance(body['details']['amount'], int), body
        assert re.fullmatch(r'255\d{9}', body['phone_number']) and all(body['customer'].get(k) for k in ('firstname', 'lastname', 'email')), body
        assert body['metadata']['order_reference'] == idem and body['webhook_url'] == 'https://radius.example.tz/webhooks/snippe', body
        if body['details']['amount'] < 500:
            return self.out(400, {'status': 'error', 'code': 400, 'error_code': 'validation_error', 'message': 'minimum amount is 500'})
        ref = f'{len(sn["payments"]):08d}-0000-4000-8000-000000000000'
        sn['payments'][ref] = {'status': 'pending', 'amount': body['details']['amount'], 'key': self.key(), 'order': idem, 'phone': body['phone_number']}
        sn['calls'].append(('create', self.key(), idem))
        return self.out(201, {'status': 'success', 'code': 201, 'data': {'reference': ref, 'status': 'pending', 'object': 'payment',
                        'payment_type': 'mobile', 'amount': {'currency': 'TZS', 'value': body['details']['amount']}}})
srv = ThreadingHTTPServer(('127.0.0.1', 0), FakeSnippe); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ['SNIPPE_BASE_URL'] = f'http://127.0.0.1:{srv.server_address[1]}'

import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
cp_calls = []
clickpesa.preview_ussd_push = lambda a, p, r, c=None: cp_calls.append(('preview', r)) or ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: cp_calls.append(('push', r)) or {'id': 'CPTX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'PROCESSING'}
from app import app, db, _hash_key
import migrations, snippe
from models import Admin, Tenant, Gateway, Package, Payment, Voucher, BillingPlan, SubscriptionPayment
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    boss = Admin(username='platform', email='p@x.tz', tenant_id=migrations.default_tenant().id, role='owner', is_superadmin=True, email_verified_at=now)
    boss.set_password('password1')
    t = Tenant(name='Morombo', slug='morombo', status='trial', trial_ends_at=now + timedelta(days=5)); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1')
    db.session.add_all([boss, o, Gateway(tenant_id=t.id, name='gw', key_prefix='sgw_m', key_hash=_hash_key('sgw_m')),
                        Package(tenant_id=t.id, name='6 Hours', price=Decimal(1000), validity_minutes=360),
                        Package(tenant_id=t.id, name='Tiny', price=Decimal(300), validity_minutes=30)])
    db.session.commit(); TID = t.id
    PKG = Package.query.filter_by(name='6 Hours').one().id; TINY = Package.query.filter_by(name='Tiny').one().id
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
H = {'X-SafeNet-Key': 'sgw_m'}
api = app.test_client()
buy = lambda phone, network, pkg=PKG: api.post('/api/portal/purchase', headers=H, json={'package_id': pkg, 'phone': phone, 'network': network})

def webhook(snippe_ref, key, event='payment.completed', ts=None, tamper=False):
    body = json.dumps({'id': 'evt_1', 'type': event, 'api_version': '2026-01-25', 'data': {'reference': snippe_ref,
                       'amount': {'value': 1000, 'currency': 'TZS'}}}, separators=(',', ':'))
    ts = str(int(ts or time.time()))
    sig = hmac.new(key.encode(), f'{ts}.{body}'.encode(), hashlib.sha256).hexdigest()
    if tamper:
        body = body.replace('1000', '9000')
    return api.post('/webhooks/snippe', data=body, content_type='application/json',
                    headers={'X-Webhook-Timestamp': ts, 'X-Webhook-Signature': sig, 'X-Webhook-Event': event})

# 1. default provider is ClickPesa: M-Pesa not offered (ClickPesa networks), fee 3%
nets = [n['id'] for n in api.get('/api/portal/packages', headers=H).get_json()['networks']]
assert 'mpesa' not in nets and 'airtel' in nets, nets
r = buy('0684000111', 'airtel'); assert r.status_code == 200, r.get_json()
with app.app_context():
    p = Payment.query.one(); assert p.provider == 'clickpesa' and p.provider_account == 'platform' and p.fee_amount == Decimal('30.00')
assert ('push', p.reference) in cp_calls

# 2. platform admin switches SafeNet Pay to Snippe
cs = login('platform'); pb = cs.get('/platform/billing').text
assert 'SafeNet Pay: mobile-money provider' in pb and 'In use' in pb
r = cs.post('/platform/payment-provider', data={'csrf_token': tok(pb), 'provider': 'snippe'}, follow_redirects=True).text
assert 'now uses Snippe' in r
co = login('owner')
assert 'through Snippe' in co.get('/settings/payments').text

# 3. a Vodacom M-Pesa guest pays through Snippe (SafeNet Pay, 3% fee)
nets = [n['id'] for n in api.get('/api/portal/packages', headers=H).get_json()['networks']]
assert 'mpesa' in nets, nets
r = buy('0754000222', 'mpesa'); d = r.get_json()
assert r.status_code == 200 and d['status'] == 'pending', d
with app.app_context():
    p = Payment.query.filter_by(reference=d['reference']).one()
    assert p.provider == 'snippe' and p.provider_account == 'platform' and p.provider_id and p.fee_amount == Decimal('30.00') and p.net_amount == Decimal('970.00')
    SREF = p.provider_id
assert sn['calls'][-1] == ('create', 'snp_platform', d['reference'])
r = buy('0754000223', 'mpesa', TINY); assert r.status_code == 502 and '500' in r.get_json()['error'], r.get_json()   # below Snippe's minimum
with app.app_context():
    tiny = Payment.query.filter_by(phone='255754000223').first()
    assert tiny is not None and tiny.status == 'failed'

# still pending with Snippe -> polling says pending
assert api.get(f"/api/portal/purchase/{d['reference']}", headers=H).get_json()['status'] == 'pending'

# 4. webhooks: bad signature, old timestamp and tampered body are refused; a valid one fulfils after re-checking
sn['payments'][SREF]['status'] = 'completed'
assert webhook(SREF, 'wrong-key').status_code == 401
assert webhook(SREF, 'whsec_platform', ts=time.time() - 3600).status_code == 401
assert webhook(SREF, 'whsec_platform', tamper=True).status_code == 401
with app.app_context(): assert Payment.query.filter_by(provider_id=SREF).one().status == 'pending'
assert webhook(SREF, 'whsec_platform').status_code == 200
with app.app_context():
    p = Payment.query.filter_by(provider_id=SREF).one(); assert p.status == 'paid' and p.voucher and p.channel == 'mpesa'
assert webhook(SREF, 'whsec_platform').status_code == 200             # repeated delivery: no second voucher
with app.app_context(): assert Voucher.query.filter_by(batch='online-payments').count() == 1
# a webhook claiming "completed" when Snippe says otherwise grants nothing
r = buy('0754000224', 'mpesa'); ref2 = r.get_json()['reference']
with app.app_context(): SREF2 = Payment.query.filter_by(reference=ref2).one().provider_id
webhook(SREF2, 'whsec_platform')
with app.app_context(): assert Payment.query.filter_by(reference=ref2).one().status == 'pending'
# ClickPesa payment started before the switch is still checked with ClickPesa
with app.app_context():
    first = Payment.query.filter_by(provider='clickpesa').one()
    assert first.status == 'pending'

# 5. a tenant with their own Snippe account: no fee, their key, their webhook key
sp = co.get('/settings/payments').text
r = co.post('/settings/payments', data={'csrf_token': tok(sp), 'payment_mode': 'own', 'own_provider': 'snippe'}, follow_redirects=True).text
assert 'Enter your Snippe API key' in r
r = co.post('/settings/payments', data={'csrf_token': tok(sp), 'payment_mode': 'own', 'own_provider': 'snippe',
                                        'snippe_api_key': 'snp_tenant', 'snippe_webhook_key': 'whsec_tenant'}, follow_redirects=True).text
assert 'Payment settings saved' in r
assert 'Snippe accepted your keys' in co.post('/settings/payments/test', data={'csrf_token': tok(sp)}, follow_redirects=True).text
r = buy('0754000225', 'mpesa'); ref3 = r.get_json()['reference']
with app.app_context():
    p3 = Payment.query.filter_by(reference=ref3).one()
    assert p3.provider == 'snippe' and p3.provider_account == 'own' and p3.fee_amount == 0
    SREF3 = p3.provider_id
assert sn['payments'][SREF3]['key'] == 'snp_tenant'
sn['payments'][SREF3]['status'] = 'completed'
assert webhook(SREF3, 'whsec_platform').status_code == 401           # the platform key can't confirm a tenant's payment
assert webhook(SREF3, 'whsec_tenant').status_code == 200
with app.app_context(): assert Payment.query.filter_by(reference=ref3).one().status == 'paid'
# wrong keys are reported when testing
with app.app_context():
    import secretbox
    t = db.session.get(Tenant, TID); t.snippe_api_key_enc = secretbox.encrypt('snp_bad'); db.session.commit()
assert 'Snippe rejected the keys' in co.post('/settings/payments/test', data={'csrf_token': tok(sp)}, follow_redirects=True).text

# 6. subscriptions go through SafeNet Pay's provider (Snippe) too
with app.app_context():
    db.session.add(BillingPlan(name='Starter X', price=Decimal(10000), currency='TZS', sort_order=9)); db.session.commit()
    plan_id = BillingPlan.query.filter_by(name='Starter X').one().id
b = co.get('/billing').text
r = co.post('/billing/pay', data={'csrf_token': tok(b), 'plan_id': plan_id, 'months': 1, 'phone': '0754000226'})
with app.app_context():
    s = SubscriptionPayment.query.order_by(SubscriptionPayment.id.desc()).first()
    assert s.method == 'snippe' and s.provider_id and s.status == 'pending', (s.method, s.status, s.message)
    SSUB = s.provider_id
assert sn['payments'][SSUB]['key'] == 'snp_platform'
sn['payments'][SSUB]['status'] = 'completed'
assert webhook(SSUB, 'whsec_platform').status_code == 200
with app.app_context(): assert SubscriptionPayment.query.filter_by(provider_id=SSUB).one().status == 'paid'

# 7. only platform admins can switch, and only to a provider with keys
assert co.post('/platform/payment-provider', data={'csrf_token': tok(b), 'provider': 'clickpesa'}).status_code == 404
config.Config.SNIPPE_API_KEY = ''
pb = cs.get('/platform/billing').text
assert 'Keys not set' in pb
cs.post('/platform/payment-provider', data={'csrf_token': tok(pb), 'provider': 'clickpesa'})
assert 'Add the Snippe keys' in cs.post('/platform/payment-provider', data={'csrf_token': tok(pb), 'provider': 'snippe'}, follow_redirects=True).text

# 8. webhook signature helper
assert snippe.verify_webhook(b'{"a":1}', '100', hmac.new(b'k', b'100.{"a":1}', hashlib.sha256).hexdigest(), 'k', now=100)
assert not snippe.verify_webhook(b'{"a":1}', '100', 'deadbeef', 'k', now=100)
assert not snippe.verify_webhook(b'{"a":1}', '100', hmac.new(b'k', b'100.{"a":1}', hashlib.sha256).hexdigest(), '', now=100)
srv.shutdown()
print('SNIPPE OK')
