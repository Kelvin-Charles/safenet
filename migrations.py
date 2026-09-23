"""Idempotent schema upgrades, run by `flask init-db` on every start.

db.create_all() creates missing tables but never alters existing ones, and the
FreeRADIUS tables come from database/schema.sql. Each step here checks the live
schema first, so it is safe on a fresh database and on one upgraded many times.
"""
from datetime import datetime

from sqlalchemy import inspect, text

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


def run():
    tenant = default_tenant()

    # Multi-tenancy: every owned row belongs to a tenant; existing data -> default tenant
    for table in TENANT_TABLES:
        _add_column(table, 'tenant_id', 'INTEGER NULL')
        db.session.execute(text(f'UPDATE {table} SET tenant_id = :t WHERE tenant_id IS NULL'), {'t': tenant.id})
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
