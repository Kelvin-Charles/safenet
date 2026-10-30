"""MikroTik hotspot with SafeNet's login page: the router's login.html sends guests to SafeNet, they buy with mobile
money or type a voucher, and the code is posted back to the router (which asks SafeNet's RADIUS)."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel',
                  PUBLIC_URL='https://radius.example.tz')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
pay = {'status': 'PROCESSING'}
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': pay['status'], 'collectedAmount': '1000'}
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
from app import app, db
import migrations
from models import Admin, Tenant, Package, Payment
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kariakoo Spot', slug='kariakoo', status='active'); db.session.add(t); db.session.flush()
    a = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=datetime.utcnow())
    a.set_password('password1'); db.session.add(a)
    db.session.add(Package(tenant_id=t.id, name='Siku 1', price=Decimal(1000), validity_minutes=1440))
    site = tenant_sites(t.id)[0]; site.portal_token = 'mktok'
    db.session.commit()
    PKG = Package.query.filter_by(name='Siku 1').one().id

g = app.test_client()
H = 'https://radius.example.tz'
# the router's login.html: sends the guest to SafeNet with the router's own values
f = g.get('/mikrotik/mktok/login.html', base_url=H)
assert f.status_code == 200 and 'action="https://radius.example.tz/mikrotik/mktok"' in f.text
assert 'value="$(link-login-only)"' in f.text and 'value="$(mac)"' in f.text and 'document.sn.submit()' in f.text
assert g.get('/mikrotik/nope/login.html', base_url=H).status_code == 404

# only a local hotspot can be the login link
assert g.get('/mikrotik/mktok?link-login-only=https://evil.example.com/login', base_url=H).status_code == 400
r = g.get('/mikrotik/mktok?link-login-only=http://10.5.50.1/login&link-orig=http://example.com/&mac=AA:BB:CC:00:00:09&ip=10.5.50.20',
          base_url=H)
assert r.status_code == 302
p = html.unescape(g.get('/mikrotik/mktok', base_url=H).text)
assert 'Siku 1' in p and 'Buy package' in p and 'action="http://10.5.50.1/login"' in p       # vouchers go straight to the router
assert 'action="/mikrotik/mktok/buy"' in p
# a wrong code: the router comes back with its error, shown on the voucher tab
p = html.unescape(g.get('/mikrotik/mktok?link-login-only=http://10.5.50.1/login&error=invalid+username+or+password',
                        base_url=H, follow_redirects=True).text)
assert 'invalid username or password' in p.lower()

# buying: then the phone is logged in on the router with the new code
b = g.post('/mikrotik/mktok/buy', data={'package_id': PKG, 'phone': '0684000111', 'network': 'airtel', 'agree': '1'}, base_url=H)
assert b.status_code == 302 and '/mikrotik/mktok/buy/wait?ref=' in b.headers['Location']
ref = b.headers['Location'].split('ref=')[1]
w = html.unescape(g.get(f'/mikrotik/mktok/buy/wait?ref={ref}', base_url=H).text)
assert '/mikrotik/mktok/buy/wait?ref=' in w                                          # waits for the PIN
with app.app_context():
    assert Payment.query.filter_by(reference=ref).one().client_mac == 'AA:BB:CC:00:00:09'
pay['status'] = 'SUCCESS'
with app.app_context():                  # SafeNet asks the provider at most every few seconds
    Payment.query.filter_by(reference=ref).update({'checked_at': None}); db.session.commit()
w = html.unescape(g.get(f'/mikrotik/mktok/buy/wait?ref={ref}', base_url=H).text)
with app.app_context():
    code = Payment.query.filter_by(reference=ref).one().voucher.code
assert code in w and 'action="http://10.5.50.1/login"' in w and f'name="username" value="{code}"' in w
assert 'name="dst" value="http://example.com/"' in w and 'document.getElementById("mk").submit()' in w
assert html.unescape(g.get(f'/mikrotik/mktok/buy/wait?ref={ref}', base_url=H, follow_redirects=False).text) != w   # not shown twice
assert g.post('/mikrotik/mktok/buy', data={'package_id': PKG, 'phone': '0684000111'}, base_url=H).status_code == 200   # no agree: page

# the phone comes back later (left the Wi-Fi, came back): its paid code still has time, so it's logged straight back in
back = lambda mac, error='': html.unescape(app.test_client().get(
    f'/mikrotik/mktok?link-login-only=http://10.5.50.1/login&link-orig=http://example.com/&mac={mac}&error={error}',
    base_url=H, follow_redirects=True).text)
r = back('AA:BB:CC:00:00:09')
assert 'Welcome back' in r and f'name="username" value="{code}"' in r and 'submit();},0)' in r and 'Buy package' not in r
# the router turned it down (e.g. kicked by the business): the page, not a loop
assert 'Buy package' in back('AA:BB:CC:00:00:09', 'invalid+username+or+password')
# a code typed on another day: found from the router's sessions (MikroTik writes the address with colons)
from models import RadAcct, Voucher
with app.app_context():
    tid = Tenant.query.filter_by(slug='kariakoo').one().id
    typed = appmod._create_vouchers(1, None, 1440, Decimal(1000), 'cards', tenant=tid)[0]
    typed.status, typed.first_used_at, typed.expires_at = 'active', datetime.utcnow(), datetime.utcnow() + timedelta(hours=5)
    db.session.add(RadAcct(acctsessionid='m1', acctuniqueid='m1', username=typed.code, nasipaddress='10.66.0.5', groupname='',
                           acctterminatecause='', calledstationid='hotspot1', callingstationid='AA:BB:CC:00:00:22',
                           acctstarttime=datetime.utcnow() - timedelta(hours=1), acctstoptime=datetime.utcnow(),
                           acctsessiontime=3600, acctinputoctets=0, acctoutputoctets=0))
    db.session.commit(); TYPED = typed.code
assert f'value="{TYPED}"' in back('AA:BB:CC:00:00:22')
# used up: the login page as usual
with app.app_context():
    Voucher.query.filter_by(code=TYPED).update({'expires_at': datetime.utcnow() - timedelta(minutes=1)}); db.session.commit()
assert 'Buy package' in back('AA:BB:CC:00:00:22')
assert 'Buy package' in back('AA:BB:CC:00:00:99')                # a new phone

# the router's setup script installs the page
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
with app.app_context():
    from models import Router, VpnServer
    db.session.add(VpnServer(id=1, public_key='PUB', listen_port=51820))
    rt = Router(tenant_id=Tenant.query.filter_by(slug='kariakoo').one().id, name='Kariakoo', vendor='mikrotik',
                tunnel_ip='10.66.0.5', public_key='RPUB', private_key_enc=appmod.secretbox.encrypt('PRIV'))
    db.session.add(rt); db.session.commit(); RID = rt.id
s = html.unescape(c.get(f'/routers/{RID}/script').text)
assert '/ip hotspot walled-garden ip add action=accept dst-host=radius.example.tz' in s
assert '/tool fetch url="https://radius.example.tz/mikrotik/mktok/login.html" dst-path=($d . "/login.html")' in s
assert 'login-by=http-chap,http-pap,cookie' in s
assert '/ip firewall filter add chain=forward hotspot=from-client ttl=equal:63 action=drop' in s     # no hotspot sharing (on by default)
print('MIKROTIK PORTAL OK')
