"""Owner alerts: an SMS per sale and a daily summary (SMS/email), off until the owner turns them on, charged like SMS."""
import html, os, re, sys
from datetime import datetime, timedelta
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', SMS_PRICE='30')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['M-PESA']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: {'id': 'TX', 'status': 'PROCESSING'}
clickpesa.query_payment = lambda r, c=None: {'status': 'SUCCESS', 'collectedAmount': '1000'}
import app as appmod
sms, mails = [], []
appmod.sms_is_configured = lambda: True
appmod.send_sms_async = lambda to, text, ref=None: sms.append((to, text))
appmod.send_mail = lambda to, subj, body: mails.append((to, subj, body)) or True
from app import app, db, _hash_key
import migrations
from models import Admin, Tenant, Package, Gateway, SmsCharge
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Furahini', slug='furahini', status='active', phone='0684000001', sms_to_guests=False); db.session.add(t); db.session.flush()
    db.session.add_all([Package(tenant_id=t.id, name='1 Day', price=Decimal(1000), validity_minutes=1440),
                        Gateway(tenant_id=t.id, name='gw', key_prefix='sgw_furah', key_hash=_hash_key('sgw_furahini'))])
    o = Admin(username='owner', email='o@x.tz', tenant_id=t.id, role='owner', email_verified_at=datetime.utcnow()); o.set_password('password1')
    db.session.add(o); db.session.commit(); TID = t.id; PKG = Package.query.filter_by(tenant_id=TID).one().id

api = app.test_client()
def buy(phone):
    r = api.post('/api/portal/purchase', headers={'X-SafeNet-Key': 'sgw_furahini'}, json={'package_id': PKG, 'phone': phone}).get_json()
    return api.get(f"/api/portal/purchase/{r['reference']}", headers={'X-SafeNet-Key': 'sgw_furahini'}).get_json()

# off by default: no alerts, and the dashboard invites the owner to turn them on
assert buy('0684000111')['status'] == 'paid' and sms == []
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
assert 'Turn on alerts' in c.get('/dashboard').text
s = html.unescape(c.get('/settings/payments').text)
assert 'SMS for every sale' in s and 'Daily summary by SMS' in s and 'TZS 900 a month' in s
assert 'valid mobile number' in html.unescape(c.post('/settings/notifications', data={'csrf_token': tok(s), 'sale_sms': '1', 'notify_phone': '123'},
                                                     follow_redirects=True).text)
c.post('/settings/notifications', data={'csrf_token': tok(s), 'sale_sms': '1', 'daily_sms': '1', 'daily_email': '1', 'notify_phone': '0754 000 999'})
with app.app_context():
    t = db.session.get(Tenant, TID); assert t.notify_sale_sms and t.notify_daily_sms and t.notify_daily_email and t.notify_phone == '255754000999'
assert 'Turn on alerts' not in c.get('/dashboard').text

# a sale: one SMS to the owner (guest SMS stay off), charged
assert buy('0684000222')['status'] == 'paid'
assert len(sms) == 1 and sms[0][0] == '255754000999', sms
assert sms[0][1] == 'SafeNet: Sale TZS 1,000 (1 Day) from 0684***222. Today: TZS 2,000.', sms[0][1]
with app.app_context():
    ch = SmsCharge.query.one(); assert ch.kind == 'sale' and ch.amount == 30 and ch.method == 'balance'
assert 'Sale alert to you' in c.get('/earnings').text
# in Kiswahili for an owner who uses the dashboard in Kiswahili
with app.app_context():
    Admin.query.filter_by(username='owner').update({'language': 'sw'}); db.session.commit()
buy('0684000333')
assert sms[-1][1] == 'SafeNet: Mauzo TZS 1,000 (1 Day) 0684***333. Leo jumla: TZS 3,000.', sms[-1][1]

# daily summary: not before 21:00, then once a day
with app.app_context():
    n = len(sms)
    assert appmod._send_daily_summaries(datetime.now().replace(hour=20, minute=59)) == 0 and len(sms) == n
    assert appmod._send_daily_summaries(datetime.now().replace(hour=21, minute=5)) == 1
    assert appmod._send_daily_summaries(datetime.now().replace(hour=22, minute=0)) == 0
    text = sms[-1][1]
    assert text.startswith('SafeNet ') and 'Mauzo TZS 3,000 (mtandaoni 3,000, vocha 0)' in text and 'Salio: TZS 2,' in text and len(text) <= 160, text
    assert mails[-1][0] == 'o@x.tz' and 'Muhtasari wa leo' in mails[-1][1] and 'Mauzo TZS 3,000' in mails[-1][2]
    assert SmsCharge.query.filter_by(kind='daily').count() == 1
    # the next day it goes again
    t = db.session.get(Tenant, TID); t.summary_sent_on = (datetime.now() - timedelta(days=1)).date(); db.session.commit()
    assert appmod._send_daily_summaries(datetime.now().replace(hour=21, minute=0)) == 1
print('OWNER ALERTS OK')
