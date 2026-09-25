import os, re, sys
from datetime import datetime
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db
import migrations
from models import Admin, BillingPlan
app.config.update(TESTING=True)
with app.app_context():
    db.create_all(); migrations.run(); __import__("models").BillingPlan.query.delete(); db.session.commit()
    a = Admin(username='owner', email='o@x.tz', tenant_id=1, role='owner', is_superadmin=True, email_verified_at=datetime.utcnow()); a.set_password('password1'); db.session.add(a); db.session.commit()
c = app.test_client()
r = c.get('/'); assert r.status_code == 200 and 'The Smart Way to Sell Wi-Fi' in r.text
assert 'Start with a free trial' in r.text and 'Popular' not in r.text          # no plans yet
assert 'href="/signup"' in r.text and 'href="/login"' in r.text
with app.app_context():
    db.session.add_all([BillingPlan(name='Starter', price=Decimal(15000), max_routers=1, sort_order=1),
                        BillingPlan(name='Business', price=Decimal(35000), max_routers=3, sort_order=2),
                        BillingPlan(name='ISP', price=Decimal(90000), sort_order=3),
                        BillingPlan(name='Hidden', price=Decimal(1), is_active=False)]); db.session.commit()
r = c.get('/'); assert 'TZS 15,000' in r.text and 'TZS 90,000' in r.text and 'Hidden' not in r.text
assert re.search(r'class="hl">\s*<span class="tag">Popular</span><br>\s*Business', r.text)
assert c.get('/dashboard').status_code == 302                                    # dashboard still private
r = c.get('/login'); tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text).group(1)
assert 'Back to SafeNet home' in r.text
r = c.post('/login', data={'username': 'owner', 'password': 'password1', 'csrf_token': tok})
assert r.headers['Location'].endswith('/dashboard')
r = c.get('/'); assert '>Dashboard</a>' in r.text and 'Log in</a>' in r.text     # nav shows Dashboard (band still offers Log in)
print('LANDING OK')
