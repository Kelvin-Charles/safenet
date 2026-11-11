"""Financial report: income statement for a period on screen and as a PDF (periods, sites, logo, Kiswahili, who may see it)."""
import base64, io, os, re, sys, zlib
from datetime import datetime, timedelta, date
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db, _finance_report, _month_add
import migrations
from models import Admin, Tenant, Site, Voucher, Payment, Expense
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
now = datetime.utcnow()
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Kpstar WiFi', slug='kpstar', status='active', portal_color='#0A6E4F'); db.session.add(t); db.session.flush(); T = t.id
    o = Tenant(name='Other', slug='other', status='active'); db.session.add(o); db.session.flush()
    for u, role, tid in (('owner1', 'owner', T), ('staff1', 'staff', T), ('partner1', 'viewer', T), ('other1', 'owner', o.id)):
        a = Admin(username=u, email=f'{u}@x.tz', tenant_id=tid, role=role, email_verified_at=now); a.set_password('password1'); db.session.add(a)
    s1, s2 = Site(tenant_id=T, name='Hostel'), Site(tenant_id=T, name='Shop'); db.session.add_all([s1, s2]); db.session.flush()
    S1, S2 = s1.id, s2.id
    for i, (site, amount, days, pkg) in enumerate(((S1, 2000, 1, '1 Day'), (S1, 10000, 2, '1 Week'), (S2, 2000, 3, '1 Day'), (S1, 50000, 70, '1 Month'))):
        db.session.add(Payment(tenant_id=T, reference=f'R{i}', phone='255712000001', amount=Decimal(amount), validity_minutes=60, package_name=pkg,
                               status='paid', paid_at=now - timedelta(days=days), site_id=site, provider_account='platform', fee_amount=Decimal(amount) * Decimal('0.03')))
    db.session.add(Payment(tenant_id=o.id, reference='OTHER', phone='255712000009', amount=Decimal(777777), validity_minutes=60, status='paid', paid_at=now))
    db.session.add(Expense(tenant_id=T, site_id=S1, spent_on=date.today(), category='printing', description='Posters <b>&</b> flyers', paid_to='Mzizima', amount=Decimal(8000)))
    db.session.add(Expense(tenant_id=T, site_id=None, spent_on=date.today(), category='other', description='Domain', amount=Decimal(3000)))
    db.session.add(Expense(tenant_id=T, site_id=S1, spent_on=date.today() - timedelta(days=75), category='equipment', description='Router', amount=Decimal(90000)))
    db.session.add(Expense(tenant_id=o.id, spent_on=date.today(), category='other', description='Secret', amount=Decimal(1)))
    db.session.commit()

def login(user):
    c = app.test_client(); r = c.get('/login')
    c.post('/login', data={'username': user, 'password': 'password1', 'csrf_token': tok(r.text)})
    return c

def text(pdf):
    """Visible text of a ReportLab PDF (its content streams are Flate-compressed)."""
    out = []
    for m in re.finditer(rb'stream\r?\n(.*?)endstream', pdf, re.S):
        raw = m.group(1).strip()
        try:
            if raw.endswith(b'~>'):
                raw = base64.a85decode(raw[:-2].replace(b'\n', b''))
            out.append(zlib.decompress(raw).decode('latin-1'))
        except Exception:
            pass
    return ''.join(re.findall(r'\((.*?)\)\s*Tj', ''.join(out)))

# the numbers: this month (all within the last 3 days, unless the month just started)
with app.test_request_context():
    from flask_login import login_user
    login_user(Admin.query.filter_by(username='owner1').one())
    month = (now + timedelta(hours=3)).strftime('%Y-%m')
    rep = _finance_report(T, None, 'custom', _month_add(month, -3), month)
    t = rep['totals']
    assert t['sales'] == 64000 and t['spent'] == 101000 and t['fees'] == Decimal('1920'), t
    assert t['out'] == t['spent'] + t['fees'] and t['net'] == t['sales'] - t['out']
    assert len(rep['rows']) == 4 and rep['all_sites'] and [s['name'] for s in rep['sites']][:2] == ['Hostel', 'Shop']
    assert sum(s['sales'] for s in rep['sites']) == t['sales'] and sum(s['out'] for s in rep['sites']) == t['out']   # sites add up
    assert {p[0] for p in rep['packages']} == {'1 Day', '1 Week', '1 Month'}
    assert rep['payback']['invested'] == 101000
    one = _finance_report(T, db.session.get(Site, S2), 'custom', month, month)
    assert one['totals']['spent'] == 0 and one['sites'] == [] and not one['all_sites']
    bad = _finance_report(T, None, 'custom', 'nonsense', '2026-13')
    assert bad['period'] == 'this_month' and bad['start'] == bad['end'] == month
    swapped = _finance_report(T, None, 'custom', month, _month_add(month, -2))
    assert swapped['start'] < swapped['end']
    assert _month_add('2026-01', -1) == '2025-12' and _month_add('2026-12', 1) == '2027-01'

c = login('owner1')
page = c.get('/reports/finance?period=custom&from=' + _month_add(month, -3) + '&to=' + month)
assert page.status_code == 200 and 'Income statement' in page.text and 'Sites compared' in page.text and 'Download PDF' in page.text
assert '777,777' not in page.text and 'Secret' not in page.text
assert 'Posters &lt;b&gt;&amp;&lt;/b&gt; flyers' in page.text
for period in ('this_month', 'last_month', 'this_quarter', 'last_quarter', 'this_year', 'last_year', '12m', 'all', 'weird'):
    assert c.get(f'/reports/finance?period={period}').status_code == 200, period
    r = c.get(f'/reports/finance.pdf?period={period}')
    assert r.status_code == 200 and r.data.startswith(b'%PDF') and r.mimetype == 'application/pdf', period
r = c.get('/reports/finance.pdf?period=custom&from=' + _month_add(month, -3) + '&to=' + month)
assert 'attachment' in r.headers['Content-Disposition'] and 'financial-report-kpstar-wifi' in r.headers['Content-Disposition']
words = text(r.data)
for w in ('Kpstar WiFi', 'FINANCIAL REPORT', 'Income statement', 'Sites compared', 'Expense details', 'Posters <b&> flyers'.replace('<b&>', '<b>&</b>'),
          'Hostel', 'Mzizima', 'Page 1 of'):
    assert w.replace('(', '\\(') in words or w in words, w
assert '777,777' not in words and 'Secret' not in words
assert 'inline' in c.get('/reports/finance.pdf?period=this_month&view=1').headers['Content-Disposition']
# one site picked in the top bar
with c.session_transaction() as s: s['site_id'] = S2
w = text(c.get('/reports/finance.pdf?period=this_month').data)
assert 'Shop' in w and 'Sites compared' not in w and 'Posters' not in w
with c.session_transaction() as s: s.pop('site_id')
# the tenant's logo goes in the header; a broken one is skipped
from PIL import Image
buf = io.BytesIO(); Image.new('RGB', (64, 64), (200, 30, 30)).save(buf, 'PNG')
with app.app_context():
    tt = db.session.get(Tenant, T); tt.portal_logo, tt.portal_logo_type = buf.getvalue(), 'image/png'; db.session.commit()
r = c.get('/reports/finance.pdf?period=this_month'); assert r.status_code == 200 and b'/Subtype /Image' in r.data
with app.app_context():
    tt = db.session.get(Tenant, T); tt.portal_logo = b'not an image'; db.session.commit()
assert c.get('/reports/finance.pdf?period=this_month').status_code == 200
# Kiswahili
c.post('/language', data={'csrf_token': tok(c.get('/dashboard').text), 'lang': 'sw'})
assert 'Taarifa ya fedha' in c.get('/reports/finance').text
assert 'TAARIFA YA FEDHA' in text(c.get('/reports/finance.pdf?period=12m').data)
# who may see it
p = login('partner1'); assert p.get('/reports/finance').status_code == 200 and p.get('/reports/finance.pdf').status_code == 200
s = login('staff1'); assert s.get('/reports/finance').status_code == 302 and s.get('/reports/finance.pdf').status_code == 403
x = login('other1'); assert 'Posters' not in text(x.get('/reports/finance.pdf?period=12m').data)
print('FINANCE REPORT OK')
