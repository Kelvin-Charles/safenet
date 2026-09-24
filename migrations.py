"""Idempotent schema upgrades, run by `flask init-db` on every start.

db.create_all() creates missing tables but never alters existing ones, and the
FreeRADIUS tables come from database/schema.sql. Each step here checks the live
schema first, so it is safe on a fresh database and on one upgraded many times.
"""
from datetime import datetime, timedelta

from sqlalchemy import inspect, text

from config import Config
from models import db, Tenant, Admin

DEFAULT_TENANT_SLUG = 'safenet'
TENANT_TABLES = ('admins', 'plans', 'nas', 'radusers', 'vouchers', 'packages', 'payments')


def _q(name):
    """Quote an identifier (index `name` on plans is a keyword in MariaDB)."""
    return f'`{name}`' if db.engine.dialect.name == 'mysql' else f'"{name}"'


def _columns(table):
    return {c['name'] for c in inspect(db.engine).get_columns(table)}


def _indexes(table):
    insp = inspect(db.engine)
    names = {i['name'] for i in insp.get_indexes(table)}
    names |= {u['name'] for u in insp.get_unique_constraints(table) if u.get('name')}
    return names


def _add_column(table, column, ddl):
    if column not in _columns(table):
        db.session.execute(text(f'ALTER TABLE {_q(table)} ADD COLUMN {_q(column)} {ddl}'))
        db.session.commit()
        print(f'migrate: added {table}.{column}')
        return True
    return False


def _add_index(table, name, columns, unique=False):
    if name not in _indexes(table):
        cols = ', '.join(_q(c.strip()) for c in columns.split(','))
        db.session.execute(text(f'CREATE {"UNIQUE " if unique else ""}INDEX {_q(name)} ON {_q(table)} ({cols})'))
        db.session.commit()
        print(f'migrate: created index {name}')


def _drop_unique_index(table, name):
    insp = inspect(db.engine)
    unique = {i['name'] for i in insp.get_indexes(table) if i.get('unique')}
    unique |= {u['name'] for u in insp.get_unique_constraints(table) if u.get('name')}
    if name in unique:
        sql = f'DROP INDEX {_q(name)} ON {_q(table)}' if db.engine.dialect.name == 'mysql' else f'DROP INDEX {_q(name)}'
        db.session.execute(text(sql))
        db.session.commit()
        print(f'migrate: dropped unique index {name}')


def default_tenant():
    tenant = Tenant.query.filter_by(slug=DEFAULT_TENANT_SLUG).first()
    if not tenant:
        tenant = Tenant(name='SafeNet', slug=DEFAULT_TENANT_SLUG, status='active')
        db.session.add(tenant)
        db.session.commit()
        print('migrate: created default tenant')
    return tenant


def _as_datetime(value):
    """SQLite returns DATETIME columns from raw SQL as strings."""
    return datetime.fromisoformat(str(value)) if not isinstance(value, datetime) else value


def _default_tenant_id():
    """Default tenant's id via plain SQL, so it works before the ORM's columns exist."""
    row = db.session.execute(text('SELECT id FROM tenants WHERE slug = :s'), {'s': DEFAULT_TENANT_SLUG}).first()
    if row:
        return row[0]
    db.session.execute(text("INSERT INTO tenants (name, slug, status, currency, payment_mode, created_at) "
                            "VALUES ('SafeNet', :s, 'active', 'TZS', 'platform', :now)"),
                       {'s': DEFAULT_TENANT_SLUG, 'now': datetime.utcnow()})
    db.session.commit()
    print('migrate: created default tenant')
    return _default_tenant_id()


def run():
    # Columns of tables that are read during the upgrade come first: never use
    # ORM queries on a table before all of its model's columns exist.
    # Payments in both modes (phase 3)
    _add_column('tenants', 'payment_mode', "VARCHAR(16) NOT NULL DEFAULT 'platform'")
    _add_column('tenants', 'clickpesa_client_id', 'VARCHAR(64) NULL')
    _add_column('tenants', 'clickpesa_api_key_enc', 'TEXT NULL')
    _add_column('tenants', 'clickpesa_checksum_key_enc', 'TEXT NULL')
    _add_column('tenants', 'fee_percent', 'NUMERIC(5, 2) NULL')
    _add_column('tenants', 'billing_plan_id', 'INTEGER NULL')
    _add_column('tenants', 'paid_until', 'DATETIME NULL')
    if _add_column('tenants', 'service_until', 'DATETIME NULL'):
        # Trials that existed before billing: service ends after the trial + grace
        grace = timedelta(days=Config.BILLING_GRACE_DAYS)
        for tid, trial_end in db.session.execute(text(
                "SELECT id, trial_ends_at FROM tenants WHERE status = 'trial' AND trial_ends_at IS NOT NULL")).all():
            db.session.execute(text('UPDATE tenants SET service_until = :u WHERE id = :i'),
                               {'u': _as_datetime(trial_end) + grace, 'i': tid})
        db.session.commit()
    _add_column('tenants', 'billing_notice', 'VARCHAR(32) NULL')
    # Captive portal customisation
    _add_column('tenants', 'portal_color', 'VARCHAR(7) NULL')
    _add_column('tenants', 'portal_style', 'VARCHAR(16) NULL')
    _add_column('tenants', 'portal_title', 'VARCHAR(80) NULL')
    _add_column('tenants', 'portal_message', 'VARCHAR(300) NULL')
    _add_column('tenants', 'portal_language', 'VARCHAR(2) NULL')
    _add_column('tenants', 'portal_show_voucher', 'BOOLEAN NOT NULL DEFAULT 1')
    _add_column('tenants', 'portal_show_packages', 'BOOLEAN NOT NULL DEFAULT 1')
    _add_column('tenants', 'portal_logo', 'MEDIUMBLOB NULL' if db.engine.dialect.name == 'mysql' else 'BLOB NULL')
    _add_column('tenants', 'portal_logo_type', 'VARCHAR(32) NULL')
    _add_column('tenants', 'portal_logo_at', 'DATETIME NULL')
    _add_column('tenants', 'block_tethering', 'BOOLEAN NOT NULL DEFAULT 1')
    _add_column('payments', 'provider_account', "VARCHAR(16) NOT NULL DEFAULT 'platform'")
    _add_column('payments', 'fee_amount', 'NUMERIC(10, 2) NULL DEFAULT 0')
    _add_column('payments', 'net_amount', 'NUMERIC(10, 2) NULL')

    tid = _default_tenant_id()

    # Multi-tenancy: every owned row belongs to a tenant; existing data -> default tenant
    for table in TENANT_TABLES:
        _add_column(table, 'tenant_id', 'INTEGER NULL')
        db.session.execute(text(f'UPDATE {table} SET tenant_id = :t WHERE tenant_id IS NULL'), {'t': tid})
        db.session.commit()
        _add_index(table, f'ix_{table}_tenant_id', 'tenant_id')

    # Admin roles; admins that existed before tenants are the platform operators
    new_roles = _add_column('admins', 'role', "VARCHAR(16) NOT NULL DEFAULT 'owner'")
    _add_column('admins', 'is_superadmin', 'BOOLEAN NOT NULL DEFAULT 0')
    if _add_column('admins', 'email_verified_at', 'DATETIME NULL') or new_roles:
        db.session.execute(text('UPDATE admins SET is_superadmin = 1, email_verified_at = :now '
                                'WHERE email_verified_at IS NULL'), {'now': datetime.utcnow()})
        db.session.commit()

    # Plans: names unique per tenant; RADIUS group name fixed and globally unique
    _add_column('plans', 'group_name', 'VARCHAR(64) NULL')
    db.session.execute(text('UPDATE plans SET group_name = name WHERE group_name IS NULL'))
    db.session.commit()
    _drop_unique_index('plans', 'name')           # schema.sql: UNIQUE KEY name (name)
    _drop_unique_index('plans', 'ix_plans_name')  # older create_all: unique index on name
    _add_index('plans', 'ix_plans_name', 'name')
    _add_index('plans', 'uq_plans_tenant_name', 'tenant_id, name', unique=True)
    _add_index('plans', 'uq_plans_group_name', 'group_name', unique=True)

    db.session.execute(text('UPDATE payments SET fee_amount = 0, net_amount = amount WHERE net_amount IS NULL'))
    db.session.commit()

    # One code, limited devices (anti-sharing)
    for table in ('vouchers', 'packages', 'payments'):
        _add_column(table, 'max_devices', 'INTEGER NOT NULL DEFAULT 1')

    # Free-trial (marketing) vouchers: one per phone
    _add_column('vouchers', 'is_free', 'BOOLEAN NOT NULL DEFAULT 0')
    _add_column('vouchers', 'first_mac', 'VARCHAR(17)')

    # Plan limits for customers and staff, and a yearly price
    _add_column('billing_plans', 'price_yearly', 'NUMERIC(10, 2)')
    _add_column('billing_plans', 'max_customers', 'INTEGER')
    _add_column('billing_plans', 'max_staff', 'INTEGER')
    _seed_billing_plans()


STARTER_PLANS = (
    # name, monthly, yearly, customers, routers, sites (gateways), staff
    ('Starter', 10000, 110000, 200, 1, 1, 2),
    ('Business', 20000, 220000, 400, 10, 10, 10),
    ('Economic', 30000, 339000, 1000, 20, 16, 20),
)


def _seed_billing_plans():
    """First-time plans, only while there are none (edit them in Platform: Billing)."""
    from models import BillingPlan
    if db.session.query(BillingPlan.id).first():
        return
    for order, (name, month, year, customers, routers, sites, staff) in enumerate(STARTER_PLANS):
        db.session.add(BillingPlan(name=name, price=month, price_yearly=year, currency='TZS', max_customers=customers,
                                   max_routers=routers, max_gateways=sites, max_staff=staff, sort_order=order))
    db.session.commit()
    print('migrate: added starter billing plans')
