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


