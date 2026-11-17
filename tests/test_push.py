"""App notifications: phones register, alerts go to the right people (role, site, their own choices), the alerts list,
device offline / back online once each way, platform announcements, the Firebase files and a correctly signed FCM call."""
import base64, io, json, os, plistlib, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import push
import app as appmod
from app import app, db
import migrations
from models import Admin, Tenant, Site, Payment, Gateway, Notification, PushDevice
app.config.update(TESTING=True)
appmod.send_sms_async = lambda *a, **k: None
appmod.send_mail = lambda *a, **k: True
push.folder = appmod.APP_FILES_DIR = sys.argv[1] if len(sys.argv) > 1 else '/tmp/sn-push-test'
appmod._push_async = appmod._push_deliver            # deliver at once, in the test
sent = []
gone = set()
def fake_send(token, title, body, data=None):
    sent.append((token, title, body, data)); return 'gone' if token in gone else 'ok'
real_send = push.send
push.send = fake_send
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kpstar', slug='kpstar', status='active'); db.session.add(t); db.session.flush(); T = t.id
    s1, s2 = Site(tenant_id=T, name='Hostel'), Site(tenant_id=T, name='Shop'); db.session.add_all([s1, s2]); db.session.flush()
    S1, S2 = s1.id, s2.id
    ids = {}
    for u, role, site, sa in (('owner1', 'owner', None, False), ('staff1', 'staff', None, False), ('partner1', 'viewer', None, False),
                              ('sitepart', 'viewer', S2, False), ('boss', 'owner', None, True)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=T, role=role, site_id=site, is_superadmin=sa, email_verified_at=now)
        a.set_password('password1'); db.session.add(a); db.session.flush(); ids[u] = a.id
    db.session.add(Gateway(tenant_id=T, site_id=S1, name='Box 1', key_prefix='abc', key_hash='h' * 64, last_seen_at=now))
    db.session.commit()

c = app.test_client()
def token(user):
    r = c.post('/api/m/login', json={'username': user, 'password': 'password1'}); assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.get_json()['token']}"}
H = {u: token(u) for u in ids}

# not set up yet: the app is told to skip Firebase; the alerts list still works
assert c.get('/api/m/push/config').get_json() == {'enabled': False}
assert c.post('/api/m/push/register', json={'token': 'x' * 40}).status_code == 401
for u in ids:
    assert c.post('/api/m/push/register', headers=H[u], json={'token': f'tok-{u}-' + 'x' * 30, 'platform': 'ios' if u == 'owner1' else 'android'}).status_code == 200
assert c.post('/api/m/push/register', headers=H['owner1'], json={'token': 'short'}).status_code == 400
with app.app_context():
    assert PushDevice.query.count() == 5 and PushDevice.query.filter_by(admin_id=ids['owner1']).one().platform == 'ios'
# the same phone, someone else signs in: the phone moves to them
c.post('/api/m/push/register', headers=H['staff1'], json={'token': 'tok-partner1-' + 'x' * 30})
with app.app_context():
    assert PushDevice.query.filter_by(token='tok-partner1-' + 'x' * 30).one().admin_id == ids['staff1']
c.post('/api/m/push/register', headers=H['partner1'], json={'token': 'tok-partner1-' + 'x' * 30})

# settings: each person sees only the kinds their role gets
kinds = lambda u: [k['kind'] for k in c.get('/api/m/alerts/settings', headers=H[u]).get_json()['kinds']]
assert kinds('owner1') == ['sale', 'failed', 'daily', 'device', 'withdrawal', 'billing', 'news']
assert kinds('staff1') == ['device', 'news'] and kinds('sitepart') == ['sale', 'failed', 'device', 'news']
assert 'platform' in kinds('boss')

# a sale: owner, partner and the partner of that site; not staff, not the partner of another site. Nothing pushed yet (no key)
def sale(ref, site):
    with app.app_context():
        p = Payment(tenant_id=T, reference=ref, phone='255712000111', amount=Decimal(2000), validity_minutes=60, package_name='Day',
                    status='paid', paid_at=datetime.utcnow(), site_id=site, currency='TZS')
        db.session.add(p); db.session.flush(); appmod._sale_alert(p); db.session.commit()
sale('R1', S1)
with app.app_context():
    got = {a for (a,) in db.session.query(Notification.admin_id).filter_by(kind='sale')}
    assert got == {ids['owner1'], ids['partner1'], ids['boss']}, got
    n = Notification.query.filter_by(admin_id=ids['owner1']).one()
    assert n.title == 'New sale: TZS 2,000' and 'Hostel' in n.body and '0712***111' in n.body and n.link == 'payments'
assert sent == []

# Firebase files on Platform: Notifications
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
service = json.dumps({'type': 'service_account', 'project_id': 'safenet-test', 'private_key': pem, 'client_email': 'fcm@safenet-test.iam.gserviceaccount.com',
                      'token_uri': 'https://oauth2.googleapis.com/token'}).encode()
android = json.dumps({'project_info': {'project_number': '1234', 'project_id': 'safenet-test'},
                      'client': [{'client_info': {'mobilesdk_app_id': '1:1234:android:ab', 'android_client_info': {'package_name': 'com.safezonetz.safenet_app'}},
                                  'api_key': [{'current_key': 'AIzaAndroid'}]}]}).encode()
ios = plistlib.dumps({'API_KEY': 'AIzaIos', 'GOOGLE_APP_ID': '1:1234:ios:cd', 'GCM_SENDER_ID': '1234', 'PROJECT_ID': 'safenet-test', 'BUNDLE_ID': 'com.safezonetz.safenetApp'})
import re
w = app.test_client()
r = w.get('/login'); tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
w.post('/login', data={'username': 'boss', 'password': 'password1', 'csrf_token': tok(r.text)})
page = w.get('/platform/notifications'); assert page.status_code == 200 and 'Missing' in page.text
r = w.post('/platform/notifications', data={'csrf_token': tok(page.text), 'action': 'upload', 'android': (io.BytesIO(ios), 'x.json')},
           content_type='multipart/form-data', follow_redirects=True)
assert 'could not be read' in r.text
r = w.post('/platform/notifications', data={'csrf_token': tok(page.text), 'action': 'upload', 'service': (io.BytesIO(service), 'k.json'),
                                            'android': (io.BytesIO(android), 'google-services.json'), 'ios': (io.BytesIO(ios), 'GoogleService-Info.plist')},
           content_type='multipart/form-data', follow_redirects=True)
assert 'Saved: service account key, Android app, iOS app' in r.text and 'Android, ' in r.text, r.text[-3000:]
assert oct(os.stat(os.path.join(push.folder, push.FILES['service'])).st_mode & 0o777) == '0o600'
cfg = c.get('/api/m/push/config').get_json()
assert cfg == {'enabled': True, 'project_id': 'safenet-test', 'android': {'api_key': 'AIzaAndroid', 'app_id': '1:1234:android:ab', 'sender_id': '1234', 'project_id': 'safenet-test'},
               'ios': {'api_key': 'AIzaIos', 'app_id': '1:1234:ios:cd', 'sender_id': '1234', 'project_id': 'safenet-test'}}, cfg

# now sales push too; a person who turned sales off gets neither the alert nor the push; a gone phone is forgotten
r = c.post('/api/m/alerts/settings', headers=H['partner1'], json={'sale': False}).get_json()
assert [k['on'] for k in r['kinds'] if k['kind'] == 'sale'] == [False] and r['phones'] == 1
gone.add('tok-boss-' + 'x' * 30)
sale('R2', S2)
assert sorted(s[0].split('-')[1] for s in sent) == ['boss', 'owner1', 'sitepart'], sent
assert sent[0][3] == {'kind': 'sale', 'link': 'payments'}
with app.app_context():
    assert not PushDevice.query.filter_by(admin_id=ids['boss']).count()
    assert Notification.query.filter_by(admin_id=ids['partner1'], kind='sale').count() == 1      # only the first one

# the alerts list and read state
L = c.get('/api/m/alerts', headers=H['owner1']).get_json()
assert L['unread'] == 2 and [i['title'] for i in L['items']] == ['New sale: TZS 2,000'] * 2 and L['push'] is True
assert c.post('/api/m/alerts/read', headers=H['owner1'], json={'id': L['items'][0]['id']}).get_json() == {'unread': 1}
assert c.post('/api/m/alerts/read', headers=H['staff1'], json={'id': L['items'][1]['id']}).get_json() == {'unread': 0}   # not theirs
assert c.get('/api/m/alerts/count', headers=H['owner1']).get_json() == {'unread': 1}
assert c.post('/api/m/alerts/read', headers=H['owner1'], json={}).get_json() == {'unread': 0}

# device offline once, then back online once; staff hear about it, the partner of the other site doesn't
sent.clear()
with app.app_context():
    Gateway.query.update({'last_seen_at': datetime.utcnow() - timedelta(minutes=20)}); db.session.commit()
    assert appmod.check_devices() == 1 and appmod.check_devices() == 0
    assert Gateway.query.one().is_down
    who = {a for (a,) in db.session.query(Notification.admin_id).filter_by(kind='device')}
    assert ids['staff1'] in who and ids['owner1'] in who and ids['sitepart'] not in who
    assert Notification.query.filter_by(kind='device', admin_id=ids['owner1']).one().title == 'Box 1 is offline'
    Gateway.query.update({'last_seen_at': datetime.utcnow()}); db.session.commit()
    assert appmod.check_devices() == 1 and not Gateway.query.one().is_down
    assert Notification.query.filter_by(kind='device', admin_id=ids['owner1']).order_by(Notification.id.desc()).first().title == 'Box 1 is back online'
assert any(s[1] == 'Box 1 is offline' for s in sent)
# Kiswahili for people who use it
with app.app_context():
    db.session.get(Admin, ids['owner1']).language = 'sw'; db.session.commit()
sale('R3', S1)
assert c.get('/api/m/alerts', headers=H['owner1']).get_json()['items'][0]['title'] == 'Mauzo mapya: TZS 2,000'

# payment problems: failed once per payment (not when it's only waiting for an answer), short payments, paid but no code
def problem(ref, kind, msg, note=None):
    with app.app_context():
        p = Payment.query.filter_by(reference=ref).first() or Payment(tenant_id=T, reference=ref, phone='255712000222', amount=Decimal(1000),
                                                                      validity_minutes=60, package_name='Hour', site_id=S1, currency='TZS')
        p.status, p.message = 'failed', msg
        db.session.add(p); db.session.flush(); appmod._payment_problem(p, kind, note); db.session.commit()
        return [n.title for n in Notification.query.filter_by(admin_id=ids['boss'], kind='failed').order_by(Notification.id)]
assert problem('F1', 'failed', 'Customer cancelled.') == ['Payment failed: TZS 1,000']
assert problem('F1', 'failed', 'Customer cancelled.') == ['Payment failed: TZS 1,000']             # once
assert problem('F2', 'failed', 'Snippe unreachable') == ['Payment failed: TZS 1,000']             # checked again first
assert problem('F3', 'review', 'Collected 500, expected 1000')[-1] == 'Payment to check: TZS 1,000'
assert problem('F4', 'no_code', None, 'no Ruijie package lasts 1 hour')[-1] == 'Paid, but no code: TZS 1,000'
with app.app_context():
    n = Notification.query.filter_by(admin_id=ids['boss'], kind='failed').first()
    assert 'Customer cancelled.' in n.body and 'Ref F1' in n.body and n.link == 'payments'
    assert {a for (a,) in db.session.query(Notification.admin_id).filter_by(kind='failed')} == {ids['owner1'], ids['partner1'], ids['boss']}
    assert Notification.query.filter_by(admin_id=ids['owner1'], kind='failed').first().title == 'Malipo hayakukamilika: TZS 1,000'
    # the platform team pauses / restores an account: its people hear about it
    appmod._account_action_alert(db.session.get(Tenant, T), 'suspend'); db.session.commit()
    assert Notification.query.filter_by(admin_id=ids['boss'], kind='billing').one().title == 'Your SafeNet account is paused'

# withdrawals reach the owner only
with app.app_context():
    from models import Withdrawal
    wd = Withdrawal(tenant_id=T, amount=Decimal(10000), method='mobile', phone='255712000111', status='requested', fee_charged=Decimal(500))
    db.session.add(wd); db.session.flush()
    appmod._finish_withdrawal(wd, 'paid', reference='PO1'); db.session.commit()
    assert {a for (a,) in db.session.query(Notification.admin_id).filter_by(kind='withdrawal')} == {ids['owner1'], ids['boss']}

# an announcement from the platform
page = w.get('/platform/notifications')
r = w.post('/platform/notifications', data={'csrf_token': tok(page.text), 'action': 'announce', 'title': 'Maintenance tonight',
                                            'body': '23:00 to 23:30', 'who': 'owners', 'tenant_id': ''}, follow_redirects=True)
assert 'Sent to 2 people' in r.text, r.text[-2000:]
assert 'Maintenance tonight' in w.get('/platform/notifications').text

# the real sender: a JWT signed with the key, swapped for an access token, then the FCM v1 call
push.send = real_send
calls = []
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake_urlopen(req, timeout=None):
    calls.append(req)
    if 'oauth2' in req.full_url:
        return Resp(json.dumps({'access_token': 'ya29.test', 'expires_in': 3600}).encode())
    return Resp(b'{"name": "projects/safenet-test/messages/1"}')
push.urllib.request.urlopen = fake_urlopen
push._token.update(value=None, exp=0)
assert push.send('tok-owner1', 'Hi', 'There', {'kind': 'news'}) == 'ok'
assert push.send('tok-owner1', 'Again', '', None) == 'ok'
assert len(calls) == 3                                                       # the access token is reused
assertion = dict(x.split('=') for x in calls[0].data.decode().split('&'))['assertion']
head, claims, sig = assertion.split('.')
pad = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
key.public_key().verify(pad(sig), f'{head}.{claims}'.encode(), padding.PKCS1v15(), hashes.SHA256())
cl = json.loads(pad(claims)); assert cl['iss'].startswith('fcm@') and cl['scope'].endswith('firebase.messaging')
assert calls[1].full_url == 'https://fcm.googleapis.com/v1/projects/safenet-test/messages:send'
assert calls[1].headers['Authorization'] == 'Bearer ya29.test'
msg = json.loads(calls[1].data)['message']
assert msg['token'] == 'tok-owner1' and msg['notification'] == {'title': 'Hi', 'body': 'There'} and msg['data'] == {'kind': 'news'}
def unregistered(req, timeout=None):
    raise push.urllib.error.HTTPError(req.full_url, 404, 'Not Found', {}, io.BytesIO(b'{"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}'))
push.urllib.request.urlopen = unregistered
assert push.send('tok-old', 'x', 'y') == 'gone'

# signing out: the phone stops getting them
assert c.post('/api/m/push/unregister', json={'token': 'tok-owner1-' + 'x' * 30}).status_code == 200
with app.app_context():
    assert not PushDevice.query.filter_by(admin_id=ids['owner1']).count()
print('PUSH OK')
