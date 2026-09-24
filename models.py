from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import bcrypt

db = SQLAlchemy()


class Tenant(db.Model):
    """A customer business (workspace) with its own users, routers and sales."""
    __tablename__ = 'tenants'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default='trial')  # trial, active, suspended
    trial_ends_at = db.Column(db.DateTime)
    phone = db.Column(db.String(20))
    # Guest-facing branding (splash page, printed vouchers)
    hotspot_name = db.Column(db.String(64))
    support_phone = db.Column(db.String(32))
    currency = db.Column(db.String(3), nullable=False, default='TZS')
    terms = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Package sales: 'platform' = paid into the platform's ClickPesa, tenant withdraws
    # its balance; 'own' = paid straight into the tenant's ClickPesa account.
    payment_mode = db.Column(db.String(16), nullable=False, default='platform')
    clickpesa_client_id = db.Column(db.String(64))
    clickpesa_api_key_enc = db.Column(db.Text)        # secretbox-encrypted
    clickpesa_checksum_key_enc = db.Column(db.Text)   # secretbox-encrypted
    fee_percent = db.Column(db.Numeric(5, 2))         # platform fee; NULL = PLATFORM_FEE_PERCENT
    # Subscription: paid_until = end of the paid period; service_until = when its
    # guests lose service (end of trial or paid period + grace). NULL = no limit.
    billing_plan_id = db.Column(db.Integer, db.ForeignKey('billing_plans.id', ondelete='SET NULL'))
    paid_until = db.Column(db.DateTime)
    service_until = db.Column(db.DateTime)
    billing_notice = db.Column(db.String(32))          # last reminder sent, e.g. "pre:2026-10-01"
    # Captive portal look (see gateway/portal_ui.py); NULL = SafeNet defaults
    portal_color = db.Column(db.String(7))
    portal_style = db.Column(db.String(16))            # gradient, solid, light
    portal_title = db.Column(db.String(80))
    portal_message = db.Column(db.String(300))
    portal_language = db.Column(db.String(2))          # en, sw
    portal_show_voucher = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    portal_show_packages = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    portal_logo = db.deferred(db.Column(db.LargeBinary(length=16777215)))   # MEDIUMBLOB; loaded only when needed
    portal_logo_type = db.Column(db.String(32))
    portal_logo_at = db.Column(db.DateTime)
    # Drop traffic forwarded by a guest's own hotspot (TTL 63/127) at the gateway
    block_tethering = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())

    billing_plan = db.relationship('BillingPlan')

    @property
    def display_hotspot_name(self):
        return self.hotspot_name or self.name

    @property
    def trial_days_left(self):
        if self.status != 'trial' or not self.trial_ends_at:
            return None
        return max(0, (self.trial_ends_at - datetime.utcnow()).days + 1)

    def __repr__(self):
        return f'<Tenant {self.slug}>'


class Gateway(db.Model):
    """A SafeNet gateway box; authenticates to the API with its own key."""
    __tablename__ = 'gateways'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    key_prefix = db.Column(db.String(8), nullable=False)       # shown in the UI to tell keys apart
    key_hash = db.Column(db.String(64), unique=True, nullable=False)  # sha256 of the full key
    is_active = db.Column(db.Boolean, default=True)
    last_seen_at = db.Column(db.DateTime)
    last_ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<Gateway {self.name}>'


ROLES = ('staff', 'admin', 'owner')   # increasing permissions


class Admin(UserMixin, db.Model):
    """Admin users for the management interface"""
    __tablename__ = 'admins'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), index=True)
    role = db.Column(db.String(16), nullable=False, default='owner')
    is_superadmin = db.Column(db.Boolean, nullable=False, default=False)  # platform operator
    email_verified_at = db.Column(db.DateTime)

    tenant = db.relationship('Tenant')

    def has_role(self, role):
        return self.is_superadmin or ROLES.index(self.role or 'staff') >= ROLES.index(role)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        """Verify password"""
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def __repr__(self):
        return f'<Admin {self.username}>'


class Plan(db.Model):
    """Service plans/groups"""
    __tablename__ = 'plans'
    __table_args__ = (db.UniqueConstraint('tenant_id', 'name', name='uq_plans_tenant_name'),)
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), index=True)
    name = db.Column(db.String(64), nullable=False, index=True)
    # FreeRADIUS group name (radusergroup/radgroupreply). Fixed at creation so
    # renaming a plan never orphans its RADIUS rows; unique across tenants
    # (index uq_plans_group_name, created by migrations.py).
    group_name = db.Column(db.String(64))
    description = db.Column(db.Text)
    vendor = db.Column(db.String(32), default='standard')  # Default vendor for this plan
    is_active = db.Column(db.Boolean, default=True)
    # Bandwidth limits (default for plan)
    upload_speed = db.Column(db.String(32))  # e.g., "10M", "1G"
    download_speed = db.Column(db.String(32))  # e.g., "10M", "1G"
    data_cap = db.Column(db.BigInteger)  # Data cap in bytes (0 = unlimited)
    data_cap_period = db.Column(db.String(10), default='monthly')  # daily, weekly, monthly
    last_reset = db.Column(db.DateTime)  # Last time data cap was reset
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    attributes = db.relationship('PlanAttribute', backref='plan', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Plan {self.name}>'


class PlanAttribute(db.Model):
    """Dynamic RADIUS attributes for plans (vendor-agnostic)"""
    __tablename__ = 'plan_attributes'
    
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)
    attribute = db.Column(db.String(64), nullable=False)
    op = db.Column(db.String(2), nullable=False, default=':=')  # :=, ==, +=, etc.
    value = db.Column(db.String(253), nullable=False)
    vendor = db.Column(db.String(32))  # NULL for standard, or vendor name
    priority = db.Column(db.Integer, default=0)  # For ordering
    
    def __repr__(self):
        vendor_str = f' ({self.vendor})' if self.vendor else ''
        return f'<PlanAttribute {self.attribute}{vendor_str}>'


# FreeRADIUS Standard Tables

class RadCheck(db.Model):
    """User authentication data (FreeRADIUS radcheck)"""
    __tablename__ = 'radcheck'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    attribute = db.Column(db.String(64), nullable=False)
    op = db.Column(db.String(2), nullable=False, default=':=')
    value = db.Column(db.String(253), nullable=False)
    
    def __repr__(self):
        return f'<RadCheck {self.username}>'


class RadReply(db.Model):
    """User reply attributes (FreeRADIUS radreply)"""
    __tablename__ = 'radreply'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    attribute = db.Column(db.String(64), nullable=False)
    op = db.Column(db.String(2), nullable=False, default=':=')
    value = db.Column(db.String(253), nullable=False)
    
    def __repr__(self):
        return f'<RadReply {self.username}>'


class RadUserGroup(db.Model):
    """User to group mapping (FreeRADIUS radusergroup)"""
    __tablename__ = 'radusergroup'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    groupname = db.Column(db.String(64), nullable=False, index=True)
    priority = db.Column(db.Integer, nullable=False, default=1)
    
    def __repr__(self):
        return f'<RadUserGroup {self.username} -> {self.groupname}>'


class RadGroupCheck(db.Model):
    """Group check attributes (FreeRADIUS radgroupcheck)"""
    __tablename__ = 'radgroupcheck'
    
    id = db.Column(db.Integer, primary_key=True)
    groupname = db.Column(db.String(64), nullable=False, index=True)
    attribute = db.Column(db.String(64), nullable=False)
    op = db.Column(db.String(2), nullable=False, default=':=')
    value = db.Column(db.String(253), nullable=False)
    
    def __repr__(self):
        return f'<RadGroupCheck {self.groupname}>'


class RadGroupReply(db.Model):
    """Group reply attributes (FreeRADIUS radgroupreply)"""
    __tablename__ = 'radgroupreply'
    
    id = db.Column(db.Integer, primary_key=True)
    groupname = db.Column(db.String(64), nullable=False, index=True)
    attribute = db.Column(db.String(64), nullable=False)
    op = db.Column(db.String(2), nullable=False, default=':=')
    value = db.Column(db.String(253), nullable=False)
    priority = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<RadGroupReply {self.groupname}>'


class RadAcct(db.Model):
    """Accounting data (FreeRADIUS radacct)"""
    __tablename__ = 'radacct'
    
    # BIGINT AUTO_INCREMENT in MariaDB; SQLite (tests) only auto-numbers INTEGER keys
    radacctid = db.Column(db.BigInteger().with_variant(db.Integer, 'sqlite'), primary_key=True, autoincrement=True)
    acctsessionid = db.Column(db.String(64), nullable=False, index=True)
    acctuniqueid = db.Column(db.String(32), nullable=False, unique=True, index=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    # NOT NULL DEFAULT '' in database/schema.sql: never insert NULL here
    groupname = db.Column(db.String(64), nullable=False, default='')
    realm = db.Column(db.String(64), default='')
    nasipaddress = db.Column(db.String(15), nullable=False, index=True)
    nasportid = db.Column(db.String(32))
    nasporttype = db.Column(db.String(32))
    acctstarttime = db.Column(db.DateTime, index=True)
    acctupdatetime = db.Column(db.DateTime)
    acctstoptime = db.Column(db.DateTime, index=True)
    acctinterval = db.Column(db.Integer)
    acctsessiontime = db.Column(db.Integer)
    acctauthentic = db.Column(db.String(32))
    connectinfo_start = db.Column(db.String(50))
    connectinfo_stop = db.Column(db.String(50))
    acctinputoctets = db.Column(db.BigInteger)
    acctoutputoctets = db.Column(db.BigInteger)
    calledstationid = db.Column(db.String(50), nullable=False, default='')
    callingstationid = db.Column(db.String(50), nullable=False, default='')
    acctterminatecause = db.Column(db.String(32), nullable=False, default='')
    servicetype = db.Column(db.String(32))
    framedprotocol = db.Column(db.String(32))
    framedipaddress = db.Column(db.String(15), nullable=False, default='', index=True)
    
    def __repr__(self):
        return f'<RadAcct {self.username} @ {self.nasipaddress}>'


class Nas(db.Model):
    """Network Access Servers (FreeRADIUS nas)"""
    __tablename__ = 'nas'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), index=True)
    nasname = db.Column(db.String(128), nullable=False, unique=True, index=True)
    shortname = db.Column(db.String(32), nullable=False)
    type = db.Column(db.String(30), nullable=False, default='other')
    ports = db.Column(db.Integer)
    secret = db.Column(db.String(60), nullable=False)
    server = db.Column(db.String(64))
    community = db.Column(db.String(50))
    description = db.Column(db.String(200))
    vendor = db.Column(db.String(32), default='standard')  # Vendor type
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Nas {self.shortname} ({self.vendor})>'


class RadUser(db.Model):
    """Extended user information (application-specific)"""
    __tablename__ = 'radusers'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), index=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'))
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    # Bandwidth limits (override plan limits if set)
    upload_speed = db.Column(db.String(32))  # e.g., "10M", "1G"
    download_speed = db.Column(db.String(32))  # e.g., "10M", "1G"
    data_cap = db.Column(db.BigInteger)  # Data cap in bytes (0 = unlimited)
    data_cap_period = db.Column(db.String(10), default='monthly')  # daily, weekly, monthly
    last_reset = db.Column(db.DateTime)  # Last time data cap was reset
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    plan = db.relationship('Plan', backref='plan_users')
    
    def __repr__(self):
        return f'<RadUser {self.username}>'


class RadPostAuth(db.Model):
    """Post-authentication logging (FreeRADIUS radpostauth)"""
    __tablename__ = 'radpostauth'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    pass_field = db.Column('pass', db.String(64), nullable=False)  # 'pass' is a MySQL keyword
    reply = db.Column(db.String(32), nullable=False)
    authdate = db.Column(db.DateTime, nullable=False, index=True, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<RadPostAuth {self.username} - {self.reply}>'




class Voucher(db.Model):
    """Prepaid access code: username and password are both `code`.

    Validity starts on the first successful login (set by FreeRADIUS
    post-auth); FreeRADIUS rejects the code once expires_at has passed.
    All timestamps are UTC.
    """
    __tablename__ = 'vouchers'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), index=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id', ondelete='SET NULL'))
    batch = db.Column(db.String(64), index=True)
    validity_minutes = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2))
    max_devices = db.Column(db.Integer, nullable=False, default=1, server_default='1')   # devices online at once
    is_free = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())  # marketing free trial
    first_mac = db.Column(db.String(17))    # device that first used it (one free trial per phone)
    status = db.Column(db.String(16), nullable=False, default='unused')  # unused, active, disabled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    first_used_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)

    plan = db.relationship('Plan', backref='vouchers')

    @property
    def state(self):
        """Status for display: unused, active, expired or disabled."""
        if self.status == 'disabled':
            return 'disabled'
        if self.expires_at and self.expires_at <= datetime.utcnow():
            return 'expired'
        return self.status

    @property
    def validity_label(self):
        return format_minutes(self.validity_minutes)

    @property
    def remaining_label(self):
        if not self.expires_at:
            return None
        seconds = (self.expires_at - datetime.utcnow()).total_seconds()
        return format_minutes(int(seconds // 60)) if seconds > 0 else None

    def __repr__(self):
        return f'<Voucher {self.code} ({self.state})>'



class Package(db.Model):
    """Internet package guests can buy on the captive portal.

    Speeds and other RADIUS attributes come from the linked plan; a paid
    purchase becomes a voucher for that plan, valid validity_minutes from
    first login.
    """
    __tablename__ = 'packages'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), index=True)
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(200))
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id', ondelete='SET NULL'))
    price = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='TZS')
    validity_minutes = db.Column(db.Integer, nullable=False)
    max_devices = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    is_active = db.Column(db.Boolean, default=True)
    show_on_portal = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plan = db.relationship('Plan', backref='packages')

    @property
    def validity_label(self):
        return format_minutes(self.validity_minutes)

    def __repr__(self):
        return f'<Package {self.name}>'


class Payment(db.Model):
    """Mobile-money purchase of a package (ClickPesa USSD push). UTC times."""
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), index=True)
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)  # ClickPesa orderReference
    package_id = db.Column(db.Integer, db.ForeignKey('packages.id', ondelete='SET NULL'))
    package_name = db.Column(db.String(64))
    # Copied from the package at purchase time
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id', ondelete='SET NULL'))
    validity_minutes = db.Column(db.Integer, nullable=False)
    max_devices = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    phone = db.Column(db.String(16), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='TZS')
    status = db.Column(db.String(16), nullable=False, default='pending', index=True)  # pending, paid, failed
    provider = db.Column(db.String(16), nullable=False, default='clickpesa')
    provider_id = db.Column(db.String(64))
    provider_status = db.Column(db.String(16))
    channel = db.Column(db.String(32))
    message = db.Column(db.String(255))
    nas_identifier = db.Column(db.String(64))
    client_mac = db.Column(db.String(17))
    client_ip = db.Column(db.String(45))
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id', ondelete='SET NULL'))
    provider_account = db.Column(db.String(16), nullable=False, default='platform')  # whose ClickPesa: platform/own
    fee_amount = db.Column(db.Numeric(10, 2), default=0)      # kept by the platform
    net_amount = db.Column(db.Numeric(10, 2))                 # owed to the tenant
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    checked_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)

    tenant = db.relationship('Tenant')
    package = db.relationship('Package')
    plan = db.relationship('Plan')
    voucher = db.relationship('Voucher')

    def __repr__(self):
        return f'<Payment {self.reference} {self.status}>'


def format_minutes(minutes):
    """90 -> '1h 30m', 2880 -> '2 days'."""
    if minutes >= 1440 and minutes % 1440 == 0:
        days = minutes // 1440
        return f'{days} day{"s" if days != 1 else ""}'
    hours, mins = divmod(minutes, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f'{days}d {hours}h'
    if hours and mins:
        return f'{hours}h {mins}m'
    if hours:
        return f'{hours} hour{"s" if hours != 1 else ""}'
    return f'{mins} min'



class Withdrawal(db.Model):
    """A tenant's request to be paid out its platform-collected balance."""
    __tablename__ = 'withdrawals'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    phone = db.Column(db.String(16), nullable=False)          # mobile money number to pay
    account_name = db.Column(db.String(100))
    status = db.Column(db.String(16), nullable=False, default='requested', index=True)  # requested, paid, rejected
    reference = db.Column(db.String(64))                      # payout transaction id
    note = db.Column(db.String(255))
    requested_by_id = db.Column(db.Integer, db.ForeignKey('admins.id', ondelete='SET NULL'))
    processed_by_id = db.Column(db.Integer, db.ForeignKey('admins.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)

    tenant = db.relationship('Tenant')
    requested_by = db.relationship('Admin', foreign_keys=[requested_by_id])
    processed_by = db.relationship('Admin', foreign_keys=[processed_by_id])

    def __repr__(self):
        return f'<Withdrawal {self.id} {self.status}>'


class VpnServer(db.Model):
    """The WireGuard hub's public details, published by the safenet-wireguard service."""
    __tablename__ = 'vpn_server'

    id = db.Column(db.Integer, primary_key=True)
    public_key = db.Column(db.String(64), nullable=False)
    listen_port = db.Column(db.Integer, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class Router(db.Model):
    """A tenant's router (MikroTik etc.) connected over the WireGuard VPN.

    Its tunnel address is unique, so FreeRADIUS can tell routers apart even when
    they share a public IP; the matching nas row carries the RADIUS secret.
    """
    __tablename__ = 'routers'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    vendor = db.Column(db.String(16), nullable=False, default='mikrotik')
    tunnel_ip = db.Column(db.String(15), unique=True, nullable=False)
    public_key = db.Column(db.String(64), unique=True, nullable=False)
    private_key_enc = db.Column(db.Text, nullable=False)       # secretbox; only used to build the setup script
    nas_id = db.Column(db.Integer, db.ForeignKey('nas.id', ondelete='SET NULL'))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_handshake_at = db.Column(db.DateTime)                  # updated by safenet-wireguard
    rx_bytes = db.Column(db.BigInteger, default=0)
    tx_bytes = db.Column(db.BigInteger, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant')
    nas = db.relationship('Nas')

    def __repr__(self):
        return f'<Router {self.name} {self.tunnel_ip}>'


class SessionKick(db.Model):
    """Admin asked to disconnect a user now; gateways pick it up on their next check."""
    __tablename__ = 'session_kicks'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    consumed_at = db.Column(db.DateTime)



class BillingPlan(db.Model):
    """What tenants pay the platform each month."""
    __tablename__ = 'billing_plans'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255))
    price = db.Column(db.Numeric(10, 2), nullable=False)       # per 30 days
    price_yearly = db.Column(db.Numeric(10, 2))                # 12 months at once; NULL = 12 x price
    currency = db.Column(db.String(3), nullable=False, default='TZS')
    max_routers = db.Column(db.Integer)                        # NULL = unlimited
    max_gateways = db.Column(db.Integer)                       # "sites"
    max_customers = db.Column(db.Integer)                      # subscriber accounts (vouchers are unlimited)
    max_staff = db.Column(db.Integer)                          # team accounts, owner included

    def amount_for(self, months):
        if months == 12 and self.price_yearly is not None:
            return self.price_yearly
        return self.price * months
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<BillingPlan {self.name}>'


class SubscriptionPayment(db.Model):
    """A tenant paying the platform for months of service (ClickPesa USSD push)."""
    __tablename__ = 'subscription_payments'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    billing_plan_id = db.Column(db.Integer, db.ForeignKey('billing_plans.id', ondelete='SET NULL'))
    plan_name = db.Column(db.String(64))
    months = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='TZS')
    phone = db.Column(db.String(16))
    method = db.Column(db.String(16), nullable=False, default='clickpesa')   # clickpesa, manual
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default='pending')     # pending, paid, failed, review
    provider_id = db.Column(db.String(64))
    provider_status = db.Column(db.String(16))
    channel = db.Column(db.String(32))
    message = db.Column(db.String(255))
    period_start = db.Column(db.DateTime)
    period_end = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('admins.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    checked_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)

    tenant = db.relationship('Tenant')
    billing_plan = db.relationship('BillingPlan')

    def __repr__(self):
        return f'<SubscriptionPayment {self.reference} {self.status}>'
