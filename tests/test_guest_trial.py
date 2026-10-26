"""'Try free' button: the business chooses time, speed, who and how often; guests tap it and are connected with a
free code made for their phone, which can't be repeated against the business's rules."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel',
                  PUBLIC_URL='https://radius.example.tz')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
from app import app, db
import migrations
from models import Admin, Tenant, Package, Plan, Payment, Voucher
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kariakoo Spot', slug='kariakoo', status='active'); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1')
    db.session.add_all([a, Package(tenant_id=TID, name='Siku 1', price=Decimal(1000), validity_minutes=1440),
                        Plan(tenant_id=TID, name='Trial 2M', group_name='kariakoo-trial', download_speed='2M', upload_speed='1M')])
    tenant_sites(TID)[0].portal_token = 'mktok'
    db.session.commit()
    PLAN = Plan.query.filter_by(name='Trial 2M').one().id

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = html.unescape(c.get('/settings/portal').text)
assert 'Free trial button' in p and 'Off: no free trial button' in p
H = 'https://radius.example.tz'


def guest(mac):
    g = app.test_client()
    g.get(f'/mikrotik/mktok?link-login-only=http://10.5.50.1/login&link-orig=http://example.com/&mac={mac}&ip=10.5.50.20', base_url=H)
    return g


# off: no button
assert 'Try free' not in guest('AA:00:00:00:00:01').get('/mikrotik/mktok', base_url=H).text
r = c.post('/settings/free-trial', data={'csrf_token': tok(p), 'minutes': 30, 'plan_id': PLAN, 'who': 'new', 'every': 'once'}, follow_redirects=True)
assert 'Free trial button switched on: 30 min' in html.unescape(r.text) or 'Free trial button switched on' in html.unescape(r.text)
with app.app_context():
    t = db.session.get(Tenant, TID)
    assert (t.guest_trial_minutes, t.guest_trial_plan_id, t.guest_trial_who, t.guest_trial_every) == (30, PLAN, 'new', 'once')

# a new phone: the button, one tap, connected on the router with a free code at the trial speed
g = guest('AA:00:00:00:00:01')
page = html.unescape(g.get('/mikrotik/mktok', base_url=H).text)
assert 'Try free for 30m' in page or 'Try free for 30 min' in page or 'Try free for' in page
assert 'action="/mikrotik/mktok/trial"' in page
w = html.unescape(g.post('/mikrotik/mktok/trial', base_url=H).text)
with app.app_context():
    v = Voucher.query.filter_by(tenant_id=TID, is_free=True).one()
    assert v.batch == appmod.GUEST_TRIAL_BATCH and v.validity_minutes == 30 and v.plan_id == PLAN and v.first_mac == 'aa:00:00:00:00:01'
    CODE = v.code
assert "free trial" in w.lower() and f'name="username" value="{CODE}"' in w and 'action="http://10.5.50.1/login"' in w
# once per phone
again = html.unescape(g.post('/mikrotik/mktok/trial', base_url=H).text)
assert 'already had a free trial' in again
# new customers only: a phone that has paid before doesn't get it
with app.app_context():
    db.session.add(Payment(tenant_id=TID, reference='SNPAID1', package_name='Siku 1', validity_minutes=1440, phone='255684000111',
                           amount=Decimal(1000), currency='TZS', provider='clickpesa', status='paid', client_mac='AA-00-00-00-00-02'))
    db.session.commit()
assert 'for new customers' in html.unescape(guest('AA:00:00:00:00:02').post('/mikrotik/mktok/trial', base_url=H).text)
# no phone address (not through the router): nothing made
assert 'connect to the Wi-Fi again' in html.unescape(app.test_client().post('/mikrotik/mktok/trial', base_url=H).text)

# everyone, once a day: the paying phone gets it; the first phone again only after a day
c.post('/settings/free-trial', data={'csrf_token': tok(p), 'minutes': 60, 'who': 'all', 'every': 'day'})
assert 'name="username"' in guest('AA:00:00:00:00:02').post('/mikrotik/mktok/trial', base_url=H).text
assert 'already had its free trial today' in html.unescape(guest('AA:00:00:00:00:01').post('/mikrotik/mktok/trial', base_url=H).text)
with app.app_context():
    Voucher.query.filter_by(code=CODE).update({'created_at': datetime.utcnow() - timedelta(hours=25)}); db.session.commit()
w = guest('AA:00:00:00:00:01').post('/mikrotik/mktok/trial', base_url=H).text
assert 'name="username"' in w
# the router (RADIUS / SafeNet's check) accepts the day-two code although the phone had a free code before
with app.app_context():
    v2 = Voucher.query.filter(Voucher.tenant_id == TID, Voucher.first_mac == 'aa:00:00:00:00:01', Voucher.code != CODE).one()
    ok, msg, info = appmod._gateway_authenticate(db.session.get(Tenant, TID), v2.code, v2.code, 'AA:00:00:00:00:01')
    assert ok, msg
    assert v2.plan_id is None                      # no speed chosen this time: no limit
# the gateway box: its settings carry the offer, and SafeNet makes the free code for the phone it names
with app.app_context():
    from models import Gateway
    gw = Gateway(tenant_id=TID, name='Box', key_prefix='gwkey', key_hash=appmod._hash_key('gwkey'), site_id=tenant_sites(TID)[0].id)
    db.session.add(gw); db.session.commit()
api = app.test_client()
cfg = api.get('/api/gateway/config', headers={'X-SafeNet-Key': 'gwkey'}).get_json()
assert cfg['trial'] == {'minutes': 60, 'every': 'day'}
r = api.post('/api/portal/trial', json={'mac': 'AA:00:00:00:00:07', 'ip': '10.10.0.7'}, headers={'X-SafeNet-Key': 'gwkey'})
assert r.status_code == 200 and r.get_json()['minutes'] == 60
with app.app_context():
    assert Voucher.query.filter_by(code=r.get_json()['code']).one().first_mac == 'aa:00:00:00:00:07'
r = api.post('/api/portal/trial', json={'mac': 'AA:00:00:00:00:07'}, headers={'X-SafeNet-Key': 'gwkey'})
assert r.status_code == 403 and 'today' in r.get_json()['error']
assert api.post('/api/portal/trial', json={'mac': 'AA:00:00:00:00:08'}).status_code == 401
# Reyee: the page shows the button and Ruijie's one-click login is set up for it (time, once a day, speed)
c.post('/settings/free-trial', data={'csrf_token': tok(p), 'minutes': 30, 'plan_id': PLAN, 'who': 'all', 'every': 'once'})
with app.app_context():
    lc = appmod._ruijie_load_config(db.session.get(Tenant, TID))
assert lc['custom_html']['login_options'] == ['voucher', 'pass'] and lc['oneclick']['oneclick_validity'] == '30'
assert lc['oneclick']['oneclick_times'] == '1' and lc['oneclick']['oneclick_qos'] == {'up_rate': '1', 'down_rate': '2'}
fresh = app.test_client().get('/app/kariakoo/ruijie.js?s=mktok', base_url=H).text
assert 'trialbox' in fresh and 'Try free for' in fresh

# off again: no button, and the route refuses
c.post('/settings/free-trial', data={'csrf_token': tok(p), 'minutes': 0, 'who': 'all', 'every': 'day'})
assert "isn't available" in html.unescape(guest('AA:00:00:00:00:03').post('/mikrotik/mktok/trial', base_url=H).text)
with app.app_context():
    assert appmod._ruijie_load_config(db.session.get(Tenant, TID))['custom_html']['login_options'] == ['voucher']
print('GUEST TRIAL OK')
