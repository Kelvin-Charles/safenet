import os, re, sys, socket, struct, hashlib, threading, time
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import radclient

# --- radclient against a fake router on localhost
def fake_router(code, secret, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sock.bind(('127.0.0.1', port))
    def run():
        data, addr = sock.recvfrom(4096)
        assert data[0] == 40
        req_auth = hashlib.md5(data[:4] + b'\0' * 16 + data[20:] + b'rightsecret').digest()
        assert req_auth == data[4:20], 'bad request authenticator'
        attrs = data[20:]; assert attrs[0] == 1 and attrs[2:2 + attrs[1] - 2] == b'55556666'
        hdr = struct.pack('!BBH', code, data[1], 20)
        sock.sendto(hdr + hashlib.md5(hdr + data[4:20] + secret.encode()).digest(), addr); sock.close()
    threading.Thread(target=run, daemon=True).start()
fake_router(41, 'rightsecret', 37991); assert radclient.disconnect('127.0.0.1', 'rightsecret', '55556666', 'sess1', '10.0.0.5', port=37991) == (True, 'disconnected')
fake_router(42, 'rightsecret', 37992); assert radclient.disconnect('127.0.0.1', 'rightsecret', '55556666', port=37992)[0] is False
fake_router(41, 'othersecret', 37993); assert radclient.disconnect('127.0.0.1', 'rightsecret', '55556666', port=37993) == (False, 'reply with wrong secret')
assert radclient.disconnect('127.0.0.1', 's', 'u', port=37994, timeout=0.3) == (False, 'no reply from router')

import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
sent = []
appmod.radclient.disconnect = lambda *a: sent.append(a) or (True, 'disconnected')
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Voucher, RadUser, RadCheck, Gateway, RadAcct, Nas, SessionKick
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    now = datetime.utcnow()
    ta = Tenant(name='A', slug='a', status='active'); tb = Tenant(name='B', slug='b', status='active'); db.session.add_all([ta, tb]); db.session.flush()
    A, B = ta.id, tb.id
    db.session.add_all([
        Voucher(tenant_id=A, code='55556666', validity_minutes=60, batch='x', status='active', first_used_at=now, expires_at=now + timedelta(hours=1)),
        Voucher(tenant_id=A, code='77778888', validity_minutes=60, batch='x', status='active', first_used_at=now - timedelta(hours=2), expires_at=now - timedelta(hours=1)),
        RadUser(tenant_id=A, username='alice', is_active=True), RadUser(tenant_id=A, username='carol', is_active=True, expires_at=now - timedelta(days=1)),
        RadUser(tenant_id=B, username='bob', is_active=True),
        Nas(tenant_id=A, nasname='10.200.1.9', shortname='mk', type='other', secret='mksecret1'),
        Gateway(tenant_id=A, name='gw', key_prefix='sgw_a', key_hash=_hash_key('sgw_a')),
        RadAcct(radacctid=1, acctsessionid='mk-1', acctuniqueid='u1', username='55556666', nasipaddress='10.200.1.9', framedipaddress='192.168.88.20', acctstarttime=now, acctupdatetime=now),
        RadAcct(radacctid=2, acctsessionid='gw-1', acctuniqueid='u2', username='alice', nasipaddress='1.2.3.4', acctstarttime=now, acctupdatetime=now),
    ])
    for u in ('55556666', '77778888', 'alice', 'carol', 'bob'):
        db.session.add(RadCheck(username=u, attribute='Cleartext-Password', op=':=', value='pw'))
    a = Admin(username='owner', email='o@a.tz', tenant_id=A, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    boss = Admin(username='platform', email='p@x.tz', tenant_id=1, role='owner', is_superadmin=True, email_verified_at=now); boss.set_password('password1'); db.session.add(boss)
    db.session.commit()
    vid = Voucher.query.filter_by(code='55556666').one().id; uid = RadUser.query.filter_by(username='alice').one().id

api = app.test_client(); H = {'X-SafeNet-Key': 'sgw_a'}
check = lambda names: api.post('/api/gateway/sessions/check', headers=H, json={'usernames': names}).get_json()['disconnect']
assert sorted(check(['55556666', '77778888', 'alice', 'carol', 'ghost', 'bob'])) == ['77778888', 'bob', 'carol', 'ghost']   # expired, other tenant, expired user, deleted
assert check([]) == []

c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
t = tok(c.get('/vouchers/generate').text)
r = c.post(f'/vouchers/{vid}/toggle', data={'csrf_token': t}, follow_redirects=True)
assert 'disabled and its devices disconnected' in r.text
time.sleep(0.3)
assert sent == [('10.200.1.9', 'mksecret1', '55556666', 'mk-1', '192.168.88.20')], sent     # RADIUS router got a Disconnect-Request
assert '55556666' in check(['55556666'])                                                     # gateways too

# manual kick from Live: gateway sees it exactly once
r = c.post('/live/disconnect', data={'csrf_token': t, 'username': 'alice'}); assert r.get_json()['ok']
assert check(['alice']) == ['alice'] and check(['alice']) == []
assert c.post('/live/disconnect', data={'csrf_token': t, 'username': 'bob'}).status_code == 404     # other tenant
assert c.post('/live/disconnect', data={'username': 'alice'}).status_code == 400                   # CSRF

# disabling a user in the edit form disconnects
r = c.get(f'/users/edit/{uid}'); c.post(f'/users/edit/{uid}', data={'csrf_token': tok(r.text), 'username': 'alice', 'password': 'pw12', 'plan_id': 0})
with app.app_context(): assert SessionKick.query.filter_by(username='alice', consumed_at=None).count() == 1
# suspended tenant: gateway API refuses -> gateway drops everyone
cp = app.test_client(); r = cp.get('/login'); cp.post('/login', data={'username': 'platform', 'password': 'password1', 'csrf_token': tok(r.text)})
cp.post(f'/platform/tenants/{A}/status', data={'csrf_token': tok(cp.get('/platform/tenants').text), 'action': 'suspend'})
assert api.post('/api/gateway/sessions/check', headers=H, json={'usernames': ['alice']}).status_code == 403
print('DISCONNECT CLOUD OK')
