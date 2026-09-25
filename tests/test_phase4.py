import os, re, sys, base64
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations, secretbox
from models import Admin, Tenant, Router, Nas, VpnServer
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    ta = Tenant(name='A', slug='a', status='active'); tb = Tenant(name='B', slug='b', status='active'); db.session.add_all([ta, tb]); db.session.flush()
    for u, t in (('usera', ta.id), ('userb', tb.id)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=t, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a)
    db.session.add(Nas(tenant_id=ta.id, nasname='10.200.1.1', shortname='taken', type='other', secret='s' * 8))   # already used address
    db.session.commit()
def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
ca, cb = login('usera'), login('userb')
r = ca.get('/routers'); assert 'VPN hub isn' in r.text
r = ca.post('/routers/add', data={'csrf_token': tok(r.text), 'name': 'Kariakoo hotspot', 'vendor': 'mikrotik'}, follow_redirects=True)
assert "hub isn't running yet" in r.text          # no script until the hub publishes its key
with app.app_context():
    db.session.add(VpnServer(id=1, public_key='SERVERPUBKEY=', listen_port=51820)); db.session.commit()
    rt = Router.query.one(); nas = db.session.get(Nas, rt.nas_id)
    assert rt.tunnel_ip == '10.200.1.2' and nas.nasname == '10.200.1.2' and nas.tenant_id == rt.tenant_id and len(nas.secret) >= 20
    priv = secretbox.decrypt(rt.private_key_enc)
    assert len(base64.b64decode(priv)) == 32 and len(base64.b64decode(rt.public_key)) == 32 and priv not in rt.private_key_enc
    rid = rt.id; secret = nas.secret
r = ca.get(f'/routers/{rid}/script')
assert priv in r.text and 'SERVERPUBKEY=' in r.text and 'address=10.200.1.2/16' in r.text and secret in r.text
assert 'endpoint-address=radius.safezonetz.com endpoint-port=51820' in r.text and 'address=10.200.0.1 secret=' in r.text
r = ca.get('/routers'); ca.post('/routers/add', data={'csrf_token': tok(r.text), 'name': 'Second', 'vendor': 'other'})
with app.app_context(): assert sorted(x.tunnel_ip for x in Router.query) == ['10.200.1.2', '10.200.1.3']
r = ca.get('/routers'); assert 'Kariakoo hotspot' in r.text and 'Waiting for first connection' in r.text
with app.app_context():
    x = db.session.get(Router, rid); x.last_handshake_at = datetime.utcnow() - timedelta(seconds=30); db.session.commit()
assert 'Online' in ca.get('/routers').text
# isolation
assert cb.get(f'/routers/{rid}/script').status_code == 404 and '<strong>Kariakoo' not in cb.get('/routers').text
assert cb.post(f'/routers/{rid}/delete', data={'csrf_token': tok(cb.get('/routers').text)}).status_code == 404
# toggle + delete
t = tok(ca.get('/routers').text)
ca.post(f'/routers/{rid}/toggle', data={'csrf_token': t})
with app.app_context(): assert db.session.get(Router, rid).is_active is False and db.session.get(Nas, db.session.get(Router, rid).nas_id).is_active is False
ca.post(f'/routers/{rid}/delete', data={'csrf_token': t})
with app.app_context(): assert db.session.get(Router, rid) is None and Nas.query.filter_by(nasname='10.200.1.2').count() == 0
print('PHASE4 WEB OK')

# --- hub sync logic with fake wg + database
sys.path.insert(0, 'wireguard'); import types
sys.modules['pymysql'] = types.SimpleNamespace(err=types.SimpleNamespace(ProgrammingError=Exception), MySQLError=Exception, connect=None)
import wg_sync
state = {'peers': {'OLDPEER': ('10.200.9.9/32', 0, 0, 0), 'KEEP': ('10.200.1.5/32', 1700000000, 10, 20)}}
cmds = []
def fake_sh(*args, stdin=None):
    cmds.append(args)
    if args[:3] == ('wg', 'show', 'wg-safenet'):
        lines = ['priv\tpub\t51820\toff'] + [f'{k}\t(none)\t1.2.3.4:5\t{v[0]}\t{v[1]}\t{v[2]}\t{v[3]}\t25' for k, v in state['peers'].items()]
        return '\n'.join(lines) + '\n'
    if args[:3] == ('wg', 'set', 'wg-safenet') and args[-1] == 'remove':
        state['peers'].pop(args[4])
    elif args[:3] == ('wg', 'set', 'wg-safenet') and 'allowed-ips' in args:
        state['peers'][args[4]] = (args[6], 0, 0, 0)
    return ''
wg_sync.sh = fake_sh
class Cur:
    def __init__(s, log): s.log = log
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def execute(s, sql, params=None): s.log.append((sql, params))
    def fetchall(s): return [('KEEP', '10.200.1.5'), ('NEWPEER', '10.200.1.6')]
class Conn:
    def __init__(s): s.log = []
    def cursor(s): return Cur(s.log)
conn = Conn(); wg_sync.sync(conn)
assert 'OLDPEER' not in state['peers'] and state['peers']['NEWPEER'][0] == '10.200.1.6/32' and 'KEEP' in state['peers']
assert not any(a[:5] == ('wg', 'set', 'wg-safenet', 'peer', 'KEEP') for a in cmds)       # unchanged peer untouched
upd = [p for q, p in conn.log if q and q.startswith('UPDATE routers')]
assert len(upd) == 1 and upd[0][1:] == (10, 20, 'KEEP')
print('PHASE4 HUB OK')
