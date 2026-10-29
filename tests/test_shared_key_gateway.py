"""A gateway box on the older shared key is registered as a gateway of the default business (main site) the first
time it calls, so it shows on the dashboard and can be renamed, moved or switched off like any other."""
import html, os, re, sys
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PORTAL_API_KEY='shared-gw-key')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations
from models import Admin, Gateway
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    TID = migrations.default_tenant().id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1')
    db.session.add(a); db.session.commit()
    assert Gateway.query.count() == 0

api = app.test_client()
H = {'X-SafeNet-Key': 'shared-gw-key'}
assert api.get('/api/gateway/config', headers=H).status_code == 200
assert api.get('/api/gateway/config', headers=H).status_code == 200                # once only
with app.app_context():
    gw = Gateway.query.one()
    assert gw.tenant_id == TID and gw.name == 'SafeNet gateway' and gw.site_id is None and gw.last_seen_at and gw.is_active
    GID = gw.id
assert api.get('/api/gateway/config', headers={'X-SafeNet-Key': 'wrong'}).status_code == 401

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
d = html.unescape(c.get('/dashboard').text)
assert 'SafeNet gateway' in d, d[-2000:]
assert '1 gateway' in html.unescape(c.get('/sites').text)
# switched off: the shared key no longer works (it doesn't fall back to the old way)
with app.app_context():
    db.session.get(Gateway, GID).is_active = False; db.session.commit()
assert api.get('/api/gateway/config', headers=H).status_code == 401
print('SHARED KEY GATEWAY OK')
