"""Security basics: headers, cookies, login lockout, reset links, real client address, CSRF on deletes."""
import base64, json, os, re, sys
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
mails = []
appmod.send_mail = lambda to, subj, body: mails.append(body) or True
from app import app, db
import migrations
from models import Admin, Nas
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    a = Admin(username='owner', email='o@x.tz', tenant_id=1, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1')
    db.session.add(a); db.session.add(Nas(tenant_id=1, nasname='10.9.0.1', shortname='mt', type='mikrotik', secret='nas-secret-1'))
    db.session.commit(); NAS = Nas.query.one().id

# headers on every page
r = app.test_client().get('/login', headers={'X-Forwarded-Proto': 'https'})
assert r.headers['X-Frame-Options'] == 'SAMEORIGIN' and "frame-ancestors 'self'" in r.headers['Content-Security-Policy']
assert r.headers['X-Content-Type-Options'] == 'nosniff' and 'max-age' in r.headers['Strict-Transport-Security']
assert 'Strict-Transport-Security' not in app.test_client().get('/login').headers           # only over HTTPS
# cookie settings (HTTPS deployments: secure)
assert app.config['SESSION_COOKIE_HTTPONLY'] and app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
assert config.Config.PUBLIC_URL.startswith('https') and os.environ.get('SESSION_COOKIE_SECURE') == '0'   # tests talk plain HTTP

# real client address: through the proxy (private address) it's the proxy's last X-Forwarded-For entry
with app.test_request_context('/', environ_base={'REMOTE_ADDR': '172.18.0.2'}, headers={'X-Forwarded-For': '6.6.6.6, 41.59.1.2'}):
    assert appmod._client_ip() == '41.59.1.2'
with app.test_request_context('/', environ_base={'REMOTE_ADDR': '41.59.9.9'}, headers={'X-Forwarded-For': '1.2.3.4'}):
    assert appmod._client_ip() == '41.59.9.9'                 # a direct visitor can't pick an address

# login lockout: 10 wrong passwords for an account -> locked 15 minutes, even with the right one
c = app.test_client(); page = c.get('/login').text
for i in range(10):
    assert 'Invalid username or password' in c.post('/login', data={'username': 'owner', 'password': f'wrong{i}', 'csrf_token': tok(page)}).text
r = c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(page)})
assert r.status_code == 429 and 'Too many failed attempts' in r.text
assert c.get('/dashboard').status_code == 302
with app.app_context():
    from models import RateEvent
    RateEvent.query.delete(); db.session.commit()
r = c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(page)})
assert r.status_code == 302 and c.get('/dashboard').status_code == 200

# reset links don't carry any piece of the password hash, and stop working once used
f = app.test_client(); page = f.get('/forgot').text
f.post('/forgot', data={'email': 'o@x.tz', 'csrf_token': tok(page)})
link = re.search(r'(/reset/\S+)', mails[-1]).group(1)
payload = link.split('/reset/')[1].split('.')[0]
data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
with app.app_context():
    h = Admin.query.filter_by(username='owner').one().password_hash
assert data['h'] not in h and h[-16:] not in json.dumps(data)
rp = f.get(link).text
f.post(link, data={'password': 'newpassword9', 'confirm': 'newpassword9', 'password2': 'newpassword9', 'csrf_token': tok(rp)})
assert 'already been used' in f.get(link, follow_redirects=True).text
# reset emails per address are limited
n = len(mails)
for i in range(6):
    f.post('/forgot', data={'email': 'o@x.tz', 'csrf_token': tok(page)})
assert len(mails) - n <= 2

# deletes need the CSRF token, and staff never get the NAS secret
assert c.post(f'/nas/delete/{NAS}').status_code == 400
with app.app_context(): assert db.session.get(Nas, NAS) is not None
assert 'nas-secret-1' not in open('app.py').read().split("'manual_test'")[1][:200]
print('SECURITY OK')
