"""Advanced: a business's own login to SafeNet's Omada Controller, limited to its sites; portal settings view-only."""
import html, os, re, sys
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, OMADA_HOSTED_URL='https://127.0.0.1:8043', OMADA_HOSTED_USER='op',
                  OMADA_HOSTED_PASSWORD='op', OMADA_OPENAPI_CLIENT_ID='cid', OMADA_OPENAPI_CLIENT_SECRET='sec')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import omada

# the role: nothing controller-wide, view-only for what SafeNet manages
p = omada.BUSINESS_PRIVILEGE
assert all(p[k] == 0 for k in ('globalSetting', 'users', 'roles', 'license', 'globalDashboard', 'samlSsos', 'globalSecurity', 'sdWan'))
assert p['network'] == 1 and p['hotspot'] == 1 and p['devices'] == 2 and p['clients'] == 2 and p['dashboard'] == 1
# passwords the controller accepts (upper, lower, digit, symbol; no quote, space or '?')
for _ in range(50):
    pw = omada.business_password()
    assert len(pw) == 16 and re.search('[A-Z]', pw) and re.search('[a-z]', pw) and re.search(r'\d', pw) and re.search(r'[!#$%&*@^]', pw)
    assert not re.search(r'[\s"?]', pw)

class FakeApi:
    def __init__(self): self.calls = []; self.taken = set()
    def ensure_business_role(self): self.calls.append(('role',)); return 'role-1'
    def create_business_user(self, name, password, role_id, sites):
        self.calls.append(('create', name, password, role_id, list(sites)))
        if name in self.taken: raise omada.OmadaError('controller refused /users: name already exists')
        return 'user-9'
    def update_business_user(self, user_id, name, role_id, sites, password=None):
        self.calls.append(('update', user_id, name, role_id, list(sites), password))
api = FakeApi()
import app as appmod
appmod._openapi = lambda: api
from app import app, db
import migrations, secretbox
from models import Admin, Tenant, Site
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT Hostel', slug='jriit', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    for u, role in (('owner', 'owner'), ('staffer', 'staff')):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=TID, role=role, email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    main = tenant_sites(TID)[0]
    db.session.commit(); MAIN = main.id
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
c = login('owner')
p = c.get('/sites').text
assert 'Advanced: your Omada dashboard' not in p                               # no Omada site yet
assert 'first' in html.unescape(c.post('/sites/omada-login', data={'csrf_token': tok(p)}, follow_redirects=True).text)
with app.app_context():
    s = db.session.get(Site, MAIN); s.omada_hosted = True; s.omada_site_id = 'ctl-a'; db.session.commit()
p = c.get('/sites').text
assert 'Advanced: your Omada dashboard' in p and 'Create my Omada login' in p
api.taken.add('sn-jriit')                                                         # a login with that name already exists
r = html.unescape(c.post('/sites/omada-login', data={'csrf_token': tok(p)}, follow_redirects=True).text)
assert 'Your Omada login is ready' in r
creates = [x for x in api.calls if x[0] == 'create']
assert creates[0][1] == 'sn-jriit' and creates[1][1].startswith('sn-jriit-') and creates[1][3] == 'role-1' and creates[1][4] == ['ctl-a']
with app.app_context():
    t = db.session.get(Tenant, TID); PW = secretbox.decrypt(t.omada_password_enc)
    assert t.omada_user_id == 'user-9' and t.omada_login == creates[1][1] and PW == creates[1][2] and PW not in (t.omada_password_enc or '')
p = c.get('/sites').text
assert f'<code id="om-user">{creates[1][1]}</code>' in p and f'data-pass="{PW}"' in html.unescape(p) and 'https://omada.safezonetz.com' in p
# new password
c.post('/sites/omada-login', data={'csrf_token': tok(p)})
upd = [x for x in api.calls if x[0] == 'update'][-1]
assert upd[1] == 'user-9' and upd[4] == ['ctl-a'] and upd[5] and upd[5] != PW
# a second Omada site joins the same login
with app.app_context():
    s2 = Site(tenant_id=TID, name='Block B'); db.session.add(s2); db.session.commit()
    class ProvisionApi(FakeApi):
        def find_site(self, name): return 'ctl-b'
        def ensure_ssid(self, *a): return 'ssid-1'
        def ensure_portal(self, *a): pass
        def ensure_pre_auth(self, *a): pass
        def ensure_operator_site(self, *a): pass
    api2 = ProvisionApi(); appmod._openapi = lambda: api2
    appmod._omada_provision(s2, db.session.get(Tenant, TID), 'JRIIT Guest'); db.session.commit()
    assert [x for x in api2.calls if x[0] == 'update'][-1][4] == ['ctl-a', 'ctl-b']
# staff don't see it and can't make one
st = login('staffer')
assert 'om-pass' not in st.get('/sites').text
assert st.post('/sites/omada-login', data={'csrf_token': tok(st.get('/sites').text)}).status_code == 302
print('OMADA LOGIN OK')
