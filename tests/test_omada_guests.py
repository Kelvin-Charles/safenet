"""Site Wi-Fi page: 'Guests on the Wi-Fi now' - each phone the controller sees, checked against the vouchers."""
import html, os, re, sys
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, OMADA_HOSTED_URL='https://127.0.0.1:8043', OMADA_HOSTED_USER='op',
                  OMADA_HOSTED_PASSWORD='op', OMADA_OPENAPI_CLIENT_ID='cid', OMADA_OPENAPI_CLIENT_SECRET='sec')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
class FakeApi:
    def devices(self, site_id): return []
    def clients(self, site_id):
        assert site_id == 'ctl-j'
        return [{'mac': 'AA-BB-CC-00-00-01', 'name': 'Galaxy-Note10', 'ip': '192.168.1.27', 'authStatus': 2, 'active': True},
                {'mac': 'AA-BB-CC-00-00-02', 'name': 'Infinix-HOT-40i', 'ip': '192.168.1.17', 'authStatus': 2, 'active': True},
                {'mac': 'AA-BB-CC-00-00-03', 'name': 'LENIX-Pro', 'ip': '192.168.1.19', 'authStatus': 2, 'active': True},
                {'mac': 'AA-BB-CC-00-00-04', 'name': 'Redmi-A2', 'ip': '192.168.1.30', 'authStatus': 1, 'active': True}]
import app as appmod
appmod._openapi = lambda: FakeApi()
from app import app, db
import migrations
from models import Admin, Tenant, Site, Voucher, RadAcct
from tenancy import tenant_sites
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT Hostel', slug='jriit', status='active'); db.session.add(t); db.session.flush()
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); o.set_password('password1'); db.session.add(o)
    s = tenant_sites(t.id)[0]; s.omada_hosted, s.omada_site_id, s.portal_token = True, 'ctl-j', 'tokj'
    db.session.add_all([Voucher(tenant_id=t.id, code='11112222', validity_minutes=360, batch='x', status='active', first_mac='aa:bb:cc:00:00:01',
                                first_used_at=now - timedelta(hours=1), expires_at=now + timedelta(hours=5)),
                        Voucher(tenant_id=t.id, code='33334444', validity_minutes=60, batch='promo', status='active', is_free=True,
                                first_used_at=now - timedelta(hours=5), expires_at=now - timedelta(hours=4))])
    db.session.add(RadAcct(acctsessionid='p1', acctuniqueid='p1', username='33334444', nasipaddress='1.1.1.1', groupname='', acctterminatecause='Lost-Carrier',
                           calledstationid=f'omada-{s.id}', callingstationid='AA-BB-CC-00-00-02', acctstarttime=now - timedelta(hours=5),
                           acctupdatetime=now - timedelta(hours=4), acctstoptime=now - timedelta(hours=4), acctsessiontime=0, acctinputoctets=0, acctoutputoctets=0))
    db.session.commit(); SID = s.id
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = html.unescape(c.get(f'/sites/{SID}/wifi').text)
assert 'Guests on the Wi-Fi now' in p and '(4)' in p
rows = re.findall(r'<tr>\s*<td>([^<]+)<small.*?</tr>', p, re.S)
assert rows[:3] == ['Infinix-HOT-40i', 'LENIX-Pro', 'Galaxy-Note10'], rows          # problems first
block = lambda name: p[p.index(name):p.index('</tr>', p.index(name))]
assert '33334444' in block('Infinix-HOT-40i') and 'No valid voucher: taken offline' in block('Infinix-HOT-40i') and 'voucher expired' in block('Infinix-HOT-40i')
assert 'No valid voucher' in block('LENIX-Pro') and 'no voucher known for this phone' in block('LENIX-Pro')
assert '11112222' in block('Galaxy-Note10') and 'Valid' in block('Galaxy-Note10') and 'left' in block('Galaxy-Note10')
assert 'At the login page' in block('Redmi-A2') and 'Not online yet' in block('Redmi-A2')
print('OMADA GUESTS OK')
