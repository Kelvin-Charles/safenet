import os, re, sys, json, base64, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, NEXTSMS_USERNAME='user', NEXTSMS_PASSWORD='pass', NEXTSMS_SENDER_ID='Safezone',
                  NEXTSMS_URL='http://127.0.0.1:38111/api/sms/v1/text/single', CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k')
sys.path.insert(0, os.getcwd())
got, status = [], {'code': 200}
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        got.append((self.headers['Authorization'], json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
        self.send_response(status['code']); self.end_headers(); self.wfile.write(b'{"messages":[{"status":{"name":"PENDING"}}]}')
    def log_message(self, *a): pass
srv = HTTPServer(('127.0.0.1', 38111), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
import sms
assert sms.send_sms('255712345678', 'hello', 'REF1') is True
auth, body = got[-1]
assert auth == 'Basic ' + base64.b64encode(b'user:pass').decode() and body == {'from': 'Safezone', 'to': '255712345678', 'text': 'hello', 'reference': 'REF1'}
status['code'] = 401; assert sms.send_sms('255712345678', 'x') is False; status['code'] = 200
assert sms.send_sms('', 'x') is False
import config; config.Config.NEXTSMS_USERNAME = ''; assert sms.send_sms('255712345678', 'x') is False; config.Config.NEXTSMS_USERNAME = 'user'

# flows
config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['M-PESA']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS'}
texts = []
import app as appmod
appmod.send_sms_async = lambda to, text, ref=None: texts.append((to, text))
appmod.send_mail = lambda *a: True
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Package, Gateway, BillingPlan, Withdrawal, Payment
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf-token" content="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run(); __import__("models").BillingPlan.query.delete(); db.session.commit()
    t = Tenant(name='Cafe', slug='cafe', status='active', hotspot_name='Salma WiFi', support_phone='0755111222', phone='0713000000'); db.session.add(t); db.session.flush()
    db.session.add_all([Package(tenant_id=t.id, name='Day', price=Decimal(1000), validity_minutes=1440),
                        Gateway(tenant_id=t.id, name='gw', key_prefix='sgw_x', key_hash=_hash_key('sgw_x')),
                        BillingPlan(name='Starter', price=Decimal(20000))])
    for u, tid, sa in (('owner1', t.id, False), ('platform', 1, True)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=tid, role='owner', is_superadmin=sa, email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    db.session.commit(); A = t.id; pkg = Package.query.one().id; plan = BillingPlan.query.one().id
api = app.test_client(); H2 = {'X-SafeNet-Key': 'sgw_x'}
ref = api.post('/api/portal/purchase', headers=H2, json={'package_id': pkg, 'phone': '0712345678'}).get_json()['reference']
code = api.get(f'/api/portal/purchase/{ref}', headers=H2).get_json()['code']
to, text = texts[-1]
assert to == '255712345678' and code in text and 'Salma WiFi' in text and '1 day' in text and '0755111222' in text, texts
api.get(f'/api/portal/purchase/{ref}', headers=H2); assert len(texts) == 1          # only once
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text).group(1)}); return c
co = login('owner1')
r = co.post('/billing/pay', data={'csrf_token': tok(co.get('/billing').text), 'plan_id': plan, 'months': 1, 'phone': '0654000111'})
sref = r.headers['Location'].rsplit('/', 1)[1]; co.get(f'/billing/payments/{sref}/status')
assert texts[-1][0] == '255654000111' and 'paid until' in texts[-1][1] and sref in texts[-1][1]
with app.app_context():
    db.session.add(Withdrawal(tenant_id=A, amount=Decimal(900), phone='255688000000')); db.session.commit(); wid = Withdrawal.query.one().id
cp = login('platform')
cp.post(f'/platform/payouts/{wid}', data={'csrf_token': tok(cp.get('/platform/payouts').text), 'action': 'paid', 'reference': 'MP9'})
assert texts[-1] == ('255688000000', 'SafeNet: TZS 900 has been sent to this number. Ref MP9.')
srv.shutdown(); print('SMS OK')
