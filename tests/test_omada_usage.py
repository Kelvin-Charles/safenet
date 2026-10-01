"""Omada guests' data usage comes from SafeNet's controller (Omada sends no accounting of its own)."""
import os, sys
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
from app import app, db
import migrations
from models import Tenant, Site, RadAcct

class FakeApi:
    def __init__(self): self.calls, self.clients_now = 0, []
    def clients(self, site_id):
        assert site_id == 'ctl-site-1'
        self.calls += 1
        return self.clients_now
api = FakeApi()
appmod._openapi = lambda: api

now = datetime.utcnow()
def session(sid, mac, started):
    return RadAcct(acctsessionid=sid, acctuniqueid=sid, username='11112222', nasipaddress='1.1.1.1', groupname='', acctterminatecause='',
                   calledstationid=f'omada-{SITE}', callingstationid=mac, acctstarttime=started, acctupdatetime=started,
                   acctsessiontime=0, acctinputoctets=0, acctoutputoctets=0)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Furahini', slug='furahini', status='active'); db.session.add(t); db.session.flush()
    s = Site(tenant_id=t.id, name='Camp', portal_token='tokcamp', omada_hosted=True, omada_site_id='ctl-site-1'); db.session.add(s); db.session.flush()
    SITE = s.id
    db.session.add_all([session('a', 'AA-BB-CC-00-00-01', now - timedelta(minutes=30)),
                        session('b', 'AA-BB-CC-00-00-02', now - timedelta(minutes=30)),
                        session('c', 'AA-BB-CC-00-00-03', now - timedelta(seconds=20))])     # just logged in
    db.session.commit()

api.clients_now = [{'mac': 'AA-BB-CC-00-00-01', 'ip': '10.20.0.5', 'trafficDown': 50_000_000, 'trafficUp': 4_000_000, 'active': True},
                   {'mac': 'AA-BB-CC-00-00-02', 'trafficDown': 1_000, 'trafficUp': 500, 'active': False}]
with app.app_context():
    appmod._omada_sync_due()
    a, b, c = (RadAcct.query.filter_by(acctsessionid=x).one() for x in 'abc')
    assert a.acctoutputoctets == 50_000_000 and a.acctinputoctets == 4_000_000 and a.framedipaddress == '10.20.0.5'
    assert a.acctstoptime is None and (datetime.utcnow() - a.acctupdatetime).total_seconds() < 5 and a.acctsessiontime >= 1790
    assert b.acctstoptime is not None and b.acctterminatecause == 'Lost-Carrier'      # left: closed
    assert c.acctstoptime is None                                                    # too new to judge
assert api.calls == 1
# within the minute: no second call (all workers share the claim)
with app.app_context(): appmod._omada_sync_due()
assert api.calls == 1

# more traffic, then the phone reconnects and the controller's counters restart
with app.app_context():
    db.session.get(Site, SITE).omada_synced_at = None; db.session.commit()
    api.clients_now = [{'mac': 'aa:bb:cc:00:00:01', 'trafficDown': 80_000_000, 'trafficUp': 6_000_000, 'active': True}]
    appmod._omada_sync_due()
    assert RadAcct.query.filter_by(acctsessionid='a').one().acctoutputoctets == 80_000_000
    db.session.get(Site, SITE).omada_synced_at = None; db.session.commit()
    api.clients_now = [{'mac': 'AA-BB-CC-00-00-01', 'trafficDown': 2_000_000, 'trafficUp': 100_000, 'active': True}]
    appmod._omada_sync_due()
    a = RadAcct.query.filter_by(acctsessionid='a').one()
    assert a.acctoutputoctets == 82_000_000 and a.acctinputoctets == 6_100_000, (a.acctoutputoctets, a.acctinputoctets)

# the dashboard and live view now show the usage
with app.app_context():
    from models import Admin
    o = Admin(username='owner', email='o@x.tz', tenant_id=db.session.get(Site, SITE).tenant_id, role='owner', email_verified_at=now)
    o.set_password('password1'); db.session.add(o)
    from models import Voucher
    db.session.add(Voucher(tenant_id=o.tenant_id, code='11112222', validity_minutes=1440, batch='x', status='active',
                           first_used_at=now - timedelta(minutes=30), expires_at=now + timedelta(hours=20)))
    db.session.commit()
import re
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
cl = app.test_client(); r = cl.get('/login'); cl.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
live = cl.get('/api/live').get_json()
assert [o['down'] for o in live['online'] if o['mac'] == 'AA-BB-CC-00-00-01'] == [82_000_000], live['online']
print('OMADA USAGE OK')
