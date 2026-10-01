"""SafeNet Pay uses Snippe by default; ClickPesa only while Snippe has no key; new tenants are on SafeNet Pay."""
import os, sys
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, CLICKPESA_CLIENT_ID='cp', CLICKPESA_API_KEY='cpk')
os.environ.pop('PAYMENT_PROVIDER', None); os.environ.pop('SNIPPE_API_KEY', None)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from app import app, db, platform_provider
import migrations, secretbox
from models import Tenant, PlatformSetting
assert config.Config.PAYMENT_PROVIDER == 'snippe'
with app.app_context():
    db.create_all(); migrations.run()
    assert platform_provider() == 'clickpesa'            # no Snippe key yet: keep taking payments with ClickPesa
    db.session.add(PlatformSetting(key='snippe_api_key', value=secretbox.encrypt('snp_' + 'a' * 40))); db.session.commit()
    assert platform_provider() == 'snippe'               # key saved: Snippe by default
    db.session.add(PlatformSetting(key='payment_provider', value='clickpesa')); db.session.commit()
    assert platform_provider() == 'clickpesa'            # the platform admin's explicit choice wins
    t = Tenant(name='New', slug='new', status='trial'); db.session.add(t); db.session.commit()
    assert t.payment_mode == 'platform' and t.own_provider == 'snippe'   # SafeNet Pay; Snippe first if they get their own
print('DEFAULT PROVIDER OK')
