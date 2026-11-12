"""App-store pages: the privacy policy and deleting an account (web form, the app for businesses and Wi-Fi customers,
and the platform's list of requests)."""
import os, re, sys
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as core
from app import app, db
import migrations
from models import Admin, Tenant, DeletionRequest
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
mails = []
core.send_mail = lambda to, subject, body: mails.append((to, subject, body)) or True
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kpstar', slug='kpstar', status='active'); db.session.add(t); db.session.flush()
    for u, role, sup in (('owner1', 'owner', False), ('boss', 'owner', True)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=None if sup else t.id, role=role, is_superadmin=sup, email_verified_at=now)
        a.set_password('password1'); db.session.add(a)
    db.session.commit(); TID = t.id

c = app.test_client()
p = c.get('/privacy'); assert p.status_code == 200
for w in ('Privacy policy', 'Sera ya faragha', 'Personal Data Protection Act', 'ClickPesa', '/delete-account', 'not made for children'):
    assert w in p.text, w
land = c.get('/').text; assert '/privacy' in land and '/delete-account' in land

# the web form
f = c.get('/delete-account'); assert f.status_code == 200 and 'Futa akaunti yako' in f.text and 'What is kept' in f.text
assert c.post('/delete-account', data={'kind': 'guest', 'account': '0712345678'}).status_code == 400            # CSRF
r = c.post('/delete-account', data={'csrf_token': tok(f.text), 'kind': 'guest', 'account': 'x'}); assert 'phone number you buy' in r.text
r = c.post('/delete-account', data={'csrf_token': tok(f.text), 'kind': 'business', 'account': 'owner1'}); assert 'reach you' in r.text
r = c.post('/delete-account', data={'csrf_token': tok(f.text), 'kind': 'guest', 'account': '0712 345 678', 'reason': 'Not using it'})
assert r.status_code == 200 and 'Request received' in r.text
with app.app_context():
    req = DeletionRequest.query.one(); assert req.kind == 'guest' and req.account == '0712 345 678' and not req.verified and req.source == 'web'
assert mails and mails[-1][0] == 'boss@x.tz' and '0712 345 678' in mails[-1][2]
for i in range(6):
    r = c.post('/delete-account', data={'csrf_token': tok(f.text), 'kind': 'guest', 'account': f'07123456{i:02d}'})
assert 'Too many requests' in r.text

# the app: a business account
r = c.post('/api/m/login', json={'username': 'owner1', 'password': 'password1'}); H = {'Authorization': f"Bearer {r.get_json()['token']}"}
assert c.post('/api/m/account/delete', json={}).status_code == 401
r = c.post('/api/m/account/delete', headers=H, json={'reason': 'closing'}); assert r.status_code == 200 and 'within 30 days' in r.get_json()['message']
with app.app_context():
    req = DeletionRequest.query.filter_by(source='app').one()
    assert req.kind == 'business' and req.verified and req.tenant_id == TID and 'owner1' in req.account
# the app: a Wi-Fi customer (signed in with a voucher code token)
with app.app_context():
    gtok = core._tokens('mobile-guest').dumps({'v': ['12345678']})
assert c.post('/api/m/guest/account/delete', headers={'Authorization': 'Bearer junk'}).status_code == 401
r = c.post('/api/m/guest/account/delete', headers={'Authorization': f'Bearer {gtok}', 'Accept-Language': 'sw'})
assert r.status_code == 200 and 'siku 30' in r.get_json()['message']
with app.app_context(): assert DeletionRequest.query.filter_by(kind='guest', source='app').one().account == '12345678'

# the platform team's list
o = app.test_client(); lp = o.get('/login'); o.post('/login', data={'username': 'owner1', 'password': 'password1', 'csrf_token': tok(lp.text)})
assert o.get('/platform/deletions').status_code == 404                     # not for businesses
b = app.test_client(); lp = b.get('/login'); b.post('/login', data={'username': 'boss', 'password': 'password1', 'csrf_token': tok(lp.text)})
page = b.get('/platform/deletions'); assert page.status_code == 200 and '0712 345 678' in page.text and 'Signed in' in page.text
with app.app_context(): rid = DeletionRequest.query.filter_by(source='app', kind='business').one().id
r = b.post('/platform/deletions', data={'csrf_token': tok(page.text), 'id': rid, 'status': 'done', 'note': 'tenant removed'}); assert r.status_code == 302
with app.app_context():
    req = db.session.get(DeletionRequest, rid); assert req.status == 'done' and req.done_at and req.note == 'tenant removed'
print('ACCOUNT DELETION OK')
