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
    def __init__(self): self.calls, self.clients_now, self.cut = 0, [], []
    def unauth(self, site_id, mac): self.cut.append(mac)
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

# --- a hostel: phones drop off for a moment, and the controller lets paid phones back in without the login page
from models import SessionKick
def sync(clients):
    with app.app_context():
        db.session.get(Site, SITE).omada_synced_at = None; db.session.commit()
        api.clients_now = clients
        appmod._omada_sync_due()
with app.app_context():
    s = db.session.get(Site, SITE); TENANT = s.tenant_id
    for code, minutes in (('30304040', 600), ('50506060', 600), ('70708080', 600)):
        db.session.add(Voucher(tenant_id=TENANT, code=code, validity_minutes=minutes, batch='x', status='active',
                               first_used_at=now - timedelta(minutes=20), expires_at=now + timedelta(hours=9)))
    db.session.add_all([session('h1', 'AA-BB-CC-00-00-11', now - timedelta(minutes=20)),
                        session('h2', 'AA-BB-CC-00-00-12', now - timedelta(minutes=20))])
    db.session.commit()
    RadAcct.query.filter_by(acctsessionid='h1').update({'username': '30304040', 'acctupdatetime': now - timedelta(minutes=3)})
    RadAcct.query.filter_by(acctsessionid='h2').update({'username': '50506060'})
    db.session.commit()
on = lambda mac, **kw: {'mac': mac, 'trafficDown': 1000, 'trafficUp': 100, 'active': True, 'authStatus': 2, **kw}
# h1 missing for 3 minutes: still a session (walking between rooms); h2 missing for 20 minutes: closed
sync([])
with app.app_context():
    assert RadAcct.query.filter_by(acctsessionid='h1').one().acctstoptime is None
    assert RadAcct.query.filter_by(acctsessionid='h2').one().acctterminatecause == 'Lost-Carrier'
# h2's phone is back, let in by the controller (no login page): counted again on its voucher
sync([on('AA-BB-CC-00-00-11'), on('AA-BB-CC-00-00-12', ip='10.20.0.40')])
with app.app_context():
    back = RadAcct.query.filter(RadAcct.callingstationid == 'AA-BB-CC-00-00-12', RadAcct.acctstoptime.is_(None)).all()
    assert len(back) == 1 and back[0].username == '50506060' and back[0].calledstationid == f'omada-{SITE}' and back[0].framedipaddress == '10.20.0.40'
    assert back[0].acctoutputoctets == 1000                       # its traffic counts from the next read on
    assert RadAcct.query.filter(RadAcct.callingstationid == 'AA-BB-CC-00-00-11', RadAcct.acctstoptime.is_(None)).count() == 1   # not doubled
# not counted back: still waiting at the login page, a finished voucher, or a code the owner disconnected
with app.app_context():
    db.session.add_all([session('k1', 'AA-BB-CC-00-00-13', now - timedelta(minutes=40)), session('k2', 'AA-BB-CC-00-00-14', now - timedelta(minutes=40)),
                        session('k3', 'AA-BB-CC-00-00-15', now - timedelta(minutes=40))])
    db.session.commit()
    for sid, code in (('k1', '70708080'), ('k2', '70708080'), ('k3', '99999999')):
        RadAcct.query.filter_by(acctsessionid=sid).update({'username': code, 'acctstoptime': now - timedelta(minutes=30), 'acctterminatecause': 'Lost-Carrier'})
    db.session.add(SessionKick(tenant_id=TENANT, username='70708080', created_at=now - timedelta(minutes=35)))
    db.session.commit()
sync([on('AA-BB-CC-00-00-11'), on('AA-BB-CC-00-00-12'), on('AA-BB-CC-00-00-13'), on('AA-BB-CC-00-00-14'),
      on('AA-BB-CC-00-00-15'), on('AA-BB-CC-00-00-16', authStatus=1)])
with app.app_context():
    for mac in ('AA-BB-CC-00-00-13', 'AA-BB-CC-00-00-14', 'AA-BB-CC-00-00-15', 'AA-BB-CC-00-00-16'):
        assert RadAcct.query.filter(RadAcct.callingstationid == mac, RadAcct.acctstoptime.is_(None)).count() == 0, mac
# ...and the controller is told to take them offline (it would keep them in for its own day-long portal time);
# a phone still at the login page (authStatus 1) is left alone
assert {'AA-BB-CC-00-00-13', 'AA-BB-CC-00-00-14', 'AA-BB-CC-00-00-15'} <= set(api.cut) and 'AA-BB-CC-00-00-16' not in api.cut
assert 'AA-BB-CC-00-00-11' not in api.cut and 'AA-BB-CC-00-00-12' not in api.cut
with app.app_context():
    s = db.session.get(Site, SITE); assert s.omada_checked_at and s.omada_error is None
# the controller doesn't answer: shown on the site
def broken(site_id): raise appmod.omada.OmadaError("can't reach the controller")
api.clients = broken
sync([])
with app.app_context(): assert 'Reading guests from the controller failed' in db.session.get(Site, SITE).omada_error

# time up while online: the session ends and the phone is taken offline at once
api.clients = FakeApi.clients.__get__(api)
api.cut.clear()
with app.app_context():
    Voucher.query.filter_by(code='30304040').update({'expires_at': datetime.utcnow() - timedelta(minutes=1)}); db.session.commit()
sync([on('AA-BB-CC-00-00-11'), on('AA-BB-CC-00-00-12')])
with app.app_context():
    ended = RadAcct.query.filter_by(username='30304040').order_by(RadAcct.radacctid.desc()).first()
    assert ended.acctstoptime is not None and ended.acctterminatecause == 'Session-Timeout'
assert api.cut == ['AA-BB-CC-00-00-11']
# a phone with a valid voucher from another of the business's sites keeps going (counted here), and a
# customer account (username/password) that's still valid is counted, not cut off
from models import RadUser
with app.app_context():
    other = Site(tenant_id=TENANT, name='Block B'); db.session.add(other); db.session.flush()
    db.session.add(Voucher(tenant_id=TENANT, code='12121212', validity_minutes=600, batch='x', status='active', first_mac='aa:bb:cc:00:00:21',
                           first_used_at=now - timedelta(minutes=5), expires_at=now + timedelta(hours=9)))
    db.session.add(RadUser(tenant_id=TENANT, username='mary', is_active=True))
    db.session.add(session('acc', 'AA-BB-CC-00-00-22', now - timedelta(hours=3)))
    db.session.commit()
    RadAcct.query.filter_by(acctsessionid='acc').update({'username': 'mary', 'acctstoptime': now - timedelta(hours=2)}); db.session.commit()
api.cut.clear()
sync([on('AA-BB-CC-00-00-12'), on('AA-BB-CC-00-00-21'), on('AA-BB-CC-00-00-22')])
with app.app_context():
    assert RadAcct.query.filter(RadAcct.callingstationid == 'AA-BB-CC-00-00-21', RadAcct.acctstoptime.is_(None)).one().username == '12121212'
    assert RadAcct.query.filter(RadAcct.callingstationid == 'AA-BB-CC-00-00-22', RadAcct.acctstoptime.is_(None)).one().username == 'mary'
assert api.cut == []
print('OMADA USAGE OK')
