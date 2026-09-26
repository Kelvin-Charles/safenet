"""Public setup guides: every page renders, links work, server values are filled in."""
import os, re, sys
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, OMADA_HOSTED_HOST='radius.example.tz', PUBLIC_URL='https://radius.example.tz')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db, DOC_PAGES
import migrations
app.config.update(TESTING=True)
with app.app_context():
    db.create_all(); migrations.run()
c = app.test_client()
seen = set()
for p in DOC_PAGES:
    url = '/docs' if p['slug'] == 'start' else f"/docs/{p['slug']}"
    r = c.get(url)
    assert r.status_code == 200, (url, r.status_code)
    html = r.text
    assert p['title'] in html and '{{' not in html and '{%' not in html, url
    for href in re.findall(r'href="(/docs[^"#]*)', html):
        seen.add(href)
assert c.get('/docs/nope').status_code == 404
for href in seen:
    assert c.get(href).status_code == 200, href
omada = c.get('/docs/omada').text
assert '<code>radius.example.tz</code>' in omada and 'https://radius.example.tz/omada/' in omada
gw = c.get('/docs/gateway').text
assert 'git clone https://github.com/Kelvin-Charles/safenet.git' in gw and 'SAFENET_API_URL="https://radius.example.tz"' in gw
assert 'Setup guides' in c.get('/').text                       # linked from the homepage
print(f'DOCS OK ({len(DOC_PAGES)} guides)')
