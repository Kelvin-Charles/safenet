import os, re, sys
os.environ.update(DB_PASSWORD='x')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from datetime import datetime, timedelta
from decimal import Decimal
from app import app, db
from models import Admin, Plan, Voucher, Payment, RadAcct, RadPostAuth, Nas
app.config.update(TESTING=True)
c = app.test_client()
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); __import__('migrations').run()
    a = Admin(username='admin', email='a@b.c', role='owner', tenant_id=__import__('migrations').default_tenant().id,
              email_verified_at=__import__('datetime').datetime.utcnow()); a.set_password('pw'); db.session.add(a)
    plan = Plan(name='Fast10M'); db.session.add(plan); db.session.flush()
    v1 = Voucher(code='11112222', plan_id=plan.id, batch='online-payments', validity_minutes=1440, price=Decimal(1000), status='active', first_used_at=now - timedelta(minutes=30), expires_at=now + timedelta(hours=23, minutes=30))
    v2 = Voucher(code='33334444', batch='cafe', validity_minutes=60, price=Decimal(500), status='active', first_used_at=now - timedelta(minutes=5), expires_at=now + timedelta(minutes=55))
    db.session.add_all([v1, v2]); db.session.flush()
    db.session.add(Payment(reference='SNAAA', package_name='1 Day', phone='255712345678', amount=Decimal(1000), validity_minutes=1440, status='paid', voucher_id=v1.id, paid_at=now - timedelta(minutes=31), created_at=now - timedelta(minutes=32)))
    db.session.add(Payment(reference='SNBBB', package_name='1 Hour', phone='255654000111', amount=Decimal(500), validity_minutes=60, status='failed', message='Insufficient balance', created_at=now - timedelta(minutes=10), updated_at=now - timedelta(minutes=9)))
    def acct(uid, user, start, upd, stop=None, down=0, up=0):
        return RadAcct(radacctid=int(uid[1:]), acctsessionid=uid, acctuniqueid=uid, username=user, nasipaddress='10.10.0.1', calledstationid='devserver-gw',
                       callingstationid='AA-BB-CC-00-00-0' + uid[-1], framedipaddress='10.10.0.5' + uid[-1], acctstarttime=start,
                       acctupdatetime=upd, acctstoptime=stop, acctoutputoctets=down, acctinputoctets=up, acctsessiontime=int((upd - start).total_seconds()))
    db.session.add_all([
        acct('s1', '11112222', now - timedelta(minutes=30), now - timedelta(seconds=40), down=250_000_000, up=12_000_000),
        acct('s2', '33334444', now - timedelta(minutes=5), now - timedelta(minutes=5), down=0, up=0),
        acct('s3', 'olduser', now - timedelta(hours=2), now - timedelta(hours=1), stop=now - timedelta(hours=1), down=5_000_000, up=1_000_000),
        acct('s4', 'ghost', now - timedelta(days=2), now - timedelta(days=1)),   # open but stale: not online
    ])
    db.session.add_all([RadPostAuth(username='11112222', pass_field='x', reply='Access-Accept', authdate=now - timedelta(minutes=30)),
                        RadPostAuth(username='00000000', pass_field='x', reply='Access-Reject', authdate=now - timedelta(minutes=20))])
    db.session.commit()
    db.session.add(__import__('models').RadUser(username='olduser')); db.session.commit()
    __import__('migrations').run()          # rows made without a tenant belong to the main one

assert c.get('/api/live').status_code == 302           # login required
r = c.get('/login'); c.post('/login', data={'username': 'admin', 'password': 'pw', 'csrf_token': tok(r.text)})
r = c.get('/live'); assert r.status_code == 200 and 'Online users' in r.text and 'api/live' in r.text
d = c.get('/api/live').get_json()
s = d['stats']
assert s['online'] == 2, s
users = {o['user']: o for o in d['online']}
assert set(users) == {'11112222', '33334444'}
assert users['11112222']['phone'] == '255712345678' and users['11112222']['plan'] == 'Fast10M' and users['11112222']['down'] == 250_000_000
assert users['11112222']['router'] == 'devserver-gw' and users['11112222']['expires'].endswith('Z')
assert s['down_today'] >= 250_000_000 and s['online_revenue_today'] == 1000 and s['online_sales_today'] == 1
assert s['cash_revenue_today'] == 500 and s['vouchers_activated_today'] == 2
assert s['logins_today'] == 1 and s['rejects_today'] == 0   # unknown codes belong to no tenant
types = [e['type'] for e in d['events']]
for t in ('login', 'start', 'stop', 'paid', 'failed', 'payment'):   # rejects of unknown codes belong to no tenant
    assert t in types, (t, types)
assert d['events'] == sorted(d['events'], key=lambda e: e['at'], reverse=True)
print('LIVE OK', s)
