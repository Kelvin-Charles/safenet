"""Vouchers in bulk: disable, enable or delete the ticked ones, or all matching the list's filters."""
import html, os, re, sys
from datetime import datetime, timedelta
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as appmod
kicked = []
appmod.disconnect_subscriber = lambda tid, code: kicked.append(code)
from app import app, db
import migrations
from models import Admin, Tenant, Voucher, RadCheck
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='JRIIT', slug='jriit', status='active'); o = Tenant(name='Other', slug='other', status='active')
    db.session.add_all([t, o]); db.session.flush(); TID, OID = t.id, o.id
    a = Admin(username='owner', email='o@x.tz', tenant_id=TID, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    def add(code, tid=TID, batch='b1', **kw):
        db.session.add_all([Voucher(tenant_id=tid, code=code, validity_minutes=60, batch=batch, **kw),
                            RadCheck(username=code, attribute='Cleartext-Password', op=':=', value=code)])
    for i in range(5): add(f'1000000{i}', status='unused')
    add('20000001', status='active', first_used_at=now - timedelta(minutes=10), expires_at=now + timedelta(minutes=50))   # in use
    for i in range(30): add(f'3{i:07d}', batch='promo', status='active', is_free=True, first_used_at=now - timedelta(days=2), expires_at=now - timedelta(days=1))
    add('90000001', tid=OID, status='unused')
    db.session.commit()
    ids = {v.code: v.id for v in Voucher.query}
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
p = html.unescape(c.get('/vouchers').text)
assert 'id="bulk-form"' in p and 'class="form-check-input bulk-pick"' in p and 'Select all 36 vouchers matching this list' in p
post = lambda **d: html.unescape(c.post('/vouchers/bulk', data={'csrf_token': tok(p), **d}, follow_redirects=True).text)
# ticked: disable two (one in use: its phone is disconnected); another business's voucher can't be touched
r = post(action='disable', ids=[ids['10000000'], ids['20000001'], ids['90000001']])
assert '2 vouchers disabled' in r and kicked == ['20000001']
with app.app_context():
    assert Voucher.query.filter_by(code='90000001').one().status == 'unused'
    assert Voucher.query.filter_by(code='20000001').one().status == 'disabled'
r = post(action='enable', ids=[ids['10000000'], ids['20000001']])
assert '2 vouchers enabled' in r
with app.app_context():
    assert Voucher.query.filter_by(code='10000000').one().status == 'unused' and Voucher.query.filter_by(code='20000001').one().status == 'active'
# all matching a filter: every expired promo voucher, across pages
r = post(action='delete', scope='all', batch='promo', state='expired')
assert '30 vouchers deleted' in r
with app.app_context():
    assert Voucher.query.filter_by(batch='promo').count() == 0 and RadCheck.query.filter(RadCheck.username.like('3%')).count() == 0
    assert Voucher.query.filter_by(tenant_id=TID).count() == 6 and Voucher.query.filter_by(tenant_id=OID).count() == 1
# nothing ticked / no action
assert 'No vouchers selected' in post(action='disable')
assert 'Choose what to do' in post(action='nuke', ids=[ids['10000001']])
assert c.post('/vouchers/bulk', data={'action': 'delete', 'scope': 'all'}).status_code == 400            # CSRF
print('VOUCHERS BULK OK')
