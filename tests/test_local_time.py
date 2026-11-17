"""Times are kept in UTC and shown in the viewer's timezone (the browser's sn_tz cookie, the app's X-UTC-Offset),
else the server's (East Africa)."""
import os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import app as A
from app import app, db
import migrations
from models import Admin, Tenant, Payment
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Shop', slug='shop', status='active'); db.session.add(t); db.session.flush()
    a = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); a.set_password('password1')
    db.session.add(a)
    db.session.add(Payment(tenant_id=t.id, reference='TZ1', phone='255712000001', amount=Decimal(1000), validity_minutes=60,
                           status='paid', created_at=datetime(2026, 3, 10, 21, 30), paid_at=datetime(2026, 3, 10, 21, 30)))
    db.session.commit()

with app.test_request_context('/', headers={'Cookie': 'sn_tz=Africa/Dar_es_Salaam'}):
    assert A._local_offset() == timedelta(hours=3)
    assert A.local_time(datetime(2026, 3, 10, 21, 30)) == '2026-03-11 00:30'          # the next day in Dar es Salaam
with app.test_request_context('/', headers={'Cookie': 'sn_tz=America/New_York'}):
    assert A._local_offset() in (timedelta(hours=-5), timedelta(hours=-4))
    assert A.local_time(datetime(2026, 3, 10, 21, 30), '%H:%M') == '17:30'            # summer time (EDT) that day
with app.test_request_context('/', headers={'X-UTC-Offset': '60'}):                     # the app: Lagos, Kinshasa...
    assert A._local_offset() == timedelta(hours=1) and A.local_time(datetime(2026, 3, 10, 21, 30), '%H:%M') == '22:30'
with app.test_request_context('/', headers={'Cookie': 'sn_tz=../../etc/passwd'}):      # nonsense: the server's time
    assert A._local_offset() == A._server_offset()
with app.test_request_context('/', headers={'Cookie': 'sn_tz=Mars/Olympus'}):
    assert A._local_offset() == A._server_offset()
with app.test_request_context('/'):
    assert A.local_time(None) == '' and A.local_time(datetime(2026, 3, 10).date(), '%d %b') == '10 Mar'

c = app.test_client(); r = c.get('/login')
c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
c.set_cookie('sn_tz', 'Africa/Dar_es_Salaam')
page = c.get('/payments').text
assert '2026-03-11 00:30' in page and 'UTC' not in page, re.findall(r'2026-03-1\d \d\d:\d\d', page)
c.set_cookie('sn_tz', 'Asia/Dubai')
assert '2026-03-11 01:30' in c.get('/payments').text
assert "sn_tz=" in page                                                                # the page saves the browser's zone
print('LOCAL TIME OK')
