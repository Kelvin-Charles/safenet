# Simulate the live database: tables exist WITHOUT the newest columns, then upgrade.
import os, sys
os.environ.update(DB_PASSWORD='x')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
from sqlalchemy import text, inspect
from app import app, db
import migrations
with app.app_context():
    db.create_all()
    db.session.execute(text("INSERT INTO tenants (name, slug, status, currency, payment_mode) VALUES ('SafeNet','safenet','active','TZS','platform')"))
    db.session.commit()
    for table, cols in (('tenants', ['payment_mode', 'clickpesa_client_id', 'clickpesa_api_key_enc', 'clickpesa_checksum_key_enc', 'fee_percent']),
                        ('payments', ['provider_account', 'fee_amount', 'net_amount'])):
        for c in cols:
            db.session.execute(text(f'ALTER TABLE {table} DROP COLUMN {c}'))
    db.session.commit()
    assert 'payment_mode' not in {c['name'] for c in inspect(db.engine).get_columns('tenants')}
    migrations.run(); migrations.run()
    assert migrations.default_tenant().payment_mode == 'platform'
    print('UPGRADE OK')
