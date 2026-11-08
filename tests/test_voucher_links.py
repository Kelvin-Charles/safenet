"""Voucher details page, links from codes and phones, the payments phone search, and the Customers list
(last code bought; "Has time left" only while a code's time runs, "Not used yet" for paid codes not used)."""
import os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db, _note_customer
import migrations
from models import Admin, Tenant, Voucher, Payment, RadAcct, RadUser, RadPostAuth, SmsContact
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    ids = {}
    for slug in ('furahini', 'other'):
        t = Tenant(name=slug.title(), slug=slug, status='active'); db.session.add(t); db.session.flush(); ids[slug] = t.id
        a = Admin(username=slug, email=f'{slug}@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    T = ids['furahini']
    old = Voucher(tenant_id=T, code='11110001', validity_minutes=1440, price=Decimal(1000), status='active',
                  first_used_at=now - timedelta(days=29), expires_at=now - timedelta(days=28), first_mac='aa:bb:cc:dd:ee:01')
    unused = Voucher(tenant_id=T, code='11110002', validity_minutes=1440, price=Decimal(1000), status='unused')
    running = Voucher(tenant_id=T, code='11110003', validity_minutes=1440, price=Decimal(1000), status='active',
                      first_used_at=now - timedelta(hours=2), expires_at=now + timedelta(hours=22))
    theirs = Voucher(tenant_id=ids['other'], code='99990001', validity_minutes=60, status='unused')
    db.session.add_all([old, unused, running, theirs]); db.session.flush()
    def pay(ref, phone, v, days, gift=None):
        p = Payment(tenant_id=T, reference=ref, phone=phone, gift_phone=gift, amount=Decimal(1000), validity_minutes=1440, package_name='1 Day',
                    status='paid', paid_at=now - timedelta(days=days), created_at=now - timedelta(days=days), voucher_id=v.id)
        db.session.add(p); db.session.flush(); _note_customer(p)
    pay('R-OLD', '255793896812', old, 29)        # bought long ago, used, ended
    pay('R-UNU', '255753243820', unused, 20)     # paid, never used
    pay('R-RUN', '255650691369', running, 0)     # in use now
    pay('R-OLD2', '255650691369', old, 30)       # an older purchase of the same phone: not its last code
    db.session.add(RadAcct(acctsessionid='s1', acctuniqueid='u1', username='11110001', nasipaddress='', groupname='', acctterminatecause='',
                           callingstationid='AA-BB-CC-DD-EE-01', acctstarttime=now - timedelta(days=29), acctstoptime=now - timedelta(days=28),
                           acctinputoctets=5 * 1048576, acctoutputoctets=1048576))
    db.session.add(RadPostAuth(username='11110001', pass_field='x', reply='Access-Accept', authdate=now - timedelta(days=29)))
    db.session.add(RadUser(username='kassim', tenant_id=T, is_active=True))
    db.session.commit()
    OLD, UNUSED, RUNNING, THEIRS = old.id, unused.id, running.id, theirs.id
    KASSIM = RadUser.query.filter_by(username='kassim').one().id

def login(u):
    c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': u, 'password': 'password1', 'csrf_token': tok(r.text)}); return c
c = login('furahini')

# the details page: state, times, who paid (linked to their payments), sessions (linked), login attempts
d = c.get(f'/vouchers/{OLD}').text
assert '11110001' in d and 'Expired' in d and 'aa:bb:cc:dd:ee:01' in d, d[-3000:]
assert '/payments?search=255793896812' in d and 'R-OLD' in d
assert re.search(r'/accounting/\d+', d) and '6.0 MB' in d and 'Accepted' in d
assert 'Time starts at the first login' in c.get(f'/vouchers/{UNUSED}').text
assert 'In use' in c.get(f'/vouchers/{RUNNING}').text
# another business's voucher: not found, not even by its code
assert c.get(f'/vouchers/{THEIRS}').status_code == 404
assert c.get('/open/99990001').headers['Location'].endswith('/vouchers?search=99990001')

# codes and names shown on pages go to their voucher or customer account
assert c.get('/open/11110001').headers['Location'].endswith(f'/vouchers/{OLD}')
assert c.get('/open/kassim').headers['Location'].endswith(f'/users/edit/{KASSIM}')

# payments: a phone typed the local way finds the 255... payments, and so does the code
for q in ('0793896812', '+255 793 896 812', '255793896812', '11110001'):
    r = c.get('/payments', query_string={'search': q}).text
    assert 'R-OLD<' in r.replace('</small>', '<') and 'R-UNU' not in r, q
r = c.get('/payments').text
assert f'/vouchers/{OLD}' in r and '/payments?search=255793896812' in r

# customers: last code bought (linked), the right badge, and the phone links to their payments
r = c.get('/customers').text
rows = {m.group(1): m.group(0) for m in re.finditer(r'search=0(\d{9}).*?</tr>', r, re.S)}
assert f'/vouchers/{OLD}' in rows['793896812'] and 'No time left' in rows['793896812']
assert f'/vouchers/{UNUSED}' in rows['753243820'] and 'Not used yet' in rows['753243820'] and 'Has time left' not in rows['753243820']
assert f'/vouchers/{RUNNING}' in rows['650691369'] and 'Has time left' in rows['650691369'] and f'/vouchers/{OLD}' not in rows['650691369']

# the other pages link codes too
assert f'/vouchers/{OLD}' in c.get('/vouchers').text
assert '/open/11110001' in c.get('/accounting').text
assert '/open/11110001' in c.get('/auth-logs').text
assert '/open/' in c.get('/live').text
print('ok')
