"""Phone numbers work however people type them: 0712..., 712..., +255 712..., +255 0712..., with spaces or dashes."""
import html, os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='p', CLICKPESA_API_KEY='k', PAYMENT_NETWORKS='airtel,mixx')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from gateway import portal_ui as ui

SAME = ['0712345678', '0712 345 678', '0712-345-678', '(0712) 345 678', '712345678', '712 345 678', '255712345678',
        '+255712345678', '+255 712 345 678', '+255 0712 345 678', '+2550712345678', '2550712345678', '00255712345678', ' 0712345678 ']
for raw in SAME:
    assert ui.normalize_phone(raw) == '255712345678', (raw, ui.normalize_phone(raw))
assert ui.normalize_phone('0612345678') == '255612345678'                     # Halotel
for bad in ('', '12345', '0812345678', '07123456789', '071234567', '+254712345678', 'abc'):
    assert ui.normalize_phone(bad) is None, bad
# network guessed from the number, whatever the format
for raw in ('0684000111', '684000111', '+255 0684 000 111', '255684000111'):
    assert ui.network_for_phone(raw) == 'airtel', raw
assert ui.network_for_phone('0654000111') == 'mixx' and ui.network_for_phone('+255 0754000111') == 'mpesa'

# the guest page asks for the number the way people write it (no fixed +255 in front)
page = ui.login_page(ui.theme({}), 'en', packages=[{'id': 1, 'name': 'Day', 'price': '1000', 'currency': 'TZS', 'validity_minutes': 1440}])
assert 'placeholder="07XX XXX XXX"' in page and '<span>+255</span>' not in page

# buying: typed with a leading 0, or +255 followed by 0
import clickpesa
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
pushed = []
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: pushed.append(p) or {'id': 'TX', 'status': 'PROCESSING'}
from app import app, db, _hash_key
import migrations
from models import Tenant, Package, Gateway, Payment
app.config.update(TESTING=True)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Zulu', slug='zulu', status='active'); db.session.add(t); db.session.flush()
    db.session.add_all([Package(tenant_id=t.id, name='Day', price=Decimal(1000), validity_minutes=1440),
                        Gateway(tenant_id=t.id, name='gw', key_prefix='sgw_zulu', key_hash=_hash_key('sgw_zulu'))])
    db.session.commit(); PKG = Package.query.filter_by(tenant_id=t.id).one().id
api = app.test_client()
for i, raw in enumerate(('0684 000 111', '+255 0684000112', '0684-000-113', '684000114')):
    r = api.post('/api/portal/purchase', headers={'X-SafeNet-Key': 'sgw_zulu'}, json={'package_id': PKG, 'phone': raw, 'network': 'airtel'})
    assert r.status_code == 200, (raw, r.get_json())
assert pushed == ['255684000111', '255684000112', '255684000113', '255684000114'], pushed
with app.app_context():
    assert sorted(p.phone for p in Payment.query) == ['255684000111', '255684000112', '255684000113', '255684000114']
# a wrong number still gets a clear message
r = api.post('/api/portal/purchase', headers={'X-SafeNet-Key': 'sgw_zulu'}, json={'package_id': PKG, 'phone': '0812345678', 'network': 'airtel'})
assert r.status_code == 400 and 'valid mobile number' in r.get_json()['error']
print('PHONE NUMBERS OK')
