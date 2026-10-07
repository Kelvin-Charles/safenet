"""Platform settings in Platform: Billing: trial days, SafeNet Pay fee, SMS price, minimum withdrawal, grace days."""
import html, os, re, sys
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, TRIAL_DAYS='14', PLATFORM_FEE_PERCENT='3', SMS_PRICE='30', SIGNUP_ENABLED='true')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
appmod.send_mail = lambda *a, **k: True
from app import app, db
import migrations
from models import Admin, Tenant, PlatformSetting
from config import Config
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    a = Admin(username='boss', email='b@x.tz', tenant_id=1, role='owner', is_superadmin=True, email_verified_at=datetime.utcnow()); a.set_password('password1')
    t = Tenant(name='Zulu', slug='zulu', status='active'); db.session.add_all([a, t]); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=datetime.utcnow()); o.set_password('password1')
    db.session.add(o); db.session.commit()
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
cs = login('boss')
p = html.unescape(cs.get('/platform/billing').text)
assert 'Platform settings' in p and 'Free trial for new businesses (days)' in p and 'value="14"' in p and 'Server default: 14' in p
form = {'csrf_token': tok(p), 'TRIAL_DAYS': '30', 'PLATFORM_FEE_PERCENT': '4.5', 'SMS_PRICE': '25', 'MIN_WITHDRAWAL': '3,000', 'BILLING_GRACE_DAYS': '5'}
# out of range or not a number: refused, nothing saved
assert 'between 0 and 365' in html.unescape(cs.post('/platform/settings', data={**form, 'TRIAL_DAYS': '999'}, follow_redirects=True).text)
assert 'enter a number' in cs.post('/platform/settings', data={**form, 'SMS_PRICE': 'abc'}, follow_redirects=True).text
with app.app_context(): assert PlatformSetting.query.filter(PlatformSetting.key.like('cfg:%')).count() == 0
r = html.unescape(cs.post('/platform/settings', data=form, follow_redirects=True).text)
assert 'Platform settings saved' in r and 'value="30"' in r and 'value="4.5"' in r
assert (Config.TRIAL_DAYS, Config.PLATFORM_FEE_PERCENT, Config.SMS_PRICE, Config.MIN_WITHDRAWAL, Config.BILLING_GRACE_DAYS) == (30, 4.5, 25, 3000, 5)
# used straight away: the landing page and a new sign-up get the 30-day trial
assert '30-day free trial' in app.test_client().get('/').text
sg = app.test_client(); f = sg.get('/signup').text
sg.post('/signup', data={'csrf_token': tok(f), 'business_name': 'New Cafe', 'username': 'newcafe', 'email': 'n@x.tz', 'phone': '0712345678',
                         'password': 'password123', 'confirm': 'password123', 'accept': 'y'})
with app.app_context():
    nt = Tenant.query.filter_by(name='New Cafe').one()
    assert 29 <= (nt.trial_ends_at - datetime.utcnow()).days <= 30, nt.trial_ends_at
# another worker (fresh process memory) picks the saved values up from the database
Config.TRIAL_DAYS = 14; appmod._knobs_loaded_at[0] = 0
app.test_client().get('/login')
assert Config.TRIAL_DAYS == 30
# only the platform admin
assert login('owner').post('/platform/settings', data=form).status_code in (302, 404)
with app.app_context(): assert db.session.get(PlatformSetting, 'cfg:TRIAL_DAYS').value == '30'
print('PLATFORM SETTINGS OK')
