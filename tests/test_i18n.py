"""Owner dashboard in Kiswahili: every wrapped text has a translation, placeholders match, pages render in both."""
import glob, os, re, sys
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import i18n

# 1. every _('...') in templates and tr('...') in the code has Kiswahili, with the same {placeholders}
LIT = r"""\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*[,)]"""
found = {}
for path in glob.glob('templates/**/*.html', recursive=True):
    for m in re.finditer(r'(?<![\w.])_' + LIT, open(path).read()):
        found.setdefault((m.group(1) if m.group(1) is not None else m.group(2)).replace("\\'", "'").replace('\\"', '"'), path)
for path, fn in (('app.py', 'tr'), ('tenancy.py', 'tr'), ('forms.py', 'L')):
    if os.path.exists(path):
        for m in re.finditer(r'(?<![\w.])' + fn + LIT, open(path).read()):
            found.setdefault((m.group(1) if m.group(1) is not None else m.group(2)).replace("\\'", "'").replace('\\"', '"'), path)
missing = sorted(f'{where}: {text}' for text, where in found.items() if text not in i18n.SW)
assert not missing, f'{len(missing)} without Kiswahili:\n' + '\n'.join(missing[:60])
ph = lambda s: sorted(re.findall(r'\{(\w*)\}', s))
wrong = [en for en, sw in i18n.SW.items() if ph(en) != ph(sw)]
assert not wrong, 'placeholders differ: ' + '; '.join(wrong[:20])
print(f'{len(found)} texts wrapped, {len(i18n.SW)} translations')

# 2. switching language, and the main pages in both languages
from app import app, db
import migrations
from models import Admin
app.config.update(TESTING=True)
tok = lambda h: re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h).group(1)
with app.app_context():
    db.create_all(); migrations.run()
    a = Admin(username='owner', email='o@x.tz', tenant_id=1, role='owner', email_verified_at=datetime.utcnow()); a.set_password('password1')
    db.session.add(a); db.session.commit()
c = app.test_client(); r = c.get('/login'); c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok(r.text)})
d = c.get('/dashboard').text
assert '>Dashibodi<' not in d and 'Kiswahili' in d
r = c.post('/language', data={'csrf_token': tok(d), 'lang': 'sw', 'next': '/vouchers'})
assert r.status_code == 302 and r.headers['Location'].endswith('/vouchers') and 'sn_lang=sw' in r.headers.get('Set-Cookie', '')
with app.app_context(): assert Admin.query.filter_by(username='owner').one().language == 'sw'
d = c.get('/dashboard').text
assert 'Dashibodi' in d and 'lang="sw"' in d and 'English' in d
pages = ['/dashboard', '/live', '/sites', '/users', '/vouchers', '/vouchers/generate', '/payments', '/earnings', '/packages', '/packages/add',
         '/plans', '/gateways', '/routers', '/nas', '/accounting', '/auth-logs', '/billing', '/settings/portal', '/settings',
         '/settings/payments', '/team', '/team/add', '/radius-features', '/users/add', '/plans/add', '/nas/add']
for lang in ('sw', 'en'):
    c.post('/language', data={'csrf_token': tok(c.get('/dashboard').text), 'lang': lang})
    for url in pages:
        r = c.get(url)
        assert r.status_code in (200, 302), (lang, url, r.status_code)
assert c.post('/language', data={'lang': 'sw'}).status_code == 400            # CSRF
# before login: the cookie decides
anon = app.test_client(); anon.set_cookie('sn_lang', 'sw')
assert anon.get('/login').status_code == 200
print('I18N OK')
