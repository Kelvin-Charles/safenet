from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import bcrypt

db = SQLAlchemy()


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
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False, index=True)
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
    
    radacctid = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    acctsessionid = db.Column(db.String(64), nullable=False, index=True)
    acctuniqueid = db.Column(db.String(32), nullable=False, unique=True, index=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    groupname = db.Column(db.String(64))
    realm = db.Column(db.String(64))
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
    calledstationid = db.Column(db.String(50))
    callingstationid = db.Column(db.String(50))
    acctterminatecause = db.Column(db.String(32))
    servicetype = db.Column(db.String(32))
    framedprotocol = db.Column(db.String(32))
    framedipaddress = db.Column(db.String(15), index=True)
    
    def __repr__(self):
        return f'<RadAcct {self.username} @ {self.nasipaddress}>'


class Nas(db.Model):
    """Network Access Servers (FreeRADIUS nas)"""
    __tablename__ = 'nas'
    
    id = db.Column(db.Integer, primary_key=True)
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


