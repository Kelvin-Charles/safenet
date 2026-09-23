from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, BooleanField, IntegerField, DateTimeField
from wtforms.validators import DataRequired, Email, Length, Optional, IPAddress, ValidationError
from models import Admin, Plan, RadUser, Nas
import re


class LoginForm(FlaskForm):
    """Admin login form"""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    password = PasswordField('Password', validators=[DataRequired()])


class AdminForm(FlaskForm):
    """Admin user management form"""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[Optional(), Length(min=6)])
    is_active = BooleanField('Active')
    
    def validate_username(self, field):
        if not re.match(r'^[a-zA-Z0-9_-]+$', field.data):
            raise ValidationError('Username can only contain letters, numbers, hyphens, and underscores.')


class PlanForm(FlaskForm):
    """Plan/Group management form"""
    name = StringField('Plan Name', validators=[DataRequired(), Length(min=2, max=64)])
    description = TextAreaField('Description', validators=[Optional()])
    vendor = SelectField('Default Vendor', validators=[DataRequired()])
    is_active = BooleanField('Active', default=True)
    # Bandwidth limits
    upload_speed = StringField('Upload Speed', validators=[Optional()], 
                               description='e.g., 10M, 100M, 1G (leave empty for unlimited)')
    download_speed = StringField('Download Speed', validators=[Optional()],
                                  description='e.g., 10M, 100M, 1G (leave empty for unlimited)')
    data_cap = IntegerField('Data Cap (GB)', validators=[Optional()],
                           description='Data limit in GB (0 = unlimited)')
    data_cap_period = SelectField('Data Cap Period', choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly')
    ], default='monthly', validators=[Optional()],
    description='Reset period for data cap')
    
    def validate_name(self, field):
        if not re.match(r'^[a-zA-Z0-9_-]+$', field.data):
            raise ValidationError('Plan name can only contain letters, numbers, hyphens, and underscores.')


class PlanAttributeForm(FlaskForm):
    """Plan attribute form"""
    attribute = StringField('Attribute', validators=[DataRequired(), Length(max=64)])
    op = SelectField('Operator', choices=[
        (':=', ':= (Assign)'),
        ('==', '== (Equal)'),
        ('+=', '+= (Add)'),
        ('!=', '!= (Not Equal)'),
        ('>', '> (Greater Than)'),
        ('<', '< (Less Than)'),
        ('>=', '>= (Greater or Equal)'),
        ('<=', '<= (Less or Equal)'),
    ], validators=[DataRequired()])
    value = StringField('Value', validators=[DataRequired(), Length(max=253)])
    vendor = SelectField('Vendor', validators=[Optional()])
    priority = IntegerField('Priority', default=0, validators=[Optional()])


class UserForm(FlaskForm):
    """RADIUS user management form"""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    password = StringField('Password', validators=[DataRequired(), Length(min=4)])
    plan_id = SelectField('Plan', coerce=int, validators=[Optional()])
    is_active = BooleanField('Active', default=True)
    expires_at = DateTimeField('Expires At', format='%Y-%m-%d %H:%M:%S', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    # Bandwidth limits (override plan limits if set)
    upload_speed = StringField('Upload Speed', validators=[Optional()],
                               description='Override plan: e.g., 10M, 100M, 1G (leave empty to use plan default)')
    download_speed = StringField('Download Speed', validators=[Optional()],
                                  description='Override plan: e.g., 10M, 100M, 1G (leave empty to use plan default)')
    data_cap = IntegerField('Data Cap (GB)', validators=[Optional()],
                           description='Override plan: Data limit in GB (0 = unlimited, leave empty to use plan default)')
    data_cap_period = SelectField('Data Cap Period', choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly')
    ], default='monthly', validators=[Optional()],
    description='Reset period for data cap (overrides plan default)')
    
    def validate_username(self, field):
        if not re.match(r'^[a-zA-Z0-9_.-]+$', field.data):
            raise ValidationError('Username can only contain letters, numbers, dots, hyphens, and underscores.')


class NasForm(FlaskForm):
    """NAS device management form"""
    nasname = StringField('IP Address', validators=[DataRequired(), IPAddress()])
    shortname = StringField('Short Name', validators=[DataRequired(), Length(min=2, max=32)])
    type = SelectField('Type', choices=[
        ('other', 'Other'),
        ('cisco', 'Cisco'),
        ('computone', 'Computone'),
        ('livingston', 'Livingston'),
        ('juniper', 'Juniper'),
        ('max40xx', 'Max40xx'),
        ('multitech', 'Multitech'),
        ('netserver', 'Netserver'),
        ('pathras', 'Pathras'),
        ('patton', 'Patton'),
        ('portslave', 'Portslave'),
        ('tc', 'TC'),
        ('usrhiper', 'USR Hiper'),
    ], validators=[DataRequired()])
    secret = StringField('RADIUS Secret', validators=[DataRequired(), Length(min=6, max=60)])
    vendor = SelectField('Vendor', validators=[DataRequired()])
    ports = IntegerField('Ports', validators=[Optional()])
    server = StringField('Server', validators=[Optional(), Length(max=64)])
    community = StringField('SNMP Community', validators=[Optional(), Length(max=50)])
    description = StringField('Description', validators=[Optional(), Length(max=200)])
    is_active = BooleanField('Active', default=True)
    
    def validate_shortname(self, field):
        if not re.match(r'^[a-zA-Z0-9_-]+$', field.data):
            raise ValidationError('Short name can only contain letters, numbers, hyphens, and underscores.')


class SearchForm(FlaskForm):
    """Generic search form"""
    query = StringField('Search', validators=[Optional(), Length(max=100)])




class VoucherGenerateForm(FlaskForm):
    """Generate a batch of prepaid vouchers"""
    plan_id = SelectField('Plan', coerce=int, validators=[Optional()])
    count = IntegerField('How many', default=10, validators=[DataRequired()])
    validity_value = IntegerField('Valid for', default=1, validators=[DataRequired()])
    validity_unit = SelectField('Unit', choices=[
        ('hours', 'Hours'),
        ('days', 'Days'),
    ], default='days', validators=[DataRequired()])
    price = StringField('Price', validators=[Optional(), Length(max=12)],
                        description='Printed on the voucher, e.g. 1000')
    batch = StringField('Batch name', validators=[Optional(), Length(max=64)],
                        description='Leave empty to name it by date/time')

    def validate_count(self, field):
        if not 1 <= (field.data or 0) <= 500:
            raise ValidationError('Generate between 1 and 500 vouchers at a time.')

    def validate_validity_value(self, field):
        if not 1 <= (field.data or 0) <= 365:
            raise ValidationError('Enter a value between 1 and 365.')

    def validate_price(self, field):
        if field.data and not re.match(r'^\d+(\.\d{1,2})?$', field.data.strip()):
            raise ValidationError('Price must be a number, e.g. 1000 or 1500.50')


class PackageForm(FlaskForm):
    """Internet package sold on the captive portal"""
    name = StringField('Package name', validators=[DataRequired(), Length(max=64)],
                       description='Shown to guests, e.g. "1 Hour - 500"')
    description = StringField('Short description', validators=[Optional(), Length(max=200)])
    plan_id = SelectField('Speed plan', coerce=int, validators=[Optional()])
    price = StringField('Price (TZS)', validators=[DataRequired(), Length(max=12)])
    validity_value = IntegerField('Access duration', default=1, validators=[DataRequired()])
    validity_unit = SelectField('Unit', choices=[
        ('minutes', 'Minutes'),
        ('hours', 'Hours'),
        ('days', 'Days'),
    ], default='hours', validators=[DataRequired()])
    sort_order = IntegerField('Display order', default=0, validators=[Optional()],
                              description='Lower numbers are shown first')
    is_active = BooleanField('Active', default=True)
    show_on_portal = BooleanField('Show on captive portal', default=True)

    def validate_price(self, field):
        value = (field.data or '').strip()
        if not re.match(r'^\d+(\.\d{1,2})?$', value) or float(value) < 100:
            raise ValidationError('Enter a price of at least 100, e.g. 500 or 1000.')

    def validate_validity_value(self, field):
        if not 1 <= (field.data or 0) <= 100000:
            raise ValidationError('Enter a positive duration.')


class SignupForm(FlaskForm):
    """Self-service signup: creates a tenant and its owner"""
    business_name = StringField('Business name', validators=[DataRequired(), Length(min=2, max=100)])
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField('Confirm password', validators=[DataRequired()])
    accept = BooleanField('I accept the terms of service', validators=[DataRequired()])

    def validate_username(self, field):
        if not re.match(r'^[a-zA-Z0-9_.-]+$', field.data):
            raise ValidationError('Use letters, numbers, dots, hyphens and underscores only.')

    def validate_confirm(self, field):
        if field.data != self.password.data:
            raise ValidationError('Passwords do not match.')


class EmailForm(FlaskForm):
    """Resend verification / forgot password"""
    email = StringField('Email', validators=[DataRequired(), Email()])


class ResetPasswordForm(FlaskForm):
    password = PasswordField('New password', validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField('Confirm password', validators=[DataRequired()])

    def validate_confirm(self, field):
        if field.data != self.password.data:
            raise ValidationError('Passwords do not match.')


class TenantSettingsForm(FlaskForm):
    name = StringField('Business name', validators=[DataRequired(), Length(max=100)])
    phone = StringField('Business phone', validators=[Optional(), Length(max=20)])
    hotspot_name = StringField('Wi-Fi name shown to guests', validators=[Optional(), Length(max=64)],
                               description='On the splash page and printed vouchers. Defaults to the business name.')
    support_phone = StringField('Support phone / WhatsApp', validators=[Optional(), Length(max=32)])
    currency = StringField('Currency', validators=[DataRequired(), Length(min=3, max=3)])
    terms = TextAreaField('Terms of use for guests', validators=[Optional(), Length(max=4000)])


class TeamMemberForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    role = SelectField('Role', choices=[('staff', 'Staff: users, vouchers, live'),
                                        ('admin', 'Admin: everything except team owners')])
    password = PasswordField('Temporary password', validators=[DataRequired(), Length(min=8, max=128)])

    def validate_username(self, field):
        if not re.match(r'^[a-zA-Z0-9_.-]+$', field.data):
            raise ValidationError('Use letters, numbers, dots, hyphens and underscores only.')


class GatewayForm(FlaskForm):
    name = StringField('Gateway name', validators=[DataRequired(), Length(max=64)],
                       description='e.g. "Main branch - dev server"')
