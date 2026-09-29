from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, PasswordField, TextAreaField, SelectField, BooleanField, IntegerField, DateTimeField
from wtforms.validators import DataRequired, Email, Length, Optional, IPAddress, ValidationError
from models import Admin, Plan, RadUser, Nas
import re


_SPEED_RE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*(k|kb|kbit|kbps|kb/s|m|mb|mbit|mbps|mb/s|g|gb|gbit|gbps|gb/s)?\s*$', re.I)


def normalize_speed(text):
    """'5', '5M', '5 Mbps', '5Mb/s', '512k', '1.5 Mbps' -> '5M', '512k', '1500k'. '' -> ''. None if unreadable.
    One format (bits per second, k/M/G) that the gateway, MikroTik and Omada all understand."""
    text = (text or '').strip()
    if not text:
        return ''
    m = _SPEED_RE.match(text)
    if not m:
        return None
    value = float(m.group(1).replace(',', '.'))
    unit = (m.group(2) or 'm')[0].lower()
    kbps = value * {'k': 1, 'm': 1000, 'g': 1000000}[unit]
    if kbps < 8:
        return None
    if kbps % 1000000 == 0:
        return f'{int(kbps // 1000000)}G'
    if kbps % 1000 == 0:
        return f'{int(kbps // 1000)}M'
    return f'{int(round(kbps))}k'


class SpeedField(StringField):
    """Speed limit in bits per second, saved as e.g. 5M; empty means no limit."""
    def process_formdata(self, valuelist):
        super().process_formdata(valuelist)
        self.raw_speed = self.data
        normal = normalize_speed(self.data)
        self.data = normal if normal is not None else self.data

    def pre_validate(self, form):
        if normalize_speed(getattr(self, 'raw_speed', self.data)) is None:
            raise ValidationError('Write the speed like 5M (5 Mb/s), 20M or 512k (512 kb/s).')


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
    upload_speed = SpeedField('Upload Speed', validators=[Optional()],
                              description='e.g. 2M, 5M, 512k (Mb/s or kb/s). Leave empty for no limit.')
    download_speed = SpeedField('Download Speed', validators=[Optional()],
                                description='e.g. 5M, 20M (Mb/s). Leave empty for no limit.')
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
    upload_speed = SpeedField('Upload Speed', validators=[Optional()],
                              description='Override the plan, e.g. 5M or 512k (leave empty to use the plan)')
    download_speed = SpeedField('Download Speed', validators=[Optional()],
                                description='Override the plan, e.g. 20M (leave empty to use the plan)')
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
    max_devices = IntegerField('Devices per voucher', default=1, validators=[DataRequired()],
                               description='How many devices can use one code at the same time')
    is_free = BooleanField('Free trial (marketing)',
                           description='Given away to let people try the Wi-Fi: no price, not counted as sales, '
                                       'and each phone can use only one free trial.')

    def validate_max_devices(self, field):
        if not 1 <= (field.data or 0) <= 10:
            raise ValidationError('Choose between 1 and 10 devices.')

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
    max_devices = IntegerField('Devices allowed', default=1, validators=[DataRequired()],
                               description='How many devices can use one purchase at the same time')
    is_active = BooleanField('Active', default=True)
    show_on_portal = BooleanField('Show on captive portal', default=True)

    def validate_price(self, field):
        value = (field.data or '').strip()
        if not re.match(r'^\d+(\.\d{1,2})?$', value) or float(value) < 100:
            raise ValidationError('Enter a price of at least 100, e.g. 500 or 1000.')

    def validate_validity_value(self, field):
        if not 1 <= (field.data or 0) <= 100000:
            raise ValidationError('Enter a positive duration.')

    def validate_max_devices(self, field):
        if not 1 <= (field.data or 0) <= 10:
            raise ValidationError('Choose between 1 and 10 devices.')


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
    block_tethering = BooleanField('Block hotspot sharing',
                                   description="Guests can't share their internet with other devices through their phone or laptop hotspot.")


class TeamMemberForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    role = SelectField('Role', choices=[('viewer', 'Partner / shareholder: view only (finance and usage)'),
                                        ('staff', 'Staff: users, vouchers, live'),
                                        ('admin', 'Admin: everything except team owners')], default='staff')
    site_id = SelectField('Can see', coerce=int, default=0,
                          description='For partners: the whole business, or only one site.')
    password = PasswordField('Temporary password', validators=[DataRequired(), Length(min=8, max=128)])

    def validate_username(self, field):
        if not re.match(r'^[a-zA-Z0-9_.-]+$', field.data):
            raise ValidationError('Use letters, numbers, dots, hyphens and underscores only.')


class GatewayForm(FlaskForm):
    name = StringField('Gateway name', validators=[DataRequired(), Length(max=64)],
                       description='e.g. "Main branch - dev server"')


class PaymentSettingsForm(FlaskForm):
    payment_mode = SelectField('Who receives package payments?', choices=[
        ('platform', 'SafeNet Pay collects for me, I withdraw my balance'),
        ('own', 'Straight into my own ClickPesa or Snippe account'),
    ])
    own_provider = SelectField('My payment account', choices=[('clickpesa', 'ClickPesa'), ('snippe', 'Snippe')])
    snippe_api_key = PasswordField('Snippe API key', validators=[Optional(), Length(max=200)],
                                   description='Starts with snp_. Leave empty to keep the saved key.')
    snippe_webhook_key = PasswordField('Snippe webhook signing key', validators=[Optional(), Length(max=200)],
                                       description='Snippe dashboard: Settings -> Webhook Secret. Leave empty to keep the saved key.')
    client_id = StringField('ClickPesa Client ID', validators=[Optional(), Length(max=64)])
    api_key = PasswordField('ClickPesa API key', validators=[Optional(), Length(max=200)],
                            description='Leave empty to keep the saved key.')
    checksum_key = PasswordField('Checksum key (only if enabled in ClickPesa)', validators=[Optional(), Length(max=200)],
                                 description='Leave empty to keep the saved key.')
    clear_checksum = BooleanField('Remove the saved checksum key')


class WithdrawalForm(FlaskForm):
    amount = IntegerField('Amount', validators=[DataRequired()])
    phone = StringField('Mobile money number', validators=[DataRequired(), Length(max=20)])
    account_name = StringField('Account name', validators=[Optional(), Length(max=100)],
                               description='Name registered on the mobile money number')



class PortalSettingsForm(FlaskForm):
    """How the captive portal looks to guests"""
    color = StringField('Brand colour', validators=[DataRequired()])
    style = SelectField('Header style', choices=[('gradient', 'Gradient'), ('solid', 'Solid colour'), ('light', 'Light (white)')])
    title = StringField('Welcome title', validators=[Optional(), Length(max=80)],
                        description='Leave empty for "Welcome to <your Wi-Fi name>".')
    message = TextAreaField('Welcome message', validators=[Optional(), Length(max=300)],
                            description='One or two short sentences under the title.')
    language = SelectField('Default language', choices=[('en', 'English'), ('sw', 'Kiswahili')])
    show_voucher = BooleanField('Voucher login')
    show_packages = BooleanField('Buy packages with mobile money')
    logo = FileField('Logo (PNG, JPG or WebP, up to 300 KB)')
    remove_logo = BooleanField('Remove the current logo')

    def validate_color(self, field):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', field.data or ''):
            raise ValidationError('Use a colour like #051D60.')

    def validate_show_packages(self, field):
        if not field.data and not self.show_voucher.data:
            raise ValidationError('Keep at least one way to get online.')
