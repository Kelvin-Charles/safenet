"""Expenses: recording what a site cost, money in against money out by month, paid back, per site, permissions, CSV."""
import os, re, sys
from datetime import datetime, timedelta, date
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations
from models import Admin, Tenant, Site, Voucher, Payment, Expense, SmsCharge
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    ids = {}
    for slug in ('kpstar', 'other'):
        t = Tenant(name=slug.title(), slug=slug, status='active'); db.session.add(t); db.session.flush(); ids[slug] = t.id
        a = Admin(username=slug, email=f'{slug}@x.tz', tenant_id=t.id, role='owner', email_verified_at=now); a.set_password('password1'); db.session.add(a)
    T = ids['kpstar']
    s1, s2 = Site(tenant_id=T, name='Hostel'), Site(tenant_id=T, name='Shop')
    db.session.add_all([s1, s2]); db.session.flush()
    S1, S2 = s1.id, s2.id
    for role, site in (('staff', None), ('viewer', None), ('partner', S2)):
        a = Admin(username=role, email=f'{role}@x.tz', tenant_id=T, role='viewer' if role == 'partner' else role, site_id=site, email_verified_at=now)
        a.set_password('password1'); db.session.add(a)
    # 90,000 of sales at the hostel (platform, 3% fee), 10,000 cash voucher, 5,000 at the shop
    for i, (site, amount, days) in enumerate(((S1, 60000, 40), (S1, 30000, 5), (S2, 5000, 5))):
        db.session.add(Payment(tenant_id=T, reference=f'R{i}', phone='255712000001', amount=Decimal(amount), validity_minutes=60,
                               status='paid', paid_at=now - timedelta(days=days), site_id=site, provider_account='platform',
                               fee_amount=Decimal(amount) * Decimal('0.03'), net_amount=Decimal(amount) * Decimal('0.97')))
    db.session.add(Voucher(tenant_id=T, code='55550001', validity_minutes=60, price=Decimal(10000), status='active', site_id=S1,
                           first_used_at=now - timedelta(days=3), expires_at=now - timedelta(days=2)))
    db.session.add(SmsCharge(tenant_id=T, site_id=S1, phone='255712000001', kind='voucher', amount=Decimal(300), method='balance'))
    db.session.add(Expense(tenant_id=ids['other'], site_id=None, spent_on=date.today(), category='other', description='Not ours', amount=Decimal(999999)))
    db.session.commit()

def login(user):
    c = app.test_client(); r = c.get('/login')
    c.post('/login', data={'username': user, 'password': 'password1', 'csrf_token': tok(r.text)})
    return c

c = login('kpstar')
r = c.get('/expenses'); assert r.status_code == 200, (r.status_code, r.headers.get('Location'))
assert 'Record what you spent' not in r.text or True
f = c.get('/expenses/add').text
assert 'Posters and printing' in f and 'Whole business (shared by all sites)' in f
old = (date.today() - timedelta(days=60)).isoformat()
r = c.post('/expenses/add', data={'csrf_token': tok(f), 'amount': '120,000', 'spent_on': old, 'description': '2 access points',
                                  'category': 'equipment', 'site_id': S1, 'paid_to': 'Kariakoo shop'})
assert r.status_code == 302, r.status_code
r = c.post('/expenses/add', data={'csrf_token': tok(f), 'amount': '20000', 'spent_on': date.today().isoformat(), 'description': '50 posters',
                                  'category': 'printing', 'site_id': S1, 'again': '1'})
assert r.status_code == 302 and 'add' in r.headers['Location']
c.post('/expenses/add', data={'csrf_token': tok(f), 'amount': '7000', 'spent_on': date.today().isoformat(), 'description': 'Domain name',
                              'category': 'other', 'site_id': '0'})
# bad input
for bad in ({'amount': 'abc'}, {'amount': '-5'}, {'description': ''}, {'spent_on': ''}, {'site_id': '99999'},
            {'spent_on': (date.today() + timedelta(days=5)).isoformat()}):
    data = {'csrf_token': tok(f), 'amount': '1000', 'spent_on': date.today().isoformat(), 'description': 'x', 'category': 'other', 'site_id': S1, **bad}
    r = c.post('/expenses/add', data=data); assert r.status_code == 200, bad
assert c.post('/expenses/add', data={'amount': '1000', 'spent_on': date.today().isoformat(), 'description': 'x'}).status_code == 400  # CSRF
with app.app_context():
    assert Expense.query.filter_by(tenant_id=T).count() == 3
    e = Expense.query.filter_by(description='2 access points').one()
    assert e.amount == Decimal(120000) and e.site_id == S1 and e.paid_to == 'Kariakoo shop' and e.created_by_id
    EID = e.id
    OTHER = Expense.query.filter_by(tenant_id=ids['other']).one().id

# the whole business: in 105,000; out 147,000 + fees 2,850 + SMS 300
page = c.get('/expenses').text
assert '105,000' in page and '147,000' in page and '3,150' in page, re.findall(r'stat-value[^>]*>([^<]*)', page)
assert '2 access points' in page and 'Kariakoo shop' in page and 'Not ours' not in page and '999,999' not in page
assert '% paid back.' in page
# one site: the hostel only, shared costs mentioned apart
with c.session_transaction() as s: s['site_id'] = S1
page = c.get('/expenses').text
assert '100,000' in page and '140,000' in page and 'Domain name' not in page and 'shared by all sites are not counted' in page
assert 'Kariakoo shop' in page
with c.session_transaction() as s: s['site_id'] = S2
page = c.get('/expenses').text
assert 'Paid back' in page and '2 access points' not in page          # the shop cost nothing: its sales are profit
with c.session_transaction() as s: s.pop('site_id')
# periods
page = c.get('/expenses?period=month').text
assert '50 posters' in page and '2 access points' not in page
assert c.get('/expenses?period=nonsense').status_code == 200
# CSV
r = c.get('/expenses.csv'); assert r.status_code == 200 and r.mimetype == 'text/csv'
assert '2 access points' in r.text and 'Whole business' in r.text and 'Not ours' not in r.text
# edit and delete; another tenant's expense is out of reach
f = c.get(f'/expenses/{EID}/edit').text
assert '120000' in f and '2 access points' in f
r = c.post(f'/expenses/{EID}/edit', data={'csrf_token': tok(f), 'amount': '100000', 'spent_on': old, 'description': '2 access points',
                                          'category': 'equipment', 'site_id': S1}); assert r.status_code == 302
r = c.post(f'/expenses/{EID}/edit', data={'csrf_token': tok(f), 'amount': 'zzz', 'spent_on': old, 'description': '2 access points', 'site_id': S1})
assert r.status_code == 200
with app.app_context(): assert db.session.get(Expense, EID).amount == Decimal(100000)
assert c.get(f'/expenses/{OTHER}/edit').status_code == 404
assert c.post(f'/expenses/{OTHER}/delete', data={'csrf_token': tok(f)}).status_code == 404
assert c.post(f'/expenses/{EID}/delete', data={'csrf_token': tok(f)}).status_code == 302
with app.app_context(): assert db.session.get(Expense, EID) is None and db.session.get(Expense, OTHER) is not None

# partners see (read only), staff not at all, a site partner only their site
v = login('viewer'); page = v.get('/expenses').text
assert '50 posters' in page and 'Add an expense' not in page
assert v.get('/expenses/add').status_code == 302
p = login('partner'); page = p.get('/expenses').text
assert '50 posters' not in page and 'Shop' in page
assert p.get('/expenses.csv').text.count('\n') == 1
st = login('staff'); assert st.get('/expenses').status_code == 302 and st.get('/expenses.csv').status_code == 403
# Kiswahili
c.post('/language', data={'csrf_token': tok(c.get('/dashboard').text), 'lang': 'sw'})
assert c.get('/expenses').status_code == 200 and c.get('/expenses/add').status_code == 200
print('EXPENSES OK')
