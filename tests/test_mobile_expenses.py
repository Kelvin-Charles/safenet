"""Mobile app: expenses (list, add, change, delete), the financial report as data and as a PDF, per site, roles."""
import os, sys
from datetime import datetime, timedelta, date
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations
from models import Admin, Tenant, Site, Payment, Expense
app.config.update(TESTING=True)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kpstar', slug='kpstar', status='active'); db.session.add(t); db.session.flush(); T = t.id
    o = Tenant(name='Other', slug='other', status='active'); db.session.add(o); db.session.flush()
    s1, s2 = Site(tenant_id=T, name='Hostel'), Site(tenant_id=T, name='Shop'); db.session.add_all([s1, s2]); db.session.flush()
    S1, S2 = s1.id, s2.id
    for u, role, tid, site in (('owner1', 'owner', T, None), ('staff1', 'staff', T, None), ('partner1', 'viewer', T, None),
                               ('sitepart', 'viewer', T, S2), ('other1', 'owner', o.id, None)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=tid, role=role, site_id=site, email_verified_at=now); a.set_password('password1'); db.session.add(a)
    db.session.add(Payment(tenant_id=T, reference='R1', phone='255712000001', amount=Decimal(30000), validity_minutes=60, package_name='1 Week',
                           status='paid', paid_at=now - timedelta(hours=5), site_id=S1, provider_account='platform', fee_amount=Decimal(900)))
    db.session.add(Expense(tenant_id=o.id, spent_on=date.today(), category='other', description='Secret', amount=Decimal(5)))
    db.session.commit()
    OTHER = Expense.query.filter_by(description='Secret').one().id

c = app.test_client()
def token(user):
    r = c.post('/api/m/login', json={'username': user, 'password': 'password1'}); assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.get_json()['token']}"}
H = token('owner1')
me = c.get('/api/m/me', headers=H).get_json(); assert me['can']['expenses'] is True

d = c.get('/api/m/expenses', headers=H).get_json()
assert d['can_edit'] and d['items'] == [] and d['totals']['sales'] == 30000 and {'id': 'printing', 'name': 'Posters and printing'} in d['categories']
r = c.post('/api/m/expenses', headers=H, json={'amount': '45,000', 'date': date.today().isoformat(), 'description': '20 posters',
                                               'category': 'printing', 'site_id': S1, 'paid_to': 'Mzizima'})
assert r.status_code == 200, r.text
E = r.get_json(); assert E['amount'] == 45000 and E['site'] == 'Hostel' and E['category_name'] == 'Posters and printing'
r = c.post('/api/m/expenses', headers=H, json={'amount': 0, 'date': date.today().isoformat(), 'description': 'x'})
assert r.status_code == 400 and 'amount' in r.get_json()['error']
r = c.post('/api/m/expenses', headers=H, json={'amount': 5000, 'date': date.today().isoformat(), 'description': 'Domain', 'site_id': None})
assert r.status_code == 200 and r.get_json()['site'] is None
r = c.post(f"/api/m/expenses/{E['id']}", headers=H, json={**E, 'amount': 40000}); assert r.get_json()['amount'] == 40000
d = c.get('/api/m/expenses?period=month', headers=H).get_json()
assert d['totals']['spent'] == 45000 and len(d['items']) == 2 and d['payback']['invested'] == 45000 and d['by_category']
assert d['months'] and d['months'][0]['running'] == d['totals']['net']
# one site (X-Site-Id): shared costs apart
d = c.get('/api/m/expenses', headers={**H, 'X-Site-Id': str(S1)}).get_json()
assert d['site'] == 'Hostel' and d['totals']['spent'] == 40000 and d['shared'] == 5000
# another business's expense is out of reach
assert c.post(f'/api/m/expenses/{OTHER}', headers=H, json={'amount': 1}).status_code == 404
assert c.delete(f'/api/m/expenses/{OTHER}', headers=H).status_code == 404

# the report
rep = c.get('/api/m/reports/finance?period=this_month', headers=H).get_json()
assert rep['totals']['sales'] == 30000 and rep['totals']['spent'] == 45000 and rep['totals']['fees'] == 900
assert rep['totals']['net'] == 30000 - 45000 - 900 and [s['name'] for s in rep['sites']][:2] == ['Hostel', 'Shop']
assert rep['packages'][0]['name'] == '1 Week' and len(rep['items']) == 2 and any(p['id'] == 'custom' for p in rep['periods'])
assert c.get('/api/m/reports/finance?period=custom&from=2026-01&to=2026-03', headers=H).get_json()['start'] == '2026-01'
pdf = c.get('/api/m/reports/finance.pdf?period=this_month', headers=H)
assert pdf.status_code == 200 and pdf.data.startswith(b'%PDF') and pdf.mimetype == 'application/pdf'
assert c.get('/api/m/reports/finance.pdf').status_code == 401

# delete
assert c.delete(f"/api/m/expenses/{E['id']}", headers=H).status_code == 200
with app.app_context(): assert db.session.get(Expense, E['id']) is None and db.session.get(Expense, OTHER) is not None

# partners look, change nothing; a site partner sees their site; staff not at all
P = token('partner1')
d = c.get('/api/m/expenses', headers=P).get_json(); assert d['can_edit'] is False and d['items']
assert c.post('/api/m/expenses', headers=P, json={'amount': 1000, 'date': date.today().isoformat(), 'description': 'x'}).status_code == 403
assert c.get('/api/m/reports/finance.pdf', headers=P).status_code == 200
SP = token('sitepart'); d = c.get('/api/m/expenses', headers=SP).get_json(); assert d['site'] == 'Shop' and d['items'] == []
ST = token('staff1')
assert c.get('/api/m/me', headers=ST).get_json()['can']['expenses'] is False
assert c.get('/api/m/expenses', headers=ST).status_code == 403 and c.get('/api/m/reports/finance', headers=ST).status_code == 403
# Kiswahili from the server
d = c.get('/api/m/expenses', headers={**H, 'Accept-Language': 'sw'}).get_json()
assert {'id': 'printing', 'name': 'Mabango na uchapishaji'} in d['categories']
print('MOBILE EXPENSES OK')
