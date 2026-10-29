"""Hotspot sharing on Omada: a guest's PC (Windows Mobile Hotspot) or phone makes its own Wi-Fi, which the access
points hear as a rogue AP with the device's own address (first byte changed). With 'block hotspot sharing' on, that
device is taken offline and its voucher disabled (the business can enable it again)."""
import html, os, re, sys
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
from app import app, db
import migrations, omada
from models import Admin, Tenant, Site, RadAcct, Voucher


class FakeApi:
    def __init__(self): self.cut, self.rogues, self.clients_now, self.scans = [], [], [], 0
    def scan_rogue_aps(self, site_id): self.scans += 1
    def unauth(self, site_id, mac): self.cut.append(mac)
    def clients(self, site_id): return self.clients_now
    def rogue_aps(self, site_id): return self.rogues


api = FakeApi()
appmod._openapi = lambda: api
now = datetime.utcnow()
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active', block_tethering=True); db.session.add(t); db.session.flush(); TID = t.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    s = Site(tenant_id=TID, name='Hostel', portal_token='tok', omada_hosted=True, omada_site_id='ctl'); db.session.add(s); db.session.flush(); SID = s.id
    for code, mac in (('11110001', 'A4-11-22-33-44-55'), ('11110002', 'B8-00-00-00-00-01')):
        db.session.add(Voucher(tenant_id=TID, code=code, validity_minutes=1440, batch='x', status='active',
                               first_used_at=now - timedelta(hours=1), expires_at=now + timedelta(hours=23)))
        db.session.add(RadAcct(acctsessionid=code, acctuniqueid=code, username=code, nasipaddress='', groupname='', acctterminatecause='',
                               calledstationid=f'omada-{SID}', callingstationid=mac, acctstarttime=now - timedelta(hours=1),
                               acctupdatetime=now, acctsessiontime=0, acctinputoctets=0, acctoutputoctets=0))
    db.session.commit()

# how a device's own hotspot looks
assert omada.own_hotspot('A6:11:22:33:44:55', 'A4-11-22-33-44-55') and omada.own_hotspot('a4:11:22:33:44:56', 'A4:11:22:33:44:55')
assert not omada.own_hotspot('C0:FF:EE:00:00:01', 'A4-11-22-33-44-55') and not omada.own_hotspot('A4:11:22:33:44:55', 'A4:11:22:33:44:55')

on = lambda mac: {'mac': mac, 'authStatus': 2, 'active': True, 'trafficDown': 0, 'trafficUp': 0}
api.clients_now = [on('A4-11-22-33-44-55'), on('B8-00-00-00-00-01')]
# a neighbour's Wi-Fi: nothing happens
api.rogues = [{'bssid': 'C0-FF-EE-00-00-01', 'ssid': 'Neighbour'}]
with app.app_context():
    appmod._omada_sync_site(db.session.get(Site, SID), api)
assert api.cut == []
# the guest's PC shares the connection through Windows Mobile Hotspot
api.rogues.append({'bssid': 'A6-11-22-33-44-55', 'ssid': 'DESKTOP-7Q2 4471'})
with app.app_context():
    appmod._omada_sync_site(db.session.get(Site, SID), api)
    v = Voucher.query.filter_by(code='11110001').one()
    assert v.status == 'disabled' and v.disabled_reason == 'Shared the Wi-Fi through a hotspot'
    assert RadAcct.query.filter_by(acctsessionid='11110001').one().acctstoptime is not None
    assert Voucher.query.filter_by(code='11110002').one().status == 'active'          # the other guest isn't touched
assert api.cut == ['A4-11-22-33-44-55']
assert api.scans == 1                         # the access points are asked to look around every 10 minutes, not every sync
# a hotspot only seen long ago (switched off since) doesn't count
import time as _t
with app.app_context():
    v = Voucher.query.filter_by(code='11110002').one()
api.rogues = [{'bssid': 'BA-00-00-00-00-01', 'ssid': 'Old', 'lastSeen': (_t.time() - 3600) * 1000}]
with app.app_context():
    appmod._omada_sync_site(db.session.get(Site, SID), api)
    assert Voucher.query.filter_by(code='11110002').one().status == 'active'
# the business sees why, and can enable it again
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
page = html.unescape(c.get('/vouchers?state=disabled').text)
assert 'Shared the Wi-Fi through a hotspot' in page
with app.app_context():
    VID = Voucher.query.filter_by(code='11110001').one().id
c.post(f'/vouchers/{VID}/toggle', data={'csrf_token': tok(page)})
with app.app_context():
    v = Voucher.query.filter_by(code='11110001').one(); assert v.status == 'active' and v.disabled_reason is None
# 'block hotspot sharing' off: left alone; a controller that can't list rogue APs doesn't stop the usage sync
with app.app_context():
    db.session.get(Tenant, TID).block_tethering = False; db.session.commit()
    api.cut.clear(); appmod._omada_sync_site(db.session.get(Site, SID), api)
    assert api.cut == []
    db.session.get(Tenant, TID).block_tethering = True; db.session.commit()
    api.rogue_aps = lambda site_id: (_ for _ in ()).throw(omada.OmadaError('controller answered HTTP 404'))
    appmod._omada_sync_site(db.session.get(Site, SID), api)
print('OMADA HOTSPOT SHARE OK')
