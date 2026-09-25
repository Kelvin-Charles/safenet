import os, re, sys
os.environ['DB_PASSWORD'] = 'x'
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
from app import app, db
from models import Admin, Plan, Voucher, RadCheck, RadUserGroup
from datetime import datetime, timedelta

app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True)
# re-init engine for new URI
with app.app_context():
    db.engine.dispose()
c = app.test_client()
def tok(html):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1)

with app.app_context():
    db.create_all(); __import__('migrations').run()
    a = Admin(username='admin', email='a@b.c', role='owner', tenant_id=__import__('migrations').default_tenant().id,
              email_verified_at=__import__('datetime').datetime.utcnow()); a.set_password('pw'); db.session.add(a)
    db.session.add(Plan(name='Daily5M')); db.session.commit(); __import__('migrations').run()
    plan_id = Plan.query.first().id

r = c.get('/login'); r = c.post('/login', data={'username':'admin','password':'pw','csrf_token':tok(r.text)}, follow_redirects=True)
assert 'Dashboard' in r.text, r.text[:300]

r = c.get('/vouchers/generate'); assert r.status_code == 200
r = c.post('/vouchers/generate', data={'csrf_token':tok(r.text),'plan_id':plan_id,'count':5,'validity_value':1,'validity_unit':'days','price':'1000','batch':'cafe-1','max_devices':1}, follow_redirects=True)
assert '5 vouchers created' in r.text, r.text[:2000]
# bad input
r2 = c.get('/vouchers/generate'); r2 = c.post('/vouchers/generate', data={'csrf_token':tok(r2.text),'plan_id':0,'count':900,'validity_value':1,'validity_unit':'hours','price':'abc'})
assert 'between 1 and 500' in r2.text and 'Price must be a number' in r2.text

with app.app_context():
    vs = Voucher.query.all(); assert len(vs) == 5
    v = vs[0]
    assert len(v.code) == 8 and v.code.isdigit() and v.validity_minutes == 1440
    assert RadCheck.query.filter_by(username=v.code, attribute='Cleartext-Password', value=v.code).count() == 1
    assert RadUserGroup.query.filter_by(username=v.code, groupname='Daily5M').count() == 1
    # simulate FreeRADIUS activation on one, expiry on another
    vs[1].status='active'; vs[1].first_used_at=datetime.utcnow(); vs[1].expires_at=datetime.utcnow()+timedelta(hours=3, minutes=5)
    vs[2].status='active'; vs[2].first_used_at=datetime.utcnow()-timedelta(days=2); vs[2].expires_at=datetime.utcnow()-timedelta(days=1)
    db.session.commit()
    ids = [x.id for x in vs]; codes=[x.code for x in vs]

r = c.get('/vouchers'); assert r.status_code == 200
assert '3h 4m left' in r.text or '3h 5m left' in r.text, 'remaining'
assert 'Expired' in r.text and 'Unused' in r.text
assert '2,000' in r.text  # sold value: 2 used x 1000
for st in ['unused','active','expired','disabled']:
    assert c.get(f'/vouchers?state={st}').status_code == 200
r = c.get('/vouchers?state=expired'); assert codes[2] in r.text and codes[0] not in r.text
r = c.get('/vouchers?batch=cafe-1'); assert 'Print unused' in r.text

r = c.get('/vouchers/print?batch=cafe-1'); assert r.status_code == 200
assert r.text.count('class="voucher"') == 3 and 'TZS 1,000' in r.text and 'Valid 1 day from first login' in r.text

# CSRF enforced
assert c.post(f'/vouchers/{ids[0]}/toggle').status_code == 400
t = tok(c.get('/vouchers').text)
c.post(f'/vouchers/{ids[0]}/toggle', data={'csrf_token':t})
with app.app_context(): assert Voucher.query.get(ids[0]).status == 'disabled'
c.post(f'/vouchers/{ids[0]}/toggle', data={'csrf_token':t})
with app.app_context(): assert Voucher.query.get(ids[0]).status == 'unused'
r = c.post(f'/vouchers/{ids[3]}/delete', data={'csrf_token':t}, follow_redirects=True)
assert f'Voucher {codes[3]} deleted' in r.text
with app.app_context(): assert RadCheck.query.filter_by(username=codes[3]).count()==0
r = c.post('/vouchers/delete-unused', data={'csrf_token':t,'batch':'cafe-1'}, follow_redirects=True)
assert 'Deleted 2 unused' in r.text
with app.app_context(): assert Voucher.query.count()==2

# Portal is public
c2 = app.test_client()
r = c2.get('/portal'); assert r.status_code==200 and 'How to connect' in r.text and 'PEAP' in r.text
r = c2.get('/portal?link-login-only=http://10.5.50.1/login&link-orig=http://example.com/&error=invalid+code')
assert 'action="http://10.5.50.1/login"' in r.text and 'invalid code' in r.text and 'name="dst"' in r.text
r = c2.get('/portal?login_url=https://n260.network-auth.com/splash/login&continue_url=https://x.com')
assert 'network-auth.com' in r.text and 'name="success_url"' in r.text
r = c2.get('/portal?link-login-only=https://evil.example.com/steal'); assert 'How to connect' in r.text and 'evil' not in r.text
r = c2.get('/portal?login_url=javascript:alert(1)'); assert 'javascript' not in r.text
assert c2.get('/vouchers').status_code == 302  # admin pages still need login
print('ALL OK')
