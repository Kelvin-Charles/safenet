from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, abort, session, g, has_request_context, make_response, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
from config import Config
from models import db, BillingPlan, SubscriptionPayment, SessionKick, Withdrawal, VpnServer, Router, Admin, Plan, PlanAttribute, RadUser, RadCheck, RadReply, RadUserGroup, RadGroupCheck, RadGroupReply, RadAcct, Nas, RadPostAuth, Voucher, Package, Payment, Tenant, Gateway
from forms import LoginForm, AdminForm, PlanForm, PlanAttributeForm, UserForm, NasForm, SearchForm, VoucherGenerateForm, PackageForm, SignupForm, EmailForm, ResetPasswordForm, TenantSettingsForm, TeamMemberForm, GatewayForm, PaymentSettingsForm, WithdrawalForm, PortalSettingsForm
from flask_wtf.csrf import generate_csrf, validate_csrf
from wtforms.validators import ValidationError
from sqlalchemy import func, or_, desc, text
import clickpesa
from gateway import portal_ui
from sms import send_sms_async
from models import format_minutes
import radclient
import threading
import math
import os
import secretbox
import migrations
from mailer import send_mail
from tenancy import current_tenant, tenant_id, scoped, owned_or_404, tenant_usernames, role_required, superadmin_required
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import hashlib
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
import subprocess
import secrets
import hmac
import logging
import re
from functools import wraps
from datetime import timedelta
import ipaddress
from decimal import Decimal
from urllib.parse import urlparse
import socket
import time
import struct
import json
import sys
import click

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'


@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))


# Context processor for global template variables
@app.context_processor
def inject_globals():
    tenant = current_tenant() if current_user.is_authenticated else None
    return {
        'app_name': 'SafeNet',
        'supported_vendors': Config.SUPPORTED_VENDORS,
        'csrf_token': generate_csrf,
        'tenant': tenant,
        'viewing_other_tenant': bool(tenant and current_user.is_authenticated and tenant.id != current_user.tenant_id),
        'signup_enabled': Config.SIGNUP_ENABLED,
        'billing': billing_state(tenant) if tenant else None,
    }


BILLING_ENDPOINTS = {'billing', 'billing_pay', 'billing_payment', 'billing_payment_status', 'logout', 'static'}


@app.before_request
def block_suspended_tenants():
    if current_user.is_authenticated and not current_user.is_superadmin:
        tenant = current_user.tenant
        if tenant is None or tenant.status == 'suspended' or not current_user.is_active:
            logout_user()
            flash('This account is suspended. Please contact support.', 'danger')
            return redirect(url_for('login'))
        if tenant_blocked(tenant) and request.endpoint not in BILLING_ENDPOINTS:
            flash('Your SafeNet subscription has expired and your Wi-Fi is paused. Renew to continue.', 'danger')
            return redirect(url_for('billing'))


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500


# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        admin = Admin.query.filter_by(username=form.username.data).first()
        if admin and admin.check_password(form.password.data):
            if not admin.is_active:
                flash('Your account has been disabled.', 'danger')
                return redirect(url_for('login'))
            if not admin.email_verified_at:
                return render_template('auth/verify_notice.html', email=admin.email, form=EmailForm(email=admin.email))
            if not admin.is_superadmin and admin.tenant and admin.tenant.status == 'suspended':
                flash('This account is suspended. Please contact support.', 'danger')
                return redirect(url_for('login'))
            
            admin.last_login = datetime.utcnow()
            db.session.commit()
            login_user(admin)
            
            next_page = request.args.get('next', '')
            if not next_page.startswith('/') or next_page.startswith('//'):
                next_page = url_for('dashboard')
            return redirect(next_page)
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('auth/login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    session.pop('tenant_id', None)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# Dashboard
@app.route('/')
def landing():
    """Public home page of the SafeNet platform (pricing from Platform: Billing)."""
    plans = BillingPlan.query.filter_by(is_active=True).order_by(BillingPlan.sort_order, BillingPlan.price).all()
    home = Tenant.query.filter_by(slug=migrations.DEFAULT_TENANT_SLUG).first()
    return render_template('landing.html', plans=plans, trial_days=Config.TRIAL_DAYS,
                           networks=[n['name'] for n in payment_networks()],
                           support_phone=(home.support_phone if home else None) or Config.HOTSPOT_SUPPORT,
                           contact_email=Config.MAIL_USERNAME or Config.ADMIN_EMAIL,
                           signup_enabled=Config.SIGNUP_ENABLED, year=datetime.utcnow().year)


@app.route('/dashboard')
@login_required
def dashboard():
    # Statistics
    total_users = scoped(RadUser).count()
    active_users = scoped(RadUser).filter_by(is_active=True).count()
    total_plans = scoped(Plan).count()
    total_nas = scoped(Nas).count()
    mine = RadAcct.username.in_(tenant_usernames())
    
    # Active sessions
    active_sessions = RadAcct.query.filter(mine, RadAcct.acctstoptime.is_(None)).count()
    
    # Recent sessions
    recent_sessions = RadAcct.query.filter(mine).order_by(desc(RadAcct.acctstarttime)).limit(10).all()
    
    # Top users by data usage. COALESCE protects against rows where octet
    # counters are NULL (no accounting yet) so the template never divides by None.
    total_bytes_expr = func.coalesce(
        func.sum(
            func.coalesce(RadAcct.acctinputoctets, 0)
            + func.coalesce(RadAcct.acctoutputoctets, 0)
        ),
        0,
    ).label('total_bytes')
    top_users = (
        db.session.query(RadAcct.username, total_bytes_expr)
        .filter(mine)
        .group_by(RadAcct.username)
        .order_by(desc('total_bytes'))
        .limit(5)
        .all()
    )
    
    return render_template('dashboard.html',
                         total_users=total_users,
                         active_users=active_users,
                         total_plans=total_plans,
                         total_nas=total_nas,
                         active_sessions=active_sessions,
                         recent_sessions=recent_sessions,
                         top_users=top_users)


# User management routes
@app.route('/users')
@login_required
def users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    
    query = scoped(RadUser)
    if search:
        query = query.filter(RadUser.username.like(f'%{search}%'))
    
    pagination = query.order_by(RadUser.created_at.desc()).paginate(
        page=page, per_page=Config.ITEMS_PER_PAGE, error_out=False
    )
    
    return render_template('users/list.html', pagination=pagination, search=search)


@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    form = UserForm()
    form.plan_id.choices = [(0, '-- No Plan --')] + [(p.id, p.name) for p in scoped(Plan).filter_by(is_active=True).all()]
    
    if form.validate_on_submit():
        # Usernames are global in RADIUS: check every tenant's users and vouchers
        if _radius_username_taken(form.username.data):
            flash('That username is already taken. Choose another.', 'danger')
            return render_template('users/form.html', form=form, title='Add User')
        
        # Create RadUser
        user = RadUser(
            tenant_id=tenant_id(),
            username=form.username.data,
            plan_id=form.plan_id.data if form.plan_id.data > 0 else None,
            is_active=form.is_active.data,
            expires_at=form.expires_at.data,
            notes=form.notes.data,
            upload_speed=form.upload_speed.data if form.upload_speed.data else None,
            download_speed=form.download_speed.data if form.download_speed.data else None,
            data_cap=form.data_cap.data * 1073741824 if form.data_cap.data else None,  # Convert GB to bytes
            data_cap_period=form.data_cap_period.data if form.data_cap_period.data else None,
            last_reset=datetime.utcnow() if form.data_cap.data else None
        )
        db.session.add(user)
        
        # Create RadCheck entry for password
        radcheck = RadCheck(
            username=form.username.data,
            attribute='Cleartext-Password',
            op=':=',
            value=form.password.data
        )
        db.session.add(radcheck)
        
        # If plan is selected, create group mapping and apply attributes
        if form.plan_id.data and form.plan_id.data > 0:
            plan = scoped(Plan).filter_by(id=form.plan_id.data).first()
            if plan:
                # Create user-group mapping
                usergroup = RadUserGroup(
                    username=form.username.data,
                    groupname=plan.group_name,
                    priority=1
                )
                db.session.add(usergroup)
        
        db.session.commit()
        flash(f'User {form.username.data} created successfully.', 'success')
        return redirect(url_for('users'))
    
    # Get NAS list for testing (empty for new users - they need to be saved first)
    nas_list = scoped(Nas).filter_by(is_active=True).all()
    return render_template('users/form.html', form=form, nas_list=nas_list, title='Add User')


@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user = owned_or_404(RadUser, user_id)
    form = UserForm(obj=user)
    form.plan_id.choices = [(0, '-- No Plan --')] + [(p.id, p.name) for p in scoped(Plan).filter_by(is_active=True).all()]
    
    # Convert data_cap from bytes to GB for display
    if user.data_cap:
        form.data_cap.data = int(user.data_cap / 1073741824)
    if user.data_cap_period:
        form.data_cap_period.data = user.data_cap_period
    
    # Get NAS list for testing
    nas_list = scoped(Nas).filter_by(is_active=True).all()
    
    if form.validate_on_submit():
        # Update RadUser
        user.plan_id = form.plan_id.data if form.plan_id.data > 0 else None
        if user.is_active and not form.is_active.data:
            disconnect_subscriber(user.tenant_id, user.username)
        user.is_active = form.is_active.data
        user.expires_at = form.expires_at.data
        user.notes = form.notes.data
        # Bandwidth limits
        user.upload_speed = form.upload_speed.data if form.upload_speed.data else None
        user.download_speed = form.download_speed.data if form.download_speed.data else None
        if form.data_cap.data:
            user.data_cap = form.data_cap.data * 1073741824  # Convert GB to bytes
            user.data_cap_period = form.data_cap_period.data if form.data_cap_period.data else 'monthly'
            # Set last_reset if not already set
            if not user.last_reset:
                user.last_reset = datetime.utcnow()
        else:
            user.data_cap = None
            user.data_cap_period = None
        
        # Update password if provided
        if form.password.data:
            radcheck = RadCheck.query.filter_by(username=user.username, attribute='Cleartext-Password').first()
            if radcheck:
                radcheck.value = form.password.data
            else:
                radcheck = RadCheck(
                    username=user.username,
                    attribute='Cleartext-Password',
                    op=':=',
                    value=form.password.data
                )
                db.session.add(radcheck)
        
        # Update group mapping
        RadUserGroup.query.filter_by(username=user.username).delete()
        if form.plan_id.data and form.plan_id.data > 0:
            plan = scoped(Plan).filter_by(id=form.plan_id.data).first()
            if plan:
                usergroup = RadUserGroup(
                    username=user.username,
                    groupname=plan.group_name,
                    priority=1
                )
                db.session.add(usergroup)
        
        db.session.commit()
        flash(f'User {user.username} updated successfully.', 'success')
        return redirect(url_for('users'))
    
    return render_template('users/form.html', form=form, user=user, nas_list=nas_list, title='Edit User')


@app.route('/users/test-connection/<int:user_id>', methods=['POST'])
@login_required
def test_user_connection(user_id):
    """Test user RADIUS authentication against a NAS device"""
    user = owned_or_404(RadUser, user_id)
    nas_id = request.json.get('nas_id') if request.is_json else request.form.get('nas_id', type=int)
    
    if not nas_id:
        if request.is_json:
            return jsonify({
                'success': False,
                'message': 'Please select a NAS device to test against'
            }), 400
        flash('Please select a NAS device to test against.', 'danger')
        return redirect(url_for('edit_user', user_id=user_id))
    
    nas = owned_or_404(Nas, nas_id)
    
    # Get user password from radcheck
    radcheck = RadCheck.query.filter_by(
        username=user.username,
        attribute='Cleartext-Password'
    ).first()
    
    if not radcheck:
        if request.is_json:
            return jsonify({
                'success': False,
                'message': f'User {user.username} does not have a password set'
            }), 400
        flash(f'User {user.username} does not have a password set.', 'danger')
        return redirect(url_for('edit_user', user_id=user_id))
    
    password = radcheck.value
    
    try:
        # Test RADIUS authentication using radtest from FreeRADIUS container
        result = subprocess.run(
            ['docker', 'exec', 'safenet-radius', 'radtest', user.username, password, nas.nasname, '0', nas.secret],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if 'Access-Accept' in result.stdout:
            # If test successful, activate user if not already active
            was_inactive = not user.is_active
            if was_inactive:
                user.is_active = True
                db.session.commit()
            
            message = f'Authentication successful! User {user.username} can connect to {nas.shortname} ({nas.nasname})'
            if was_inactive:
                message += '. User has been activated.'
            
            if request.is_json:
                return jsonify({
                    'success': True,
                    'message': message,
                    'activated': was_inactive
                })
            flash(message, 'success')
            return redirect(url_for('edit_user', user_id=user_id))
        else:
            error_msg = 'Authentication failed'
            if 'Access-Reject' in result.stdout:
                error_msg += ': Invalid credentials or user not found'
            elif result.stderr:
                error_msg += f': {result.stderr[:100]}'
            
            if request.is_json:
                return jsonify({
                    'success': False,
                    'message': error_msg,
                    'details': result.stdout[:200] if result.stdout else ''
                }), 400
            flash(error_msg, 'danger')
            return redirect(url_for('edit_user', user_id=user_id))
            
    except subprocess.TimeoutExpired:
        error_msg = f'Connection test timed out. NAS {nas.shortname} may be unreachable.'
        if request.is_json:
            return jsonify({
                'success': False,
                'message': error_msg
            }), 500
        flash(error_msg, 'danger')
        return redirect(url_for('edit_user', user_id=user_id))
    except FileNotFoundError:
        error_msg = 'RADIUS test tool not available. Please test manually.'
        if request.is_json:
            return jsonify({
                'success': False,
                'message': error_msg,
                'manual_test': f'docker exec safenet-radius radtest {user.username} <password> {nas.nasname} 0 {nas.secret}'
            }), 500
        flash(error_msg, 'warning')
        return redirect(url_for('edit_user', user_id=user_id))
    except Exception as e:
        error_msg = f'Test failed: {str(e)}'
        if request.is_json:
            return jsonify({
                'success': False,
                'message': error_msg
            }), 500
        flash(error_msg, 'danger')
        return redirect(url_for('edit_user', user_id=user_id))


@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    user = owned_or_404(RadUser, user_id)
    username = user.username
    disconnect_subscriber(user.tenant_id, username)
    
    # Delete all related records
    RadCheck.query.filter_by(username=username).delete()
    RadReply.query.filter_by(username=username).delete()
    RadUserGroup.query.filter_by(username=username).delete()
    db.session.delete(user)
    
    db.session.commit()
    flash(f'User {username} deleted successfully.', 'success')
    return redirect(url_for('users'))


# Plan management routes
@app.route('/plans')
@login_required
@role_required('admin')
def plans():
    all_plans = scoped(Plan).order_by(Plan.created_at.desc()).all()
    return render_template('plans/list.html', plans=all_plans)


@app.route('/plans/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_plan():
    form = PlanForm()
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    if form.validate_on_submit():
        if scoped(Plan).filter_by(name=form.name.data).first():
            flash('Plan name already exists.', 'danger')
            return render_template('plans/form.html', form=form, title='Add Plan')
        
        plan = Plan(
            tenant_id=tenant_id(),
            group_name=_new_group_name(form.name.data),
            name=form.name.data,
            description=form.description.data,
            vendor=form.vendor.data,
            is_active=form.is_active.data,
            upload_speed=form.upload_speed.data if form.upload_speed.data else None,
            download_speed=form.download_speed.data if form.download_speed.data else None,
            data_cap=form.data_cap.data * 1073741824 if form.data_cap.data else None,  # Convert GB to bytes
            data_cap_period=form.data_cap_period.data if form.data_cap_period.data else 'monthly',
            last_reset=datetime.utcnow() if form.data_cap.data else None
        )
        db.session.add(plan)
        db.session.flush()
        _sync_plan_rate_limit(plan)
        db.session.commit()
        
        flash(f'Plan {form.name.data} created successfully.', 'success')
        return redirect(url_for('edit_plan', plan_id=plan.id))
    
    return render_template('plans/form.html', form=form, title='Add Plan')


@app.route('/plans/edit/<int:plan_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_plan(plan_id):
    plan = owned_or_404(Plan, plan_id)
    form = PlanForm(obj=plan)
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    # Convert data_cap from bytes to GB for display
    if plan.data_cap:
        form.data_cap.data = int(plan.data_cap / 1073741824)
    if plan.data_cap_period:
        form.data_cap_period.data = plan.data_cap_period
    
    if form.validate_on_submit():
        clash = scoped(Plan).filter(Plan.name == form.name.data, Plan.id != plan.id).first()
        if clash:
            flash('Plan name already exists.', 'danger')
            return redirect(url_for('edit_plan', plan_id=plan.id))
        plan.name = form.name.data   # group_name stays fixed, so users keep their plan
        plan.description = form.description.data
        plan.vendor = form.vendor.data
        plan.is_active = form.is_active.data
        plan.upload_speed = form.upload_speed.data if form.upload_speed.data else None
        plan.download_speed = form.download_speed.data if form.download_speed.data else None
        if form.data_cap.data:
            plan.data_cap = form.data_cap.data * 1073741824  # Convert GB to bytes
            plan.data_cap_period = form.data_cap_period.data if form.data_cap_period.data else 'monthly'
            # Set last_reset if not already set
            if not plan.last_reset:
                plan.last_reset = datetime.utcnow()
        else:
            plan.data_cap = None
            plan.data_cap_period = None
        
        _sync_plan_rate_limit(plan)
        db.session.commit()
        flash(f'Plan {plan.name} updated successfully.', 'success')
        return redirect(url_for('plans'))
    
    # Get attributes
    attributes = PlanAttribute.query.filter_by(plan_id=plan.id).order_by(PlanAttribute.priority).all()
    
    return render_template('plans/edit.html', form=form, plan=plan, attributes=attributes, title='Edit Plan')


@app.route('/plans/<int:plan_id>/attributes/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_plan_attribute(plan_id):
    plan = owned_or_404(Plan, plan_id)
    form = PlanAttributeForm()
    form.vendor.choices = [('', '-- Standard --')] + Config.SUPPORTED_VENDORS
    
    if form.validate_on_submit():
        attribute = PlanAttribute(
            plan_id=plan.id,
            attribute=form.attribute.data,
            op=form.op.data,
            value=form.value.data,
            vendor=form.vendor.data if form.vendor.data else None,
            priority=form.priority.data
        )
        db.session.add(attribute)
        
        # Also add to radgroupreply
        groupreply = RadGroupReply(
            groupname=plan.group_name,
            attribute=form.attribute.data,
            op=form.op.data,
            value=form.value.data,
            priority=form.priority.data
        )
        db.session.add(groupreply)
        
        db.session.commit()
        flash('Attribute added successfully.', 'success')
        return redirect(url_for('edit_plan', plan_id=plan.id))
    
    return render_template('plans/attribute_form.html', form=form, plan=plan, title='Add Attribute')


@app.route('/plans/reset-data-cap/<int:plan_id>', methods=['POST'])
@login_required
@role_required('admin')
def reset_plan_data_cap(plan_id):
    """Reset data cap counter for all users in a plan"""
    plan = owned_or_404(Plan, plan_id)
    plan.last_reset = datetime.utcnow()
    
    # Reset all users in this plan
    users = scoped(RadUser).filter_by(plan_id=plan_id).all()
    for user in users:
        if user.data_cap_period == plan.data_cap_period or not user.data_cap_period:
            user.last_reset = datetime.utcnow()
    
    db.session.commit()
    flash(f'Data cap reset for plan {plan.name} and all users in this plan. Counter will reset based on {plan.data_cap_period or "monthly"} period.', 'success')
    return redirect(url_for('edit_plan', plan_id=plan_id))


@app.route('/plans/<int:plan_id>/attributes/<int:attr_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_plan_attribute(plan_id, attr_id):
    plan = owned_or_404(Plan, plan_id)
    attribute = PlanAttribute.query.filter_by(id=attr_id, plan_id=plan.id).first_or_404()
    
    # Also delete from radgroupreply
    RadGroupReply.query.filter_by(
        groupname=plan.group_name,
        attribute=attribute.attribute
    ).delete()
    
    db.session.delete(attribute)
    db.session.commit()
    
    flash('Attribute deleted successfully.', 'success')
    return redirect(url_for('edit_plan', plan_id=plan_id))


@app.route('/plans/delete/<int:plan_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_plan(plan_id):
    plan = owned_or_404(Plan, plan_id)
    plan_name = plan.name
    
    # Delete related records
    RadGroupCheck.query.filter_by(groupname=plan.group_name).delete()
    RadGroupReply.query.filter_by(groupname=plan.group_name).delete()
    RadUserGroup.query.filter_by(groupname=plan.group_name).delete()
    
    db.session.delete(plan)
    db.session.commit()
    
    flash(f'Plan {plan_name} deleted successfully.', 'success')
    return redirect(url_for('plans'))


# NAS management routes
@app.route('/nas')
@login_required
@role_required('admin')
def nas_list():
    all_nas = scoped(Nas).order_by(Nas.created_at.desc()).all()
    return render_template('nas/list.html', nas_list=all_nas)


@app.route('/nas/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_nas():
    form = NasForm()
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    if form.validate_on_submit():
        # IPs are global: FreeRADIUS identifies a router by its address
        if Nas.query.filter_by(nasname=form.nasname.data).first():
            flash('A router with this IP address is already registered.', 'danger')
            return render_template('nas/form.html', form=form, title='Add NAS')
        
        nas = Nas(
            tenant_id=tenant_id(),
            nasname=form.nasname.data,
            shortname=form.shortname.data,
            type=form.type.data,
            secret=form.secret.data,
            vendor=form.vendor.data,
            ports=form.ports.data,
            server=form.server.data,
            community=form.community.data,
            description=form.description.data,
            is_active=form.is_active.data
        )
        db.session.add(nas)
        db.session.commit()
        
        flash(f'NAS {form.shortname.data} added successfully.', 'success')
        return redirect(url_for('nas_list'))
    
    return render_template('nas/form.html', form=form, title='Add NAS')


@app.route('/nas/edit/<int:nas_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_nas(nas_id):
    nas = owned_or_404(Nas, nas_id)
    form = NasForm(obj=nas)
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    if form.validate_on_submit():
        if Nas.query.filter(Nas.nasname == form.nasname.data, Nas.id != nas.id).first():
            flash('A router with this IP address is already registered.', 'danger')
            return render_template('nas/form.html', form=form, nas=nas, title='Edit NAS')
        nas.nasname = form.nasname.data
        nas.shortname = form.shortname.data
        nas.type = form.type.data
        nas.secret = form.secret.data
        nas.vendor = form.vendor.data
        nas.ports = form.ports.data
        nas.server = form.server.data
        nas.community = form.community.data
        nas.description = form.description.data
        nas.is_active = form.is_active.data
        
        db.session.commit()
        flash(f'NAS {nas.shortname} updated successfully.', 'success')
        return redirect(url_for('nas_list'))
    
    return render_template('nas/form.html', form=form, nas=nas, title='Edit NAS')


@app.route('/nas/test/<int:nas_id>', methods=['POST'])
@login_required
@role_required('admin')
def test_nas_connection(nas_id):
    """Test RADIUS connection to a NAS device"""
    nas = owned_or_404(Nas, nas_id)
    
    try:
        # Test if NAS is reachable
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        
        # Try to connect to RADIUS port
        test_result = sock.connect_ex((nas.nasname, 1812))
        sock.close()
        
        if test_result == 0:
            message = f'NAS {nas.shortname} ({nas.nasname}) is reachable on port 1812'
            if request.is_json:
                return jsonify({
                    'success': True,
                    'message': message
                })
            flash(message, 'success')
        else:
            message = f'Cannot reach NAS {nas.shortname} ({nas.nasname}) on port 1812. Check network connectivity.'
            if request.is_json:
                return jsonify({
                    'success': False,
                    'message': message
                }), 400
            flash(message, 'warning')
    except socket.gaierror:
        message = f'Invalid IP address: {nas.nasname}'
        if request.is_json:
            return jsonify({
                'success': False,
                'message': message
            }), 400
        flash(message, 'danger')
    except Exception as e:
        message = f'Connection test failed: {str(e)}'
        if request.is_json:
            return jsonify({
                'success': False,
                'message': message
            }), 500
        flash(message, 'danger')
    
    return redirect(url_for('nas_list'))


@app.route('/nas/delete/<int:nas_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_nas(nas_id):
    nas = owned_or_404(Nas, nas_id)
    shortname = nas.shortname
    
    db.session.delete(nas)
    db.session.commit()
    
    flash(f'NAS {shortname} deleted successfully.', 'success')
    return redirect(url_for('nas_list'))


# Accounting routes
@app.route('/accounting')
@login_required
def accounting():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status = request.args.get('status', 'all', type=str)
    
    query = RadAcct.query.filter(RadAcct.username.in_(tenant_usernames()))
    
    if search:
        query = query.filter(or_(
            RadAcct.username.like(f'%{search}%'),
            RadAcct.nasipaddress.like(f'%{search}%'),
            RadAcct.framedipaddress.like(f'%{search}%')
        ))
    
    if status == 'active':
        query = query.filter(RadAcct.acctstoptime.is_(None))
    elif status == 'closed':
        query = query.filter(RadAcct.acctstoptime.isnot(None))
    
    pagination = query.order_by(desc(RadAcct.acctstarttime)).paginate(
        page=page, per_page=Config.ITEMS_PER_PAGE, error_out=False
    )
    
    return render_template('accounting/list.html', pagination=pagination, search=search, status=status)


@app.route('/accounting/<int:session_id>')
@login_required
def accounting_detail(session_id):
    session = RadAcct.query.filter(RadAcct.radacctid == session_id,
                                   RadAcct.username.in_(tenant_usernames())).first_or_404()
    
    # Calculate bandwidth usage
    total_bytes = (session.acctinputoctets or 0) + (session.acctoutputoctets or 0)
    total_mb = total_bytes / 1048576
    total_gb = total_bytes / 1073741824
    
    # Calculate session duration
    if session.acctstoptime:
        duration = session.acctstoptime - session.acctstarttime
        duration_seconds = duration.total_seconds()
    elif session.acctupdatetime:
        duration = session.acctupdatetime - session.acctstarttime
        duration_seconds = duration.total_seconds()
    else:
        duration_seconds = 0
    
    return render_template('accounting/detail.html', 
                         session=session, 
                         total_bytes=total_bytes,
                         total_mb=total_mb,
                         total_gb=total_gb,
                         duration_seconds=duration_seconds)


# Authentication/Authorization logs
@app.route('/auth-logs')
@login_required
def auth_logs():
    """View authentication and authorization logs"""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    reply_filter = request.args.get('reply', 'all', type=str)
    
    mine = RadPostAuth.username.in_(tenant_usernames())
    query = RadPostAuth.query.filter(mine)
    
    if search:
        query = query.filter(RadPostAuth.username.like(f'%{search}%'))
    
    if reply_filter == 'Access-Accept':
        query = query.filter(RadPostAuth.reply == 'Access-Accept')
    elif reply_filter == 'Access-Reject':
        query = query.filter(RadPostAuth.reply == 'Access-Reject')
    elif reply_filter == 'Access-Challenge':
        query = query.filter(RadPostAuth.reply == 'Access-Challenge')
    
    pagination = query.order_by(desc(RadPostAuth.authdate)).paginate(
        page=page, per_page=Config.ITEMS_PER_PAGE, error_out=False
    )
    
    # Statistics
    total_auths = RadPostAuth.query.filter(mine).count()
    accepted = RadPostAuth.query.filter(mine, RadPostAuth.reply == 'Access-Accept').count()
    rejected = RadPostAuth.query.filter(mine, RadPostAuth.reply == 'Access-Reject').count()
    challenged = RadPostAuth.query.filter(mine, RadPostAuth.reply == 'Access-Challenge').count()
    
    return render_template('auth/logs.html', 
                         pagination=pagination, 
                         search=search,
                         reply_filter=reply_filter,
                         total_auths=total_auths,
                         accepted=accepted,
                         rejected=rejected,
                         challenged=challenged)


# RADIUS Features Configuration
@app.route('/radius-features')
@login_required
def radius_features():
    """Display all available RADIUS features and attributes"""
    
    # Standard RADIUS attributes
    standard_attributes = {
        'Session Management': [
            ('Session-Timeout', ':=', '3600', 'Maximum session time in seconds'),
            ('Idle-Timeout', ':=', '600', 'Disconnect after idle time (seconds)'),
            ('Acct-Interim-Interval', ':=', '300', 'Accounting update interval (seconds)'),
            ('Max-Daily-Session', ':=', '28800', 'Maximum daily session time (seconds)'),
        ],
        'Network Configuration': [
            ('Framed-IP-Address', ':=', '192.168.1.100', 'Assign specific IP address'),
            ('Framed-IP-Netmask', ':=', '255.255.255.0', 'Subnet mask for framed IP'),
            ('Framed-Route', ':=', '192.168.2.0/24', 'Add static route'),
            ('Framed-IPX-Network', ':=', '0x12345678', 'IPX network number'),
        ],
        'Service Control': [
            ('Service-Type', ':=', 'Framed-User', 'Type of service (Framed-User, Login-User, etc.)'),
            ('Framed-Protocol', ':=', 'PPP', 'Framing protocol (PPP, SLIP, etc.)'),
            ('Reply-Message', ':=', 'Welcome!', 'Message to user'),
            ('Login-Service', ':=', 'Telnet', 'Login service type'),
        ],
        'Bandwidth & QoS': [
            ('Mikrotik-Rate-Limit', ':=', '10M/10M', 'MikroTik: Upload/Download speed limit'),
            ('Cisco-AVPair', ':=', 'ip:sub-qos-policy-in=POLICY_10M', 'Cisco: QoS policy'),
            ('WISPr-Bandwidth-Max-Down', ':=', '10485760', 'Maximum download bandwidth (bytes/sec)'),
            ('WISPr-Bandwidth-Max-Up', ':=', '10485760', 'Maximum upload bandwidth (bytes/sec)'),
        ],
        'VLAN Assignment': [
            ('Tunnel-Type', ':=', 'VLAN', 'Tunnel type (VLAN, etc.)'),
            ('Tunnel-Medium-Type', ':=', 'IEEE-802', 'Tunnel medium type'),
            ('Tunnel-Private-Group-Id', ':=', '100', 'VLAN ID'),
        ],
        'Data Limits': [
            ('Mikrotik-Recv-Limit', ':=', '10737418240', 'MikroTik: Receive limit in bytes'),
            ('Mikrotik-Xmit-Limit', ':=', '10737418240', 'MikroTik: Transmit limit in bytes'),
            ('Ubiquiti-Data-Limit-Down', ':=', '10737418240', 'Ubiquiti: Download limit in bytes'),
            ('Ubiquiti-Data-Limit-Up', ':=', '10737418240', 'Ubiquiti: Upload limit in bytes'),
        ],
    }
    
    # Vendor-specific attributes
    vendor_attributes = {
        'Cisco': [
            ('Cisco-AVPair', ':=', 'ip:inacl#1=permit ip any any', 'Input ACL'),
            ('Cisco-AVPair', ':=', 'ip:outacl#1=permit ip any any', 'Output ACL'),
            ('Cisco-AVPair', ':=', 'ip:sub-qos-policy-in=POLICY_10M', 'Input QoS policy'),
            ('Cisco-AVPair', ':=', 'ip:sub-qos-policy-out=POLICY_10M', 'Output QoS policy'),
        ],
        'MikroTik': [
            ('Mikrotik-Rate-Limit', ':=', '10M/10M', 'Upload/Download speed'),
            ('Mikrotik-Recv-Limit', ':=', '10737418240', 'Receive data limit (bytes)'),
            ('Mikrotik-Xmit-Limit', ':=', '10737418240', 'Transmit data limit (bytes)'),
            ('Mikrotik-Address-List', ':=', 'premium_users', 'Address list assignment'),
        ],
        'Ubiquiti/UniFi': [
            ('Ubiquiti-Data-Limit-Down', ':=', '10737418240', 'Download limit (bytes)'),
            ('Ubiquiti-Data-Limit-Up', ':=', '10737418240', 'Upload limit (bytes)'),
            ('Ubiquiti-VLAN-ID', ':=', '100', 'VLAN assignment'),
        ],
        'Aruba': [
            ('Aruba-User-Role', ':=', 'employee', 'User role assignment'),
            ('Aruba-Admin-Role', ':=', 'network-admin', 'Admin role assignment'),
        ],
    }
    
    return render_template('radius/features.html',
                         standard_attributes=standard_attributes,
                         vendor_attributes=vendor_attributes)


# Vouchers
VOUCHER_CODE_LENGTH = 8


def _check_csrf():
    try:
        validate_csrf(request.form.get('csrf_token'))
    except ValidationError:
        abort(400)


def _new_voucher_code(taken):
    """Random numeric code (digits only: no case or O/0 confusion on phones)."""
    while True:
        code = ''.join(secrets.choice('0123456789') for _ in range(VOUCHER_CODE_LENGTH))
        if code[0] != '0' and code not in taken:
            taken.add(code)
            return code


def disconnect_subscriber(tid, username):
    """Cut a user/voucher off right away. SafeNet gateways pick up the kick on
    their next check (about 10 s); routers in the nas table get a RADIUS
    Disconnect-Request for each open session. Caller commits."""
    db.session.add(SessionKick(tenant_id=tid, username=username))
    recent = datetime.utcnow() - timedelta(days=2)
    targets = []
    for s in RadAcct.query.filter(RadAcct.username == username, RadAcct.acctstoptime.is_(None),
                                  func.coalesce(RadAcct.acctupdatetime, RadAcct.acctstarttime) >= recent):
        nas = Nas.query.filter_by(nasname=s.nasipaddress, tenant_id=tid).first()
        if nas and nas.secret:
            targets.append((s.nasipaddress, nas.secret, username, s.acctsessionid, s.framedipaddress))

    def send():
        for target in targets:
            ok, message = radclient.disconnect(*target)
            log.info('disconnect %s on %s: %s', username, target[0], message)
    if targets:
        threading.Thread(target=send, daemon=True).start()
    return len(targets)


def _radius_username_taken(username):
    """RADIUS usernames are global: users, voucher codes and radcheck rows of every tenant."""
    return bool(RadUser.query.filter_by(username=username).first()
                or Voucher.query.filter_by(code=username).first()
                or RadCheck.query.filter_by(username=username).first())


def _sync_plan_rate_limit(plan):
    """Keep Mikrotik-Rate-Limit ("upload/download") in step with the plan's speeds,
    unless the plan has its own Mikrotik-Rate-Limit attribute."""
    if PlanAttribute.query.filter_by(plan_id=plan.id, attribute='Mikrotik-Rate-Limit').first():
        return
    RadGroupReply.query.filter_by(groupname=plan.group_name, attribute='Mikrotik-Rate-Limit').delete()
    if plan.upload_speed or plan.download_speed:
        db.session.add(RadGroupReply(groupname=plan.group_name, attribute='Mikrotik-Rate-Limit', op=':=',
                                     value=f'{plan.upload_speed or 0}/{plan.download_speed or 0}'))


def _new_group_name(plan_name):
    """Globally unique FreeRADIUS group for a new plan of the current tenant."""
    base = f't{tenant_id()}-{plan_name}'[:56]
    name = base
    while Plan.query.filter_by(group_name=name).first():
        name = f'{base}-{secrets.token_hex(3)}'
    return name


def _create_vouchers(count, plan, minutes, price, batch, tenant=None, max_devices=1):
    """Adds `count` vouchers (and their RADIUS rows) to the session; caller commits."""
    # Codes double as RADIUS usernames, so avoid clashes with both tables.
    taken = {c for (c,) in db.session.query(Voucher.code)}
    taken |= {u for (u,) in db.session.query(RadCheck.username).distinct()}
    created = []
    for _ in range(count):
        code = _new_voucher_code(taken)
        voucher = Voucher(tenant_id=tenant if tenant is not None else tenant_id(),
                          code=code, plan_id=plan.id if plan else None, batch=batch,
                          validity_minutes=minutes, price=price, max_devices=max_devices or 1)
        db.session.add(voucher)
        db.session.add(RadCheck(username=code, attribute='Cleartext-Password', op=':=', value=code))
        if plan:
            db.session.add(RadUserGroup(username=code, groupname=plan.group_name, priority=1))
        created.append(voucher)
    return created


@app.route('/vouchers')
@login_required
def vouchers():
    page = request.args.get('page', 1, type=int)
    batch = request.args.get('batch', '', type=str)
    state = request.args.get('state', '', type=str)
    search = request.args.get('search', '', type=str).strip()

    now = datetime.utcnow()
    query = scoped(Voucher)
    if batch:
        query = query.filter(Voucher.batch == batch)
    if search:
        query = query.filter(Voucher.code.like(f'%{search}%'))
    if state == 'unused':
        query = query.filter(Voucher.status == 'unused')
    elif state == 'active':
        query = query.filter(Voucher.status == 'active', Voucher.expires_at > now)
    elif state == 'expired':
        query = query.filter(Voucher.status != 'disabled', Voucher.expires_at <= now)
    elif state == 'disabled':
        query = query.filter(Voucher.status == 'disabled')

    pagination = query.order_by(Voucher.created_at.desc(), Voucher.id.desc()).paginate(
        page=page, per_page=Config.ITEMS_PER_PAGE, error_out=False
    )

    batches = [b for (b,) in db.session.query(Voucher.batch).filter(Voucher.tenant_id == tenant_id())
               .group_by(Voucher.batch).order_by(func.max(Voucher.created_at).desc()).limit(50)]
    stats = {
        'unused': scoped(Voucher).filter_by(status='unused').count(),
        'active': scoped(Voucher).filter(Voucher.status == 'active', Voucher.expires_at > now).count(),
        'expired': scoped(Voucher).filter(Voucher.status != 'disabled', Voucher.expires_at <= now).count(),
        'sold_value': db.session.query(func.coalesce(func.sum(Voucher.price), 0))
                        .filter(Voucher.tenant_id == tenant_id(), Voucher.first_used_at.isnot(None)).scalar(),
    }
    return render_template('vouchers/list.html', pagination=pagination, batches=batches,
                           batch=batch, state=state, search=search, stats=stats,
                           currency=current_tenant().currency)


@app.route('/vouchers/generate', methods=['GET', 'POST'])
@login_required
def generate_vouchers():
    form = VoucherGenerateForm()
    form.plan_id.choices = [(0, '-- No Plan --')] + [(p.id, p.name) for p in scoped(Plan).filter_by(is_active=True).all()]

    if form.validate_on_submit():
        plan = scoped(Plan).filter_by(id=form.plan_id.data).first() if form.plan_id.data else None
        minutes = form.validity_value.data * (1440 if form.validity_unit.data == 'days' else 60)
        price = Decimal(form.price.data.strip()) if form.price.data else None
        batch = (form.batch.data or '').strip() or datetime.utcnow().strftime('%Y%m%d-%H%M%S')

        _create_vouchers(form.count.data, plan, minutes, price, batch, max_devices=form.max_devices.data)
        db.session.commit()

        flash(f'{form.count.data} vouchers created in batch "{batch}".', 'success')
        return redirect(url_for('vouchers', batch=batch))

    return render_template('vouchers/generate.html', form=form, currency=current_tenant().currency)


@app.route('/vouchers/print')
@login_required
def print_vouchers():
    batch = request.args.get('batch', '', type=str)
    if not batch:
        flash('Choose a batch to print.', 'warning')
        return redirect(url_for('vouchers'))
    items = scoped(Voucher).filter_by(batch=batch, status='unused').order_by(Voucher.id).all()
    return render_template('vouchers/print.html', vouchers=items, batch=batch,
                           hotspot=_hotspot_settings(current_tenant()))


@app.route('/vouchers/<int:voucher_id>/toggle', methods=['POST'])
@login_required
def toggle_voucher(voucher_id):
    _check_csrf()
    voucher = owned_or_404(Voucher, voucher_id)
    if voucher.status == 'disabled':
        voucher.status = 'active' if voucher.first_used_at else 'unused'
        flash(f'Voucher {voucher.code} enabled.', 'success')
    else:
        voucher.status = 'disabled'
        disconnect_subscriber(voucher.tenant_id, voucher.code)
        flash(f'Voucher {voucher.code} disabled and its devices disconnected.', 'success')
    db.session.commit()
    return redirect(request.referrer or url_for('vouchers'))


@app.route('/vouchers/<int:voucher_id>/delete', methods=['POST'])
@login_required
def delete_voucher(voucher_id):
    _check_csrf()
    voucher = owned_or_404(Voucher, voucher_id)
    code = voucher.code
    if voucher.first_used_at:
        disconnect_subscriber(voucher.tenant_id, code)
    RadCheck.query.filter_by(username=code).delete()
    RadReply.query.filter_by(username=code).delete()
    RadUserGroup.query.filter_by(username=code).delete()
    db.session.delete(voucher)
    db.session.commit()
    flash(f'Voucher {code} deleted.', 'success')
    return redirect(request.referrer or url_for('vouchers'))


@app.route('/vouchers/delete-unused', methods=['POST'])
@login_required
def delete_unused_batch():
    _check_csrf()
    batch = request.form.get('batch', '')
    codes = [c for (c,) in db.session.query(Voucher.code).filter_by(tenant_id=tenant_id(), batch=batch, status='unused')]
    if codes:
        RadCheck.query.filter(RadCheck.username.in_(codes)).delete(synchronize_session=False)
        RadReply.query.filter(RadReply.username.in_(codes)).delete(synchronize_session=False)
        RadUserGroup.query.filter(RadUserGroup.username.in_(codes)).delete(synchronize_session=False)
        Voucher.query.filter(Voucher.code.in_(codes)).delete(synchronize_session=False)
        db.session.commit()
    flash(f'Deleted {len(codes)} unused vouchers from batch "{batch}".', 'success')
    return redirect(url_for('vouchers'))


# Public guest portal
def _hotspot_settings(tenant):
    if tenant is None or tenant.slug == migrations.DEFAULT_TENANT_SLUG:
        defaults = {'name': Config.HOTSPOT_NAME, 'ssid': Config.HOTSPOT_SSID,
                    'support': Config.HOTSPOT_SUPPORT, 'terms': Config.HOTSPOT_TERMS}
    else:
        defaults = {'name': tenant.name, 'ssid': '', 'support': '', 'terms': Config.HOTSPOT_TERMS}
    if tenant is None:
        return {**defaults, 'currency': Config.HOTSPOT_CURRENCY}
    return {
        'name': tenant.hotspot_name or defaults['name'],
        'ssid': defaults['ssid'],
        'support': tenant.support_phone or defaults['support'],
        'terms': tenant.terms or defaults['terms'],
        'currency': tenant.currency,
    }


def _is_gateway_url(url):
    """Only post codes to a local hotspot gateway or Meraki, never an arbitrary site."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == 'meraki.com' or host.endswith('.meraki.com') or host.endswith('.network-auth.com'):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_link_local
    except ValueError:
        return '.' not in host or host.endswith(('.local', '.lan', '.wifi'))


def portal_config(tenant):
    """Portal look and text for a tenant, as gateway/portal_ui.theme() expects."""
    hs = _hotspot_settings(tenant)
    cfg = {'name': hs['name'], 'support': hs['support'], 'terms': hs['terms'], 'ssid': hs['ssid'], 'logo_version': None}
    if tenant is not None:
        cfg.update(color=tenant.portal_color, style=tenant.portal_style, title=tenant.portal_title,
                   message=tenant.portal_message, language=tenant.portal_language,
                   show_voucher=tenant.portal_show_voucher, show_packages=tenant.portal_show_packages,
                   logo_version=int(tenant.portal_logo_at.timestamp()) if tenant.portal_logo_at else None)
    return cfg


def _portal_packages(tenant):
    if tenant is None:
        return []
    return [{'id': p.id, 'name': p.name, 'description': p.description or '', 'price': f'{p.price:.0f}',
             'currency': p.currency, 'validity_minutes': p.validity_minutes}
            for p in Package.query.filter_by(tenant_id=tenant.id, is_active=True, show_on_portal=True)
                                  .order_by(Package.sort_order, Package.price)]


PREVIEW_FIELDS = ('color', 'style', 'title', 'message', 'show_voucher', 'show_packages')


@app.route('/portal')
def portal():
    """Guest splash page with the tenant's branding (same design as the gateway).

    Gateways redirect here with their own login URL:
      MikroTik external login: ?link-login-only=...&link-orig=...&error=...
      Meraki sign-on splash:   ?login_url=...&continue_url=...
    Without one it shows how to connect with WPA2-Enterprise.
    ?preview=1&view=voucher|buy|wait|online renders a screen for the settings page;
    unsaved settings can be passed as query parameters in preview mode.
    """
    slug = request.args.get('t', migrations.DEFAULT_TENANT_SLUG)[:64]
    tenant = Tenant.query.filter_by(slug=slug).first()
    cfg = portal_config(tenant)
    preview = request.args.get('preview') == '1'
    if preview:
        for key in PREVIEW_FIELDS:
            if key in request.args:
                value = request.args[key][:300]
                cfg[key] = value == '1' if key.startswith('show_') else value
    if cfg.get('logo_version') and tenant is not None:
        cfg['logo_url'] = url_for('portal_logo', slug=tenant.slug, v=cfg['logo_version'])
    th = portal_ui.theme(cfg)
    wanted = request.args.get('lang')
    lang = wanted if wanted in portal_ui.LANGS else request.cookies.get('sn_lang') if request.cookies.get('sn_lang') in portal_ui.LANGS else th['language']
    mikrotik_login = request.args.get('link-login-only', '')
    meraki_login = request.args.get('login_url', '')
    gateway = None
    if mikrotik_login and _is_gateway_url(mikrotik_login):
        gateway = {'action': mikrotik_login, 'next_field': 'dst', 'next_value': request.args.get('link-orig', '')}
        passthrough = ('link-login-only', 'link-orig', 'error')
    elif meraki_login and _is_gateway_url(meraki_login):
        gateway = {'action': meraki_login, 'next_field': 'success_url', 'next_value': request.args.get('continue_url', '')}
        passthrough = ('login_url', 'continue_url')
    else:
        passthrough = ()
    # The language switch only repeats parameters we trust
    lang_url = url_for('portal', t=slug, **{k: request.args[k] for k in passthrough if k in request.args})

    if preview:
        view = request.args.get('view', 'buy')
        packages = _portal_packages(tenant) or [
            {'id': 1, 'name': '1 Hour', 'price': '500', 'currency': 'TZS', 'validity_minutes': 60},
            {'id': 2, 'name': '1 Day', 'price': '1000', 'currency': 'TZS', 'validity_minutes': 1440},
            {'id': 3, 'name': '1 Week', 'price': '5000', 'currency': 'TZS', 'validity_minutes': 10080}]
        if view == 'online':
            html_out = portal_ui.status_page(th, lang, user='48291175', remaining=5 * 3600 + 1200, total=86400,
                                             new_code='48291175', preview=True)
        elif view == 'wait':
            html_out = portal_ui.waiting_page(th, lang, ref='PREVIEW', info={'amount': packages[0]['price'], 'currency': 'TZS',
                                                                             'phone': '255712345678', 'package': packages[0]['name']})
            html_out = html_out.replace('<meta http-equiv="refresh"', '<meta name="no-refresh"')
        else:
            html_out = portal_ui.login_page(th, lang, packages=packages, tab='voucher' if view == 'voucher' else 'buy',
                                            preview=True, lang_url=lang_url, networks=payment_networks(),
                                            logo_base=url_for('static', filename='img/'))
    else:
        if gateway:
            html_out = portal_ui.login_page(th, lang, external=gateway, buy_enabled=False, tab='voucher',
                                            error=request.args.get('error', '')[:200], lang_url=lang_url)
        else:
            html_out = portal_ui.instructions_page(th, lang, lang_url=lang_url)
    resp = make_response(html_out)
    resp.headers['Cache-Control'] = 'no-store'
    if wanted in portal_ui.LANGS:
        resp.set_cookie('sn_lang', wanted, max_age=31536000, samesite='Lax')
    return resp


def _logo_response(tenant):
    if tenant is None or not tenant.portal_logo_at:
        abort(404)
    data = db.session.query(Tenant.portal_logo).filter(Tenant.id == tenant.id).scalar()
    if not data:
        abort(404)
    return Response(data, mimetype=tenant.portal_logo_type or 'image/png',
                    headers={'Cache-Control': 'public, max-age=86400', 'X-Content-Type-Options': 'nosniff'})


@app.route('/portal/logo/<slug>')
def portal_logo(slug):
    return _logo_response(Tenant.query.filter_by(slug=slug[:64]).first())


LOGO_TYPES = ((b'\x89PNG\r\n\x1a\n', 'image/png'), (b'\xff\xd8\xff', 'image/jpeg'))
MAX_LOGO_BYTES = 300 * 1024


def _logo_type(data):
    for magic, kind in LOGO_TYPES:
        if data.startswith(magic):
            return kind
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


@app.route('/settings/portal', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def portal_settings():
    tenant = current_tenant()
    form = PortalSettingsForm(color=tenant.portal_color or portal_ui.DEFAULT_COLOR, style=tenant.portal_style or 'gradient',
                              title=tenant.portal_title, message=tenant.portal_message,
                              language=tenant.portal_language or 'en', show_voucher=tenant.portal_show_voucher,
                              show_packages=tenant.portal_show_packages)
    if form.validate_on_submit():
        upload = form.logo.data
        if upload and getattr(upload, 'filename', ''):
            data = upload.read(MAX_LOGO_BYTES + 1)
            kind = _logo_type(data)
            if len(data) > MAX_LOGO_BYTES or not kind:
                flash('The logo must be a PNG, JPG or WebP image of at most 300 KB.', 'danger')
                return redirect(url_for('portal_settings'))
            tenant.portal_logo, tenant.portal_logo_type, tenant.portal_logo_at = data, kind, datetime.utcnow()
        elif form.remove_logo.data:
            tenant.portal_logo = tenant.portal_logo_type = tenant.portal_logo_at = None
        tenant.portal_color = form.color.data.upper()
        tenant.portal_style = form.style.data
        tenant.portal_title = (form.title.data or '').strip() or None
        tenant.portal_message = (form.message.data or '').strip() or None
        tenant.portal_language = form.language.data
        tenant.portal_show_voucher = form.show_voucher.data
        tenant.portal_show_packages = form.show_packages.data
        db.session.commit()
        flash('Captive portal saved. Gateways pick up the changes within 5 minutes.', 'success')
        return redirect(url_for('portal_settings'))
    return render_template('portal_settings.html', form=form, has_logo=bool(tenant.portal_logo_at),
                           logo_url=url_for('portal_logo', slug=tenant.slug, v=int(tenant.portal_logo_at.timestamp()))
                           if tenant.portal_logo_at else None,
                           preview_base=url_for('portal', t=tenant.slug, preview=1),
                           package_count=scoped(Package).filter_by(is_active=True, show_on_portal=True).count(),
                           hotspot_name=_hotspot_settings(tenant)['name'])

# Packages (sold on the captive portal)
def _minutes_from(value, unit):
    return value * {'minutes': 1, 'hours': 60, 'days': 1440}[unit]


def _split_minutes(minutes):
    for unit, size in (('days', 1440), ('hours', 60)):
        if minutes % size == 0:
            return minutes // size, unit
    return minutes, 'minutes'


@app.route('/packages')
@login_required
@role_required('admin')
def packages():
    items = scoped(Package).order_by(Package.sort_order, Package.price).all()
    return render_template('packages/list.html', packages=items,
                           clickpesa_ready=clickpesa.is_configured(_tenant_credentials(current_tenant())),
                           portal_api_ready=bool(scoped(Gateway).filter_by(is_active=True).count() or Config.PORTAL_API_KEY))


def _package_form():
    form = PackageForm()
    form.plan_id.choices = [(0, '-- No speed limit --')] + [(p.id, p.name) for p in scoped(Plan).filter_by(is_active=True).all()]
    return form


def _fill_package(package, form):
    package.name = form.name.data.strip()
    package.description = (form.description.data or '').strip() or None
    package.plan_id = form.plan_id.data or None
    package.price = Decimal(form.price.data.strip())
    package.validity_minutes = _minutes_from(form.validity_value.data, form.validity_unit.data)
    package.max_devices = form.max_devices.data
    package.sort_order = form.sort_order.data or 0
    package.is_active = form.is_active.data
    package.show_on_portal = form.show_on_portal.data


@app.route('/packages/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_package():
    form = _package_form()
    if form.validate_on_submit():
        package = Package(tenant_id=tenant_id(), currency=current_tenant().currency)
        _fill_package(package, form)
        db.session.add(package)
        db.session.commit()
        flash(f'Package "{package.name}" created.', 'success')
        return redirect(url_for('packages'))
    return render_template('packages/form.html', form=form, title='New Package')


@app.route('/packages/<int:package_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_package(package_id):
    package = owned_or_404(Package, package_id)
    form = _package_form()
    if request.method == 'GET':
        form.process(obj=package)
        form.plan_id.data = package.plan_id or 0
        form.price.data = f'{package.price:.0f}' if package.price == int(package.price) else str(package.price)
        form.validity_value.data, form.validity_unit.data = _split_minutes(package.validity_minutes)
    if form.validate_on_submit():
        _fill_package(package, form)
        db.session.commit()
        flash(f'Package "{package.name}" updated.', 'success')
        return redirect(url_for('packages'))
    return render_template('packages/form.html', form=form, title='Edit Package', package=package)


@app.route('/packages/<int:package_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_package(package_id):
    _check_csrf()
    package = owned_or_404(Package, package_id)
    name = package.name
    db.session.delete(package)
    db.session.commit()
    flash(f'Package "{name}" deleted. Past payments keep their records.', 'success')
    return redirect(url_for('packages'))


# Payments
log = logging.getLogger('safenet')


def payment_networks():
    return portal_ui.parse_networks(Config.PAYMENT_NETWORKS)


def check_network(phone, network_id, amount, currency='TZS'):
    """Error message if this number/network/amount can't be paid, else None."""
    networks = payment_networks()
    if not networks:
        return None
    by_id = {n['id']: n for n in networks}
    known = portal_ui.network_for_phone(phone)
    if network_id is None:                      # no choice made (e.g. Billing): judge by the number
        network_id = known
        if network_id and network_id not in by_id:
            return (f"{portal_ui.NETWORKS[network_id]['name']} numbers can't pay yet. "
                    f"Use {', '.join(n['name'] for n in networks)}.")
        if network_id is None:
            return None
    net = by_id.get(network_id)
    if not net:
        return 'Choose your mobile-money network.'
    if known and known != network_id:
        other = portal_ui.NETWORKS[known]['name']
        if known in by_id:
            return f"That looks like a {other} number. Choose {other}, or enter your {net['name']} number."
        return f"That is a {other} number, and {other} isn't available yet. Use a {net['name']} number."
    if net['min_amount'] and amount < net['min_amount']:
        return (f"{net['name']} payments start from {currency} {net['min_amount']:,}. "
                f"Choose a bigger package or another network.")
    return None


def _normalize_tz_phone(raw):
    """0712 345 678 / +255 712 345 678 / 712345678 -> 255712345678, else None."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) == 10 and digits.startswith('0'):
        digits = '255' + digits[1:]
    elif len(digits) == 9:
        digits = '255' + digits
    return digits if re.fullmatch(r'255[67]\d{8}', digits) else None


def _own_credentials(tenant):
    return clickpesa.Credentials(tenant.clickpesa_client_id or '', secretbox.decrypt(tenant.clickpesa_api_key_enc),
                                 secretbox.decrypt(tenant.clickpesa_checksum_key_enc))


def _tenant_credentials(tenant):
    """ClickPesa account that receives this tenant's package sales."""
    return _own_credentials(tenant) if tenant.payment_mode == 'own' else clickpesa.platform_credentials()


def _payment_credentials(payment):
    return _own_credentials(payment.tenant) if payment.provider_account == 'own' else clickpesa.platform_credentials()


def _fee_percent(tenant):
    return Decimal(str(tenant.fee_percent if tenant.fee_percent is not None else Config.PLATFORM_FEE_PERCENT))


def tenant_balance(tid):
    """(balance, earned, withdrawn) of platform-collected sales for a tenant."""
    earned = db.session.query(func.coalesce(func.sum(Payment.net_amount), 0)).filter(
        Payment.tenant_id == tid, Payment.status == 'paid', Payment.provider_account == 'platform').scalar()
    withdrawn = db.session.query(func.coalesce(func.sum(Withdrawal.amount), 0)).filter(
        Withdrawal.tenant_id == tid, Withdrawal.status.in_(('requested', 'paid'))).scalar()
    earned, withdrawn = Decimal(str(earned)), Decimal(str(withdrawn))
    return earned - withdrawn, earned, withdrawn


def _fulfil_payment(payment):
    """Paid: issue a voucher for the package (once)."""
    if payment.voucher_id:
        return
    voucher = _create_vouchers(1, payment.plan, payment.validity_minutes, payment.amount, 'online-payments',
                               tenant=payment.tenant_id, max_devices=payment.max_devices)[0]
    db.session.flush()
    payment.voucher_id = voucher.id
    payment.status = 'paid'
    payment.paid_at = datetime.utcnow()
    log.info('payment %s paid: voucher %s', payment.reference, voucher.code)
    brand = _hotspot_settings(payment.tenant)
    send_sms_async(payment.phone, f'{brand["name"]}: payment of {payment.currency} {payment.amount:,.0f} received. '
                                  f'Your WiFi code is {voucher.code}, valid {format_minutes(payment.validity_minutes)} '
                                  f'from first login. Keep it to reconnect.'
                                  + (f' Help: {brand["support"]}' if brand['support'] else ''), payment.reference)


def _refresh_payment(reference, force=False):
    """Checks a pending payment with ClickPesa. Locks the row so a payment is
    fulfilled exactly once even if the webhook and the portal poll race."""
    payment = Payment.query.filter_by(reference=reference).with_for_update().first()
    if not payment:
        db.session.rollback()
        return None
    now = datetime.utcnow()
    due = force or not payment.checked_at or (now - payment.checked_at).total_seconds() >= 3
    if payment.status == 'pending' and due:
        payment.checked_at = now
        try:
            record = clickpesa.query_payment(reference, _payment_credentials(payment))
        except clickpesa.ClickPesaError as e:
            log.warning('ClickPesa query %s failed: %s', reference, e)
            record = None
        if record:
            status = (record.get('status') or '').upper()
            payment.provider_status = status
            payment.channel = record.get('channel') or payment.channel
            payment.message = (record.get('message') or payment.message or '')[:255] or None
            if status in ('SUCCESS', 'SETTLED'):
                collected = record.get('collectedAmount')
                if collected is not None and Decimal(str(collected)) < payment.amount:
                    payment.status = 'review'
                    payment.message = f'Collected {collected}, expected {payment.amount}'
                else:
                    _fulfil_payment(payment)
            elif status == 'FAILED':
                payment.status = 'failed'
    db.session.commit()
    return payment


@app.route('/payments')
@login_required
def payments():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    search = request.args.get('search', '', type=str).strip()
    query = scoped(Payment)
    if status:
        query = query.filter(Payment.status == status)
    if search:
        query = query.filter(or_(Payment.phone.like(f'%{search}%'), Payment.reference.like(f'%{search}%')))
    pagination = query.order_by(Payment.created_at.desc()).paginate(
        page=page, per_page=Config.ITEMS_PER_PAGE, error_out=False)

    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    tid = tenant_id()
    paid_total = lambda since=None: db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.tenant_id == tid, Payment.status == 'paid', *( [Payment.paid_at >= since] if since else [])).scalar()
    stats = {
        'today': paid_total(today),
        'month': paid_total(month),
        'all_time': paid_total(),
        'paid_count': scoped(Payment).filter_by(status='paid').count(),
        'pending': scoped(Payment).filter_by(status='pending').count(),
    }
    return render_template('payments/list.html', pagination=pagination, stats=stats, status=status,
                           search=search, currency=current_tenant().currency,
                           clickpesa_ready=clickpesa.is_configured(_tenant_credentials(current_tenant())))


@app.route('/payments/<int:payment_id>/refresh', methods=['POST'])
@login_required
def refresh_payment(payment_id):
    _check_csrf()
    payment = owned_or_404(Payment, payment_id)
    payment = _refresh_payment(payment.reference, force=True)
    flash(f'Payment {payment.reference}: {payment.status}.', 'info')
    return redirect(request.referrer or url_for('payments'))


# Captive-portal gateway API (JSON, authenticated with X-SafeNet-Key)
def tenant_blocked(tenant):
    """Suspended, or subscription/trial over (after grace): no service for its guests."""
    if tenant.status == 'suspended':
        return True
    until = getattr(tenant, 'service_until', None)
    return bool(until and until < datetime.utcnow())


def _hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def portal_api(fn):
    """Authenticates a gateway by its X-SafeNet-Key and sets g.api_tenant.
    The legacy shared PORTAL_API_KEY maps to the default tenant."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = request.headers.get('X-SafeNet-Key', '')
        tenant = gw = None
        if key:
            gw = Gateway.query.filter_by(key_hash=_hash_key(key), is_active=True).first()
            if gw:
                tenant = gw.tenant
                now = datetime.utcnow()
                if not gw.last_seen_at or (now - gw.last_seen_at).total_seconds() > 60:
                    gw.last_seen_at, gw.last_ip = now, request.remote_addr
                    db.session.commit()
            elif Config.PORTAL_API_KEY and hmac.compare_digest(key.encode(), Config.PORTAL_API_KEY.encode()):
                tenant = migrations.default_tenant()
        if tenant is None:
            return jsonify(error='unauthorized'), 401
        if tenant_blocked(tenant):
            return jsonify(error='This network is suspended.'), 403
        g.api_tenant = tenant
        g.api_gateway = gw
        return fn(*args, **kwargs)
    return wrapper


def _payment_json(payment):
    data = {
        'reference': payment.reference,
        'status': payment.status,
        'package': payment.package_name,
        'amount': f'{payment.amount:.0f}',
        'currency': payment.currency,
        'phone': payment.phone,
        'validity_minutes': payment.validity_minutes,
        'message': payment.message or '',
    }
    if payment.status == 'paid' and payment.voucher:
        data['code'] = payment.voucher.code
    return data


@app.route('/api/portal/packages')
@portal_api
def api_portal_packages():
    items = Package.query.filter_by(tenant_id=g.api_tenant.id, is_active=True, show_on_portal=True).order_by(
        Package.sort_order, Package.price).all()
    return jsonify(packages=[{
        'id': p.id, 'name': p.name, 'description': p.description or '',
        'price': f'{p.price:.0f}', 'currency': p.currency,
        'validity_minutes': p.validity_minutes, 'validity': p.validity_label,
    } for p in items], payments_enabled=clickpesa.is_configured(_tenant_credentials(g.api_tenant)),
                   networks=payment_networks())


@app.route('/api/portal/purchase', methods=['POST'])
@portal_api
def api_portal_purchase():
    data = request.get_json(silent=True) or {}
    package = Package.query.filter_by(id=data.get('package_id'), tenant_id=g.api_tenant.id,
                                      is_active=True, show_on_portal=True).first()
    if not package:
        return jsonify(error='That package is no longer available.'), 404
    phone = _normalize_tz_phone(str(data.get('phone', '')))
    if not phone:
        return jsonify(error='Enter a valid mobile number, e.g. 0712 345 678.'), 400
    tenant = g.api_tenant
    creds = _tenant_credentials(tenant)
    if not clickpesa.is_configured(creds):
        return jsonify(error='Mobile payments are not available right now.'), 503
    # Gateways send the network the guest picked; older ones don't, then the number decides
    problem = check_network(phone, str(data.get('network') or '') or None, package.price, package.currency)
    if problem:
        return jsonify(error=problem), 400
    recent = Payment.query.filter(Payment.phone == phone, Payment.status == 'pending',
                                  Payment.created_at >= datetime.utcnow() - timedelta(seconds=90)).count()
    if recent:
        return jsonify(error='A payment request was just sent to this number. Check your phone, or wait a minute.'), 429

    payment = Payment(
        tenant_id=g.api_tenant.id,
        reference='SN' + secrets.token_hex(6).upper(),
        package_id=package.id, package_name=package.name, plan_id=package.plan_id,
        validity_minutes=package.validity_minutes, max_devices=package.max_devices or 1, phone=phone,
        amount=package.price, currency=package.currency,
        provider_account=tenant.payment_mode,
        fee_amount=(package.price * _fee_percent(tenant) / 100).quantize(Decimal('0.01')) if tenant.payment_mode == 'platform' else Decimal(0),
        nas_identifier=str(data.get('nas', ''))[:64] or None,
        client_mac=str(data.get('mac', ''))[:17] or None,
        client_ip=str(data.get('ip', ''))[:45] or None,
    )
    payment.net_amount = payment.amount - payment.fee_amount
    db.session.add(payment)
    db.session.commit()
    try:
        available = clickpesa.preview_ussd_push(payment.amount, phone, payment.reference, creds)
        chosen = str(data.get('network') or '')
        offered = {portal_ui.network_for_method(m) for m in available}
        if available and chosen and chosen not in offered:
            payment.status = 'failed'
            payment.message = f'{chosen} not offered by ClickPesa for this number ({", ".join(available)})'
            db.session.commit()
            name = portal_ui.NETWORKS.get(chosen, {}).get('name', 'That network')
            return jsonify({**_payment_json(payment),
                            'error': f"{name} isn't available for this number right now. Try another network."}), 502
        if not available:
            payment.status = 'failed'
            payment.message = 'No mobile-money method available for this number'
            db.session.commit()
            return jsonify({**_payment_json(payment),
                            'error': "Mobile money for this number isn't available right now. Try another number or a voucher."}), 502
        tx = clickpesa.initiate_ussd_push(payment.amount, phone, payment.reference, creds) or {}
        payment.provider_id = tx.get('id')
        payment.provider_status = (tx.get('status') or '').upper() or None
        payment.channel = tx.get('channel')
        if payment.provider_status == 'FAILED':
            payment.status = 'failed'
    except clickpesa.ClickPesaError as e:
        log.warning('ClickPesa USSD push %s failed: %s', payment.reference, e)
        payment.status = 'failed'
        payment.message = str(e)[:255]
    db.session.commit()
    if payment.status == 'failed':
        return jsonify({**_payment_json(payment),
                        'error': "We couldn't send the payment request. Check the number and try again."}), 502
    return jsonify(_payment_json(payment))


@app.route('/api/portal/purchase/<reference>')
@portal_api
def api_portal_purchase_status(reference):
    if not Payment.query.filter_by(reference=reference, tenant_id=g.api_tenant.id).first():
        return jsonify(error='not found'), 404
    payment = _refresh_payment(reference)
    if not payment:
        return jsonify(error='not found'), 404
    return jsonify(_payment_json(payment))


# Gateway API (phase 2): login and accounting over HTTPS instead of RADIUS, so a
# gateway works from any ISP and is identified by its key, not its IP address.
def _subscriber_speeds(user, plan):
    """(upload, download) like "5M"; a user's own limits override the plan's."""
    up = (user.upload_speed if user else None) or (plan.upload_speed if plan else None)
    down = (user.download_speed if user else None) or (plan.download_speed if plan else None)
    return up or None, down or None


def _log_auth(username, accepted):
    db.session.add(RadPostAuth(username=username[:64], pass_field='', authdate=datetime.utcnow(),
                               reply='Access-Accept' if accepted else 'Access-Reject'))


def _devices_in_use(username, mac):
    """Other devices with a live session on this code (updated in the last 10 minutes)."""
    me = (mac or '').upper().replace(':', '-')
    recent = datetime.utcnow() - timedelta(minutes=10)
    rows = db.session.query(RadAcct.callingstationid).filter(
        RadAcct.username == username, RadAcct.acctstoptime.is_(None),
        func.coalesce(RadAcct.acctupdatetime, RadAcct.acctstarttime) >= recent).distinct()
    return {m for (m,) in rows if m and m.upper() != me}


def _gateway_authenticate(tenant, username, password, mac=None):
    """Same rules FreeRADIUS applies. Returns (ok, message, info)."""
    now = datetime.utcnow()
    voucher = Voucher.query.filter_by(code=username).with_for_update().first()
    user = None if voucher else RadUser.query.filter_by(username=username).first()
    owner = voucher.tenant_id if voucher else (user.tenant_id if user else None)
    secret = RadCheck.query.filter_by(username=username, attribute='Cleartext-Password').first()
    if owner != tenant.id or not secret or not hmac.compare_digest(secret.value.encode(), password.encode()):
        return False, "That code isn't valid. Check it and try again.", None

    if voucher:
        if voucher.status == 'disabled' or (voucher.expires_at and voucher.expires_at <= now):
            return False, 'Voucher expired or disabled', None
        if mac and len(_devices_in_use(username, mac)) >= (voucher.max_devices or 1):
            return False, 'This code is already being used on another device.', None
        if not voucher.first_used_at:
            voucher.first_used_at = now
            voucher.expires_at = now + timedelta(minutes=voucher.validity_minutes)
            voucher.status = 'active'
        remaining = int((voucher.expires_at - now).total_seconds())
        up, down = _subscriber_speeds(None, voucher.plan)
    else:
        if not user.is_active:
            return False, 'This account is disabled', None
        if user.expires_at and user.expires_at <= now:
            return False, 'This account has expired', None
        remaining = int((user.expires_at - now).total_seconds()) if user.expires_at else None
        up, down = _subscriber_speeds(user, user.plan)
    return True, '', {'session_timeout': max(60, remaining) if remaining is not None else None,
                      'upload': up, 'download': down}


@app.route('/api/gateway/config')
@portal_api
def api_gateway_config():
    t = g.api_tenant
    hotspot = _hotspot_settings(t)
    cfg = portal_config(t)
    return jsonify(tenant=t.slug, hotspot_name=hotspot['name'], support=hotspot['support'],
                   terms=hotspot['terms'], currency=hotspot['currency'], acct_interim_seconds=60,
                   block_tethering=t.block_tethering,
                   gateway=g.api_gateway.name if g.api_gateway else None,
                   portal={k: cfg.get(k) for k in ('color', 'style', 'title', 'message', 'language',
                                                   'show_voucher', 'show_packages', 'logo_version')})


@app.route('/api/gateway/logo')
@portal_api
def api_gateway_logo():
    return _logo_response(g.api_tenant)


@app.route('/api/gateway/auth', methods=['POST'])
@portal_api
def api_gateway_auth():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()[:64]
    password = str(data.get('password', ''))[:128]
    if not username:
        return jsonify(ok=False, message='Enter your voucher code.')
    ok, message, info = _gateway_authenticate(g.api_tenant, username, password, str(data.get('mac') or '')[:17])
    _log_auth(username, ok)
    db.session.commit()
    return jsonify(ok=ok, message=message, **(info or {}))


def _acct_nas_ip():
    ip = (request.remote_addr or '')
    return ip if len(ip) <= 15 else '0.0.0.0'


@app.route('/api/gateway/sessions/check', methods=['POST'])
@portal_api
def api_gateway_sessions_check():
    """{"usernames": [...]} of guests online at the gateway -> {"disconnect": [...]}:
    deleted, disabled or expired users/vouchers, suspended tenant, or kicked by an admin."""
    names = [str(n)[:64] for n in (request.get_json(silent=True) or {}).get('usernames') or []][:1000]
    tenant = g.api_tenant
    if not names:
        return jsonify(disconnect=[])
    if tenant_blocked(tenant):
        return jsonify(disconnect=names)
    now = datetime.utcnow()
    vouchers = {v.code: v for v in Voucher.query.filter(Voucher.tenant_id == tenant.id, Voucher.code.in_(names))}
    users = {u.username: u for u in RadUser.query.filter(RadUser.tenant_id == tenant.id, RadUser.username.in_(names))}
    kicks = SessionKick.query.filter(SessionKick.tenant_id == tenant.id, SessionKick.username.in_(names),
                                     SessionKick.consumed_at.is_(None)).all()
    kicked = {k.username for k in kicks}
    for k in kicks:
        k.consumed_at = now
    db.session.commit()
    out = []
    for n in names:
        v, u = vouchers.get(n), users.get(n)
        if n in kicked:
            out.append(n)
        elif v:
            if v.status == 'disabled' or (v.expires_at and v.expires_at <= now):
                out.append(n)
        elif u:
            if not u.is_active or (u.expires_at and u.expires_at <= now):
                out.append(n)
        else:
            out.append(n)          # deleted
    return jsonify(disconnect=out)


@app.route('/api/gateway/accounting', methods=['POST'])
@portal_api
def api_gateway_accounting():
    """Batch of session events: {"events": [{"type": "start|interim|stop", "session_id",
    "username", "mac", "ip", "input_octets", "output_octets", "session_time",
    "terminate_cause", "time"}]}. input = uploaded by the guest, output = downloaded."""
    events = (request.get_json(silent=True) or {}).get('events') or []
    owned = {n for (n,) in db.session.execute(tenant_usernames(g.api_tenant.id))}
    groups = dict(db.session.query(RadUserGroup.username, RadUserGroup.groupname).filter(
        RadUserGroup.username.in_({str(e.get('username', ''))[:64] for e in events[:500]})).all()) if events else {}
    where = (g.api_gateway.name if g.api_gateway else 'gateway')[:50]
    stored = 0
    for e in events[:500]:
        username = str(e.get('username', ''))[:64]
        sid = str(e.get('session_id', ''))[:64]
        kind = e.get('type')
        if username not in owned or not sid or kind not in ('start', 'interim', 'stop'):
            continue
        try:
            at = datetime.utcfromtimestamp(int(e.get('time') or time.time()))
        except (TypeError, ValueError, OverflowError):
            at = datetime.utcnow()
        uid = hashlib.md5(f'{g.api_tenant.id}:{where}:{sid}'.encode()).hexdigest()
        row = RadAcct.query.filter_by(acctuniqueid=uid).first()
        if row is None:
            seconds = int(e.get('session_time') or 0)
            row = RadAcct(acctsessionid=sid, acctuniqueid=uid, username=username, nasipaddress=_acct_nas_ip(),
                          groupname=groups.get(username, ''), acctterminatecause='',
                          calledstationid=where, callingstationid=str(e.get('mac', '')).upper().replace(':', '-')[:50],
                          framedipaddress=str(e.get('ip') or '')[:15], nasporttype='Wireless-802.11',
                          acctstarttime=at - timedelta(seconds=seconds) if kind != 'start' else at,
                          acctsessiontime=0, acctinputoctets=0, acctoutputoctets=0)
            db.session.add(row)
        if kind != 'start':
            row.acctupdatetime = at
            row.acctsessiontime = int(e.get('session_time') or 0)
            row.acctinputoctets = int(e.get('input_octets') or 0)
            row.acctoutputoctets = int(e.get('output_octets') or 0)
        else:
            row.acctupdatetime = at
        if kind == 'stop':
            row.acctstoptime = at
            row.acctterminatecause = str(e.get('terminate_cause') or 'User-Request')[:32]
        stored += 1
    db.session.commit()
    return jsonify(stored=stored)


@app.route('/api/clickpesa/webhook', methods=['POST'])
def clickpesa_webhook():
    """ClickPesa PAYMENT RECEIVED / PAYMENT FAILED. The payload is only a hint:
    the payment is re-checked with ClickPesa before anything is granted."""
    data = (request.get_json(silent=True) or {}).get('data') or {}
    reference = str(data.get('orderReference', ''))[:20]
    if reference and re.fullmatch(r'[A-Za-z0-9]+', reference):
        try:
            if reference.startswith('SB'):
                _refresh_subscription(reference, force=True)
            else:
                _refresh_payment(reference, force=True)
        except Exception:
            db.session.rollback()
            log.exception('webhook refresh %s failed', reference)
    return jsonify(received=True)


# Live activity (polled by templates/live.html)
LIVE_STALE_MINUTES = 15   # open sessions with no accounting update for this long are not "online"


def _local_midnight_utc():
    """Start of today in the server's timezone (TZ env), as naive UTC."""
    now_local = datetime.now()
    offset = now_local - datetime.utcnow()
    return now_local.replace(hour=0, minute=0, second=0, microsecond=0) - offset


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


@app.route('/live')
@login_required
def live():
    return render_template('live.html', currency=current_tenant().currency)


@app.route('/live/disconnect', methods=['POST'])
@login_required
def live_disconnect():
    _check_csrf()
    username = (request.form.get('username') or '')[:64]
    owned = {n for (n,) in db.session.execute(tenant_usernames())}
    if username not in owned:
        abort(404)
    sent = disconnect_subscriber(tenant_id(), username)
    db.session.commit()
    return jsonify(ok=True, routers=sent)


@app.route('/api/live')
@login_required
def api_live():
    now = datetime.utcnow()
    midnight = _local_midnight_utc()
    cutoff = now - timedelta(minutes=LIVE_STALE_MINUTES)
    last_seen = func.coalesce(RadAcct.acctupdatetime, RadAcct.acctstarttime)

    tid = tenant_id()
    names = tenant_usernames(tid)
    open_sessions = (RadAcct.query
                     .filter(RadAcct.username.in_(names), RadAcct.acctstoptime.is_(None), last_seen >= cutoff)
                     .order_by(RadAcct.acctstarttime.desc()).limit(200).all())
    usernames = {s.username for s in open_sessions}
    vouchers = {v.code: v for v in scoped(Voucher).filter(Voucher.code.in_(usernames))} if usernames else {}
    phones = {}
    if vouchers:
        ids = [v.id for v in vouchers.values()]
        phones = {p.voucher_id: p.phone for p in Payment.query.filter(Payment.voucher_id.in_(ids))}
    nas_names = {n.nasname: n.shortname for n in scoped(Nas).all()}

    online = []
    for s in open_sessions:
        v = vouchers.get(s.username)
        down = s.acctoutputoctets or 0   # to the user
        up = s.acctinputoctets or 0      # from the user
        online.append({
            'user': s.username,
            'kind': 'voucher' if v else 'user',
            'plan': (v.plan.name if v and v.plan else s.groupname) or '',
            'phone': phones.get(v.id) if v else None,
            'expires': _iso(v.expires_at) if v else None,
            'mac': s.callingstationid or '',
            'ip': s.framedipaddress or '',
            'router': s.calledstationid or nas_names.get(s.nasipaddress) or s.nasipaddress,
            'started': _iso(s.acctstarttime),
            'updated': _iso(s.acctupdatetime or s.acctstarttime),
            'seconds': s.acctsessiontime or 0,
            'down': down,
            'up': up,
        })

    day_sessions = RadAcct.query.filter(RadAcct.username.in_(names),
                                        or_(RadAcct.acctstoptime.is_(None), RadAcct.acctstoptime >= midnight))
    usage = day_sessions.with_entities(
        func.coalesce(func.sum(RadAcct.acctoutputoctets), 0),
        func.coalesce(func.sum(RadAcct.acctinputoctets), 0)).one()
    paid_today = scoped(Payment).filter(Payment.status == 'paid', Payment.paid_at >= midnight)
    cash_today = scoped(Voucher).filter(Voucher.first_used_at >= midnight, Voucher.batch != 'online-payments')
    stats = {
        'online': len(online),
        'down_today': int(usage[0]),
        'up_today': int(usage[1]),
        'logins_today': RadPostAuth.query.filter(RadPostAuth.username.in_(names), RadPostAuth.authdate >= midnight,
                                                 RadPostAuth.reply == 'Access-Accept').count(),
        'rejects_today': RadPostAuth.query.filter(RadPostAuth.username.in_(names), RadPostAuth.authdate >= midnight,
                                                  RadPostAuth.reply != 'Access-Accept').count(),
        'online_revenue_today': float(paid_today.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar()),
        'online_sales_today': paid_today.count(),
        'cash_revenue_today': float(cash_today.with_entities(func.coalesce(func.sum(Voucher.price), 0)).scalar()),
        'vouchers_activated_today': scoped(Voucher).filter(Voucher.first_used_at >= midnight).count(),
        'pending_payments': scoped(Payment).filter_by(status='pending').count(),
    }

    events = []
    for a in RadPostAuth.query.filter(RadPostAuth.username.in_(names)).order_by(RadPostAuth.id.desc()).limit(30):
        ok = a.reply == 'Access-Accept'
        events.append({'at': _iso(a.authdate), 'type': 'login' if ok else 'reject',
                       'text': f'{a.username} {"logged in" if ok else "was rejected"}'})
    for s in RadAcct.query.filter(RadAcct.username.in_(names)).order_by(RadAcct.radacctid.desc()).limit(30):
        events.append({'at': _iso(s.acctstarttime), 'type': 'start',
                       'text': f'{s.username} started a session on {s.calledstationid or s.nasipaddress}'})
        if s.acctstoptime:
            events.append({'at': _iso(s.acctstoptime), 'type': 'stop',
                           'text': f'{s.username} disconnected ({s.acctterminatecause or "stop"})'})
    for p in scoped(Payment).order_by(Payment.id.desc()).limit(20):
        amount = f'{p.currency} {p.amount:,.0f}'
        events.append({'at': _iso(p.created_at), 'type': 'payment',
                       'text': f'{p.phone} requested {p.package_name} ({amount})'})
        if p.status == 'paid' and p.paid_at:
            events.append({'at': _iso(p.paid_at), 'type': 'paid',
                           'text': f'{p.phone} paid {amount} for {p.package_name}'})
        elif p.status in ('failed', 'review'):
            events.append({'at': _iso(p.updated_at), 'type': 'failed',
                           'text': f'{p.phone} payment {p.status}: {p.message or ""}'.strip()})
    events = sorted((e for e in events if e['at']), key=lambda e: e['at'], reverse=True)[:40]

    return jsonify(now=_iso(now), stats=stats, online=online, events=events,
                   stale_minutes=LIVE_STALE_MINUTES)


# ---------------------------------------------------------------------------
# Accounts: signup, email verification, password reset
# ---------------------------------------------------------------------------
def _tokens(salt):
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt=salt)


def _link(endpoint, **values):
    """Absolute link for emails; also works outside a request (reminder thread, CLI)."""
    if not has_request_context():
        with app.test_request_context(base_url=Config.PUBLIC_URL or 'http://localhost'):
            return url_for(endpoint, _external=True, **values)
    if Config.PUBLIC_URL:
        return Config.PUBLIC_URL + url_for(endpoint, **values)
    return url_for(endpoint, _external=True, **values)


def _send_verification(admin):
    token = _tokens('verify-email').dumps({'id': admin.id, 'email': admin.email})
    return send_mail(admin.email, 'Confirm your SafeNet account',
                     f'Hi {admin.username},\n\nConfirm your email address to start using SafeNet:\n'
                     f'{_link("verify_email", token=token)}\n\nThe link expires in 3 days.\n')


def _unique_slug(name):
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40] or 'network'
    slug, n = base, 2
    while Tenant.query.filter_by(slug=slug).first():
        slug, n = f'{base}-{n}', n + 1
    return slug


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if not Config.SIGNUP_ENABLED:
        abort(404)
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = SignupForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if Admin.query.filter_by(username=form.username.data).first():
            form.username.errors.append('That username is taken.')
        elif Admin.query.filter(func.lower(Admin.email) == email).first():
            form.email.errors.append('An account with this email already exists. Log in or reset your password.')
        else:
            tenant = Tenant(name=form.business_name.data.strip(), slug=_unique_slug(form.business_name.data),
                            status='trial', phone=(form.phone.data or '').strip() or None,
                            trial_ends_at=datetime.utcnow() + timedelta(days=Config.TRIAL_DAYS))
            refresh_service_until(tenant)
            db.session.add(tenant)
            db.session.flush()
            owner = Admin(username=form.username.data, email=email, tenant_id=tenant.id, role='owner')
            owner.set_password(form.password.data)
            db.session.add(owner)
            db.session.commit()
            _send_verification(owner)
            return render_template('auth/verify_notice.html', email=email, form=EmailForm(email=email), new=True)
    return render_template('auth/signup.html', form=form, trial_days=Config.TRIAL_DAYS)


@app.route('/verify/<token>')
def verify_email(token):
    try:
        data = _tokens('verify-email').loads(token, max_age=3 * 86400)
    except SignatureExpired:
        flash('That confirmation link has expired. Log in to get a new one.', 'warning')
        return redirect(url_for('login'))
    except BadSignature:
        abort(404)
    admin = db.session.get(Admin, data.get('id'))
    if not admin or admin.email != data.get('email'):
        abort(404)
    if not admin.email_verified_at:
        admin.email_verified_at = datetime.utcnow()
        db.session.commit()
    flash('Email confirmed. You can log in now.', 'success')
    return redirect(url_for('login'))


@app.route('/verify/resend', methods=['POST'])
def resend_verification():
    form = EmailForm()
    if form.validate_on_submit():
        admin = Admin.query.filter(func.lower(Admin.email) == form.email.data.strip().lower()).first()
        if admin and not admin.email_verified_at:
            _send_verification(admin)
    flash('If that account is waiting for confirmation, we sent a new link.', 'info')
    return redirect(url_for('login'))


@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    form = EmailForm()
    if form.validate_on_submit():
        admin = Admin.query.filter(func.lower(Admin.email) == form.email.data.strip().lower()).first()
        if admin and admin.is_active:
            token = _tokens('reset-password').dumps({'id': admin.id, 'h': admin.password_hash[-16:]})
            send_mail(admin.email, 'Reset your SafeNet password',
                      f'Hi {admin.username},\n\nReset your password here (valid for 1 hour):\n'
                      f'{_link("reset_password", token=token)}\n\nIf you did not ask for this, ignore this email.\n')
        flash('If an account uses that email, we sent a reset link.', 'info')
        return redirect(url_for('login'))
    return render_template('auth/forgot.html', form=form)


@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        data = _tokens('reset-password').loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash('That reset link is invalid or has expired.', 'warning')
        return redirect(url_for('forgot_password'))
    admin = db.session.get(Admin, data.get('id'))
    # The token embeds part of the old hash, so it stops working once used
    if not admin or admin.password_hash[-16:] != data.get('h'):
        flash('That reset link has already been used.', 'warning')
        return redirect(url_for('forgot_password'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        admin.set_password(form.password.data)
        admin.email_verified_at = admin.email_verified_at or datetime.utcnow()
        db.session.commit()
        flash('Password changed. You can log in now.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/reset.html', form=form)


# ---------------------------------------------------------------------------
# Tenant settings and team
# ---------------------------------------------------------------------------
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def tenant_settings():
    tenant = current_tenant()
    form = TenantSettingsForm(obj=tenant)
    if form.validate_on_submit():
        tenant.name = form.name.data.strip()
        tenant.phone = (form.phone.data or '').strip() or None
        tenant.hotspot_name = (form.hotspot_name.data or '').strip() or None
        tenant.support_phone = (form.support_phone.data or '').strip() or None
        tenant.currency = form.currency.data.strip().upper()
        tenant.terms = (form.terms.data or '').strip() or None
        tenant.block_tethering = form.block_tethering.data
        db.session.commit()
        flash('Settings saved.', 'success')
        return redirect(url_for('tenant_settings'))
    return render_template('settings.html', form=form)


def _manageable(member):
    """Can the current admin change this team member?"""
    if member.id == current_user.id or member.is_superadmin:
        return False
    if current_user.is_superadmin or current_user.role == 'owner':
        return member.role != 'owner'
    return member.role == 'staff'


@app.route('/team')
@login_required
@role_required('admin')
def team():
    members = scoped(Admin).order_by(Admin.created_at).all()
    return render_template('team/list.html', members=members, manageable=_manageable)


@app.route('/team/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def add_team_member():
    form = TeamMemberForm()
    if not (current_user.is_superadmin or current_user.role == 'owner'):
        form.role.choices = [c for c in form.role.choices if c[0] == 'staff']
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if Admin.query.filter_by(username=form.username.data).first():
            form.username.errors.append('That username is taken.')
        elif Admin.query.filter(func.lower(Admin.email) == email).first():
            form.email.errors.append('That email already has an account.')
        else:
            member = Admin(username=form.username.data, email=email, tenant_id=tenant_id(),
                           role=form.role.data, email_verified_at=datetime.utcnow())
            member.set_password(form.password.data)
            db.session.add(member)
            db.session.commit()
            send_mail(email, f'You were added to {current_tenant().name} on SafeNet',
                      f'Hi {member.username},\n\n{current_user.username} added you to {current_tenant().name}.\n'
                      f'Log in at {_link("login")} with username "{member.username}" and the temporary '
                      f'password they gave you, then change it with "Forgot password".\n')
            flash(f'{member.username} added as {member.role}.', 'success')
            return redirect(url_for('team'))
    return render_template('team/form.html', form=form)


@app.route('/team/<int:member_id>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def toggle_team_member(member_id):
    _check_csrf()
    member = owned_or_404(Admin, member_id)
    if not _manageable(member):
        abort(403)
    member.is_active = not member.is_active
    db.session.commit()
    flash(f'{member.username} {"enabled" if member.is_active else "disabled"}.', 'success')
    return redirect(url_for('team'))


@app.route('/team/<int:member_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_team_member(member_id):
    _check_csrf()
    member = owned_or_404(Admin, member_id)
    if not _manageable(member):
        abort(403)
    name = member.username
    db.session.delete(member)
    db.session.commit()
    flash(f'{name} removed from the team.', 'success')
    return redirect(url_for('team'))


# ---------------------------------------------------------------------------
# Gateways (SafeNet gateway boxes, authenticated by API key)
# ---------------------------------------------------------------------------
@app.route('/gateways')
@login_required
@role_required('admin')
def gateways():
    items = scoped(Gateway).order_by(Gateway.created_at.desc()).all()
    return render_template('gateways/list.html', gateways=items, form=GatewayForm(), now=datetime.utcnow())


@app.route('/gateways/add', methods=['POST'])
@login_required
@role_required('admin')
def add_gateway():
    form = GatewayForm()
    if _plan_limit_reached(current_tenant(), 'gateways'):
        flash('Your plan does not allow more gateways. Upgrade on the Billing page.', 'warning')
        return redirect(url_for('gateways'))
    if not form.validate_on_submit():
        flash('Give the gateway a name.', 'danger')
        return redirect(url_for('gateways'))
    key = 'sgw_' + secrets.token_urlsafe(32)
    gw = Gateway(tenant_id=tenant_id(), name=form.name.data.strip(), key_prefix=key[:8], key_hash=_hash_key(key))
    db.session.add(gw)
    db.session.commit()
    # The key is shown once and never stored in plain text
    return render_template('gateways/created.html', gateway=gw, key=key,
                           api_url=Config.PUBLIC_URL or request.host_url.rstrip('/'))


@app.route('/gateways/<int:gateway_id>/revoke', methods=['POST'])
@login_required
@role_required('admin')
def revoke_gateway(gateway_id):
    _check_csrf()
    gw = owned_or_404(Gateway, gateway_id)
    gw.is_active = False
    db.session.commit()
    flash(f'Gateway "{gw.name}" disabled. Its key no longer works.', 'success')
    return redirect(url_for('gateways'))


@app.route('/gateways/<int:gateway_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_gateway(gateway_id):
    _check_csrf()
    gw = owned_or_404(Gateway, gateway_id)
    name = gw.name
    db.session.delete(gw)
    db.session.commit()
    flash(f'Gateway "{name}" deleted.', 'success')
    return redirect(url_for('gateways'))


# ---------------------------------------------------------------------------
# Platform (super-admin)
# ---------------------------------------------------------------------------
@app.route('/platform/tenants')
@login_required
@superadmin_required
def platform_tenants():
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    count = lambda model: dict(db.session.query(model.tenant_id, func.count()).group_by(model.tenant_id).all())
    revenue = dict(db.session.query(Payment.tenant_id, func.coalesce(func.sum(Payment.amount), 0))
                   .filter(Payment.status == 'paid').group_by(Payment.tenant_id).all())
    owners = {a.tenant_id: a for a in Admin.query.filter_by(role='owner').order_by(Admin.id.desc())}
    return render_template('platform/tenants.html', tenants=tenants, users=count(RadUser),
                           vouchers=count(Voucher), gateways=count(Gateway), nas=count(Nas),
                           revenue=revenue, owners=owners, now=datetime.utcnow(),
                           default_fee=Config.PLATFORM_FEE_PERCENT, balances={t.id: tenant_balance(t.id)[0] for t in tenants},
                           billing_of=billing_state)


@app.route('/platform/tenants/<int:tid>/status', methods=['POST'])
@login_required
@superadmin_required
def platform_tenant_status(tid):
    _check_csrf()
    tenant = db.get_or_404(Tenant, tid)
    action = request.form.get('action')
    if action in ('activate', 'comp'):            # complimentary: no end date
        tenant.status, tenant.paid_until = 'active', None
        refresh_service_until(tenant)
    elif action == 'resume':                      # lift a suspension, keep dates
        tenant.status = 'active' if tenant.paid_until else 'trial'
        refresh_service_until(tenant)
    elif action == 'add_month':                   # e.g. paid in cash
        start, end = extend_subscription(tenant, 1)
        db.session.add(SubscriptionPayment(tenant_id=tenant.id, plan_name=tenant.billing_plan.name if tenant.billing_plan else None,
                                           months=1, amount=tenant.billing_plan.price if tenant.billing_plan else 0,
                                           method='manual', status='paid', reference='SBM' + secrets.token_hex(5).upper(),
                                           period_start=start, period_end=end, paid_at=datetime.utcnow(),
                                           created_by_id=current_user.id))
    elif action == 'suspend':
        if tenant.slug == migrations.DEFAULT_TENANT_SLUG:
            abort(400)
        tenant.status = 'suspended'
        names = {n for (n,) in db.session.execute(tenant_usernames(tenant.id))}
        for (name,) in db.session.query(RadAcct.username).filter(RadAcct.username.in_(names),
                                                                  RadAcct.acctstoptime.is_(None)).distinct():
            disconnect_subscriber(tenant.id, name)
    elif action == 'extend':
        base = max(tenant.trial_ends_at or datetime.utcnow(), datetime.utcnow())
        tenant.status, tenant.trial_ends_at, tenant.paid_until = 'trial', base + timedelta(days=Config.TRIAL_DAYS), None
        refresh_service_until(tenant)
    elif action == 'verify':
        for a in Admin.query.filter_by(tenant_id=tenant.id, email_verified_at=None):
            a.email_verified_at = datetime.utcnow()
    else:
        abort(400)
    db.session.commit()
    flash(f'{tenant.name}: {action} done.', 'success')
    return redirect(url_for('platform_tenants'))


@app.route('/platform/switch/<int:tid>', methods=['POST'])
@login_required
@superadmin_required
def platform_switch(tid):
    _check_csrf()
    tenant = db.get_or_404(Tenant, tid)
    session['tenant_id'] = tenant.id
    flash(f'You are now managing {tenant.name}.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/platform/switch-back', methods=['POST'])
@login_required
@superadmin_required
def platform_switch_back():
    _check_csrf()
    session.pop('tenant_id', None)
    return redirect(url_for('platform_tenants'))


# ---------------------------------------------------------------------------
# Earnings, payment settings and withdrawals (phase 3)
# ---------------------------------------------------------------------------
@app.route('/earnings')
@login_required
@role_required('admin')
def earnings():
    tenant = current_tenant()
    tid = tenant.id
    paid = scoped(Payment).filter(Payment.status == 'paid')
    total = lambda col, q=paid: Decimal(str(q.with_entities(func.coalesce(func.sum(col), 0)).scalar()))
    platform_paid = paid.filter(Payment.provider_account == 'platform')
    balance, earned, withdrawn = tenant_balance(tid)
    stats = {
        'gross': total(Payment.amount),
        'own_gross': total(Payment.amount, paid.filter(Payment.provider_account == 'own')),
        'platform_gross': total(Payment.amount, platform_paid),
        'fees': total(Payment.fee_amount, platform_paid),
        'earned': earned, 'withdrawn': withdrawn, 'balance': balance,
        'cash': Decimal(str(scoped(Voucher).filter(Voucher.first_used_at.isnot(None), Voucher.batch != 'online-payments')
                            .with_entities(func.coalesce(func.sum(Voucher.price), 0)).scalar())),
    }
    withdrawals = scoped(Withdrawal).order_by(Withdrawal.created_at.desc()).limit(50).all()
    form = WithdrawalForm(phone=tenant.phone or '')
    return render_template('earnings.html', stats=stats, withdrawals=withdrawals, form=form,
                           fee_percent=_fee_percent(tenant), min_withdrawal=Config.MIN_WITHDRAWAL,
                           can_withdraw=current_user.has_role('owner'))


@app.route('/earnings/withdraw', methods=['POST'])
@login_required
@role_required('owner')
def request_withdrawal():
    form = WithdrawalForm()
    if not form.validate_on_submit():
        flash(' '.join(e for errs in form.errors.values() for e in errs) or 'Check the form.', 'danger')
        return redirect(url_for('earnings'))
    phone = _normalize_tz_phone(form.phone.data)
    if not phone:
        flash('Enter a valid mobile money number, e.g. 0712 345 678.', 'danger')
        return redirect(url_for('earnings'))
    tenant = Tenant.query.filter_by(id=tenant_id()).with_for_update().one()   # one request at a time
    amount = Decimal(str(form.amount.data))
    balance, _, _ = tenant_balance(tenant.id)
    if amount < Config.MIN_WITHDRAWAL:
        db.session.rollback()
        flash(f'The minimum withdrawal is {tenant.currency} {Config.MIN_WITHDRAWAL:,}.', 'danger')
        return redirect(url_for('earnings'))
    if amount > balance:
        db.session.rollback()
        flash(f'You can withdraw up to {tenant.currency} {balance:,.0f}.', 'danger')
        return redirect(url_for('earnings'))
    w = Withdrawal(tenant_id=tenant.id, amount=amount, phone=phone, account_name=(form.account_name.data or '').strip() or None,
                   requested_by_id=current_user.id)
    db.session.add(w)
    db.session.commit()
    for admin in Admin.query.filter_by(is_superadmin=True, is_active=True):
        send_mail(admin.email, f'Withdrawal request: {tenant.name} {tenant.currency} {amount:,.0f}',
                  f'{tenant.name} asked to withdraw {tenant.currency} {amount:,.0f} to {phone}'
                  f'{" (" + w.account_name + ")" if w.account_name else ""}.\n\nProcess it at {_link("platform_payouts")}\n')
    flash(f'Withdrawal of {tenant.currency} {amount:,.0f} requested. You will get an email when it is paid.', 'success')
    return redirect(url_for('earnings'))


@app.route('/settings/payments', methods=['GET', 'POST'])
@login_required
@role_required('owner')
def payment_settings():
    tenant = current_tenant()
    form = PaymentSettingsForm(payment_mode=tenant.payment_mode, client_id=tenant.clickpesa_client_id)
    if form.validate_on_submit():
        mode = form.payment_mode.data
        if form.client_id.data is not None:
            tenant.clickpesa_client_id = form.client_id.data.strip() or None
        if form.api_key.data:
            tenant.clickpesa_api_key_enc = secretbox.encrypt(form.api_key.data.strip())
        if form.checksum_key.data:
            tenant.clickpesa_checksum_key_enc = secretbox.encrypt(form.checksum_key.data.strip())
        if form.clear_checksum.data:
            tenant.clickpesa_checksum_key_enc = None
        if mode == 'own' and not clickpesa.is_configured(_own_credentials(tenant)):
            db.session.rollback()
            flash('Enter your ClickPesa Client ID and API key to receive payments directly.', 'danger')
            return redirect(url_for('payment_settings'))
        tenant.payment_mode = mode
        db.session.commit()
        flash('Payment settings saved.', 'success')
        return redirect(url_for('payment_settings'))
    return render_template('payment_settings.html', form=form, has_api_key=bool(tenant.clickpesa_api_key_enc),
                           has_checksum=bool(tenant.clickpesa_checksum_key_enc), fee_percent=_fee_percent(tenant),
                           webhook_url=_link('clickpesa_webhook'), platform_ready=clickpesa.is_configured())


@app.route('/settings/payments/test', methods=['POST'])
@login_required
@role_required('owner')
def test_payment_settings():
    _check_csrf()
    tenant = current_tenant()
    creds = _own_credentials(tenant)
    if not clickpesa.is_configured(creds):
        flash('Save your ClickPesa Client ID and API key first.', 'warning')
    else:
        try:
            clickpesa.test_credentials(creds)
            flash('ClickPesa accepted your keys.', 'success')
        except clickpesa.ClickPesaError as e:
            flash(f'ClickPesa rejected the keys: {e}', 'danger')
    return redirect(url_for('payment_settings'))


@app.route('/platform/payouts')
@login_required
@superadmin_required
def platform_payouts():
    status = request.args.get('status', 'requested')
    query = Withdrawal.query
    if status:
        query = query.filter_by(status=status)
    items = query.order_by(Withdrawal.created_at.desc()).limit(200).all()
    fees = db.session.query(func.coalesce(func.sum(Payment.fee_amount), 0)).filter(
        Payment.status == 'paid', Payment.provider_account == 'platform').scalar()
    owed = {t.id: tenant_balance(t.id)[0] for t in Tenant.query.all()}
    return render_template('platform/payouts.html', withdrawals=items, status=status, fees=fees,
                           owed=owed, tenants=Tenant.query.all())


@app.route('/platform/payouts/<int:wid>', methods=['POST'])
@login_required
@superadmin_required
def process_payout(wid):
    _check_csrf()
    w = Withdrawal.query.filter_by(id=wid).with_for_update().first_or_404()
    if w.status != 'requested':
        flash('This withdrawal was already processed.', 'warning')
        return redirect(url_for('platform_payouts'))
    action = request.form.get('action')
    reference = (request.form.get('reference') or '').strip()[:64]
    note = (request.form.get('note') or '').strip()[:255]
    if action == 'paid':
        if not reference:
            db.session.rollback()
            flash('Enter the payout transaction reference.', 'danger')
            return redirect(url_for('platform_payouts'))
        w.status, w.reference = 'paid', reference
    elif action == 'reject':
        w.status = 'rejected'
    else:
        abort(400)
    w.note = note or None
    w.processed_by_id, w.processed_at = current_user.id, datetime.utcnow()
    db.session.commit()
    owner = Admin.query.filter_by(tenant_id=w.tenant_id, role='owner').first()
    if owner:
        body = (f'Your withdrawal of {w.tenant.currency} {w.amount:,.0f} to {w.phone} was sent. Reference: {reference}.\n'
                if w.status == 'paid' else
                f'Your withdrawal of {w.tenant.currency} {w.amount:,.0f} was not approved{": " + note if note else ""}. '
                f'The amount is back in your balance.\n')
        send_mail(owner.email, f'Withdrawal {w.status}', body)
    if w.status == 'paid':
        send_sms_async(w.phone, f'SafeNet: {w.tenant.currency} {w.amount:,.0f} has been sent to this number. Ref {reference}.')
    else:
        send_sms_async(_normalize_tz_phone(w.tenant.phone or ''), f'SafeNet: your withdrawal of {w.tenant.currency} '
                       f'{w.amount:,.0f} was not approved{": " + note if note else ""}. It is back in your balance.')
    flash(f'Withdrawal marked {w.status}.', 'success')
    return redirect(url_for('platform_payouts'))


@app.route('/platform/tenants/<int:tid>/fee', methods=['POST'])
@login_required
@superadmin_required
def platform_tenant_fee(tid):
    _check_csrf()
    tenant = db.get_or_404(Tenant, tid)
    raw = (request.form.get('fee_percent') or '').strip()
    try:
        tenant.fee_percent = None if raw == '' else Decimal(raw)
        if tenant.fee_percent is not None and not (0 <= tenant.fee_percent <= 50):
            raise ValueError
    except (ArithmeticError, ValueError):
        flash('Enter a fee between 0 and 50 %, or leave it empty for the default.', 'danger')
        return redirect(url_for('platform_tenants'))
    db.session.commit()
    flash(f'{tenant.name}: platform fee set to {_fee_percent(tenant)} %.', 'success')
    return redirect(url_for('platform_tenants'))


# ---------------------------------------------------------------------------
# Routers over the WireGuard VPN (phase 4)
# ---------------------------------------------------------------------------
ROUTER_VENDORS = [('mikrotik', 'MikroTik (RouterOS 7)'), ('other', 'Other WireGuard-capable router')]


def _wg_keypair():
    key = X25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(private).decode(), base64.b64encode(public).decode()


def _next_tunnel_ip():
    net = ipaddress.ip_network(Config.WG_SUBNET)
    used = {r for (r,) in db.session.query(Router.tunnel_ip)} | {Config.WG_SERVER_IP}
    used |= {n for (n,) in db.session.query(Nas.nasname)}
    first = int(net.network_address) + 256          # x.x.0.* is kept for the hub
    for value in range(first, int(net.broadcast_address)):
        ip = str(ipaddress.ip_address(value))
        if ip not in used and not ip.endswith(('.0', '.255')):
            return ip
    raise RuntimeError('VPN address space is full')


def _router_online(router):
    return bool(router.last_handshake_at and (datetime.utcnow() - router.last_handshake_at).total_seconds() < 180)


@app.route('/routers')
@login_required
@role_required('admin')
def routers():
    items = scoped(Router).order_by(Router.created_at.desc()).all()
    return render_template('routers/list.html', routers=items, vendors=ROUTER_VENDORS, online=_router_online,
                           hub=db.session.get(VpnServer, 1))


@app.route('/routers/add', methods=['POST'])
@login_required
@role_required('admin')
def add_router():
    _check_csrf()
    if _plan_limit_reached(current_tenant(), 'routers'):
        flash('Your plan does not allow more routers. Upgrade on the Billing page.', 'warning')
        return redirect(url_for('routers'))
    name = (request.form.get('name') or '').strip()[:64]
    vendor = request.form.get('vendor') if request.form.get('vendor') in dict(ROUTER_VENDORS) else 'mikrotik'
    if not name:
        flash('Give the router a name.', 'danger')
        return redirect(url_for('routers'))
    private, public = _wg_keypair()
    tunnel_ip = _next_tunnel_ip()
    nas = Nas(tenant_id=tenant_id(), nasname=tunnel_ip, shortname=re.sub(r'[^A-Za-z0-9_-]+', '-', name)[:32] or 'router',
              type='other', secret=secrets.token_urlsafe(18), vendor=vendor if vendor == 'mikrotik' else 'standard',
              description=f'VPN router: {name}', is_active=True)
    db.session.add(nas)
    db.session.flush()
    router = Router(tenant_id=tenant_id(), name=name, vendor=vendor, tunnel_ip=tunnel_ip, public_key=public,
                    private_key_enc=secretbox.encrypt(private), nas_id=nas.id)
    db.session.add(router)
    db.session.commit()
    flash(f'Router "{name}" added with VPN address {tunnel_ip}. Paste the setup script into the router.', 'success')
    return redirect(url_for('router_script', router_id=router.id))


@app.route('/routers/<int:router_id>/script')
@login_required
@role_required('admin')
def router_script(router_id):
    router = owned_or_404(Router, router_id)
    hub = db.session.get(VpnServer, 1)
    return render_template('routers/script.html', router=router, hub=hub, online=_router_online(router),
                           private_key=secretbox.decrypt(router.private_key_enc), config=Config)


@app.route('/routers/<int:router_id>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def toggle_router(router_id):
    _check_csrf()
    router = owned_or_404(Router, router_id)
    router.is_active = not router.is_active
    if router.nas:
        router.nas.is_active = router.is_active
    db.session.commit()
    flash(f'Router "{router.name}" {"enabled" if router.is_active else "disconnected from the VPN"}.', 'success')
    return redirect(url_for('routers'))


@app.route('/routers/<int:router_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_router(router_id):
    _check_csrf()
    router = owned_or_404(Router, router_id)
    name = router.name
    if router.nas:
        db.session.delete(router.nas)
    db.session.delete(router)
    db.session.commit()
    flash(f'Router "{name}" removed.', 'success')
    return redirect(url_for('routers'))


# ---------------------------------------------------------------------------
# Subscription billing (tenants pay the platform)
# ---------------------------------------------------------------------------
BILLING_MONTHS = (1, 3, 6, 12)
DAYS_PER_MONTH = 30


def refresh_service_until(tenant):
    """Guests keep service until the trial / paid period ends, plus the grace days."""
    end = tenant.paid_until or (tenant.trial_ends_at if tenant.status == 'trial' else None)
    tenant.service_until = end + timedelta(days=Config.BILLING_GRACE_DAYS) if end else None


def billing_state(tenant, now=None):
    """{'state': trial|active|grace|expired|suspended|complimentary, 'end', 'days_left', 'service_until'}"""
    now = now or datetime.utcnow()
    end = tenant.paid_until or (tenant.trial_ends_at if tenant.status == 'trial' else None)
    if tenant.status == 'suspended':
        state = 'suspended'
    elif end is None:
        state = 'complimentary' if tenant.status == 'active' else 'trial'
    elif now < end:
        state = 'active' if tenant.paid_until else 'trial'
    elif tenant.service_until and now < tenant.service_until:
        state = 'grace'
    else:
        state = 'expired'
    days_left = max(0, math.ceil((end - now).total_seconds() / 86400)) if end else None
    return {'state': state, 'end': end, 'days_left': days_left, 'service_until': tenant.service_until,
            'plan': tenant.billing_plan}


def extend_subscription(tenant, months, plan=None):
    """Add paid months after today or the current paid period, whichever is later. Caller commits."""
    now = datetime.utcnow()
    start = max(now, tenant.paid_until or now)
    tenant.paid_until = start + timedelta(days=DAYS_PER_MONTH * months)
    tenant.status = 'active'
    tenant.billing_notice = None
    if plan:
        tenant.billing_plan_id = plan.id
    refresh_service_until(tenant)
    return start, tenant.paid_until


def _plan_limit_reached(tenant, kind):
    plan = tenant.billing_plan
    limit = getattr(plan, f'max_{kind}', None) if plan else None
    if limit is None:
        return False
    model = Router if kind == 'routers' else Gateway
    return model.query.filter_by(tenant_id=tenant.id).count() >= limit


def _fulfil_subscription(sp):
    if sp.status == 'paid':
        return
    sp.period_start, sp.period_end = extend_subscription(sp.tenant, sp.months, sp.billing_plan)
    sp.status, sp.paid_at = 'paid', datetime.utcnow()
    owner = Admin.query.filter_by(tenant_id=sp.tenant_id, role='owner').first()
    if owner:
        send_mail(owner.email, 'SafeNet subscription renewed',
                  f'Thank you! We received {sp.currency} {sp.amount:,.0f} for {sp.months} month(s) of '
                  f'{sp.plan_name or "SafeNet"}.\nYour service is paid until {sp.period_end:%d %b %Y}.\nReference: {sp.reference}\n')
    send_sms_async(sp.phone, f'SafeNet: we received {sp.currency} {sp.amount:,.0f}. Your service is paid until '
                             f'{sp.period_end:%d %b %Y}. Ref {sp.reference}. Asante!', sp.reference)


def _refresh_subscription(reference, force=False):
    sp = SubscriptionPayment.query.filter_by(reference=reference).with_for_update().first()
    if not sp:
        db.session.rollback()
        return None
    now = datetime.utcnow()
    if sp.status == 'pending' and sp.method == 'clickpesa' and (
            force or not sp.checked_at or (now - sp.checked_at).total_seconds() >= 3):
        sp.checked_at = now
        try:
            record = clickpesa.query_payment(reference, clickpesa.platform_credentials())
        except clickpesa.ClickPesaError as e:
            log.warning('ClickPesa query %s failed: %s', reference, e)
            record = None
        if record:
            status = (record.get('status') or '').upper()
            sp.provider_status, sp.channel = status, record.get('channel') or sp.channel
            sp.message = (record.get('message') or sp.message or '')[:255] or None
            if status in ('SUCCESS', 'SETTLED'):
                collected = record.get('collectedAmount')
                if collected is not None and Decimal(str(collected)) < sp.amount:
                    sp.status, sp.message = 'review', f'Collected {collected}, expected {sp.amount}'
                else:
                    _fulfil_subscription(sp)
            elif status == 'FAILED':
                sp.status = 'failed'
    db.session.commit()
    return sp


@app.route('/billing')
@login_required
def billing():
    tenant = current_tenant()
    plans = BillingPlan.query.filter_by(is_active=True).order_by(BillingPlan.sort_order, BillingPlan.price).all()
    history = SubscriptionPayment.query.filter_by(tenant_id=tenant.id).order_by(SubscriptionPayment.id.desc()).limit(24).all()
    return render_template('billing.html', plans=plans, history=history, months=BILLING_MONTHS,
                           can_pay=current_user.has_role('owner'), grace=Config.BILLING_GRACE_DAYS,
                           payments_ready=clickpesa.is_configured(), state=billing_state(tenant),
                           default_phone=tenant.phone or '')


@app.route('/billing/pay', methods=['POST'])
@login_required
@role_required('owner')
def billing_pay():
    _check_csrf()
    tenant = current_tenant()
    plan = BillingPlan.query.filter_by(id=request.form.get('plan_id', type=int), is_active=True).first()
    months = request.form.get('months', type=int)
    phone = _normalize_tz_phone(request.form.get('phone', ''))
    if not plan or months not in BILLING_MONTHS:
        flash('Choose a plan and a period.', 'danger')
        return redirect(url_for('billing'))
    if not phone:
        flash('Enter a valid mobile money number, e.g. 0712 345 678.', 'danger')
        return redirect(url_for('billing'))
    problem = check_network(phone, None, plan.price * months)
    if problem:
        flash(problem, 'danger')
        return redirect(url_for('billing'))
    if not clickpesa.is_configured():
        flash('Online payment is not available right now. Please contact SafeNet.', 'danger')
        return redirect(url_for('billing'))
    sp = SubscriptionPayment(tenant_id=tenant.id, billing_plan_id=plan.id, plan_name=plan.name, months=months,
                             amount=plan.price * months, currency=plan.currency, phone=phone,
                             reference='SB' + secrets.token_hex(6).upper(), created_by_id=current_user.id)
    db.session.add(sp)
    db.session.commit()
    creds = clickpesa.platform_credentials()
    try:
        if not clickpesa.preview_ussd_push(sp.amount, phone, sp.reference, creds):
            raise clickpesa.ClickPesaError('No mobile-money method available for this number')
        tx = clickpesa.initiate_ussd_push(sp.amount, phone, sp.reference, creds) or {}
        sp.provider_id, sp.channel = tx.get('id'), tx.get('channel')
        sp.provider_status = (tx.get('status') or '').upper() or None
        if sp.provider_status == 'FAILED':
            sp.status = 'failed'
    except clickpesa.ClickPesaError as e:
        sp.status, sp.message = 'failed', str(e)[:255]
    db.session.commit()
    if sp.status == 'failed':
        flash(f"We couldn't send the payment request: {sp.message or 'try again'}.", 'danger')
        return redirect(url_for('billing'))
    return redirect(url_for('billing_payment', reference=sp.reference))


@app.route('/billing/payments/<reference>')
@login_required
def billing_payment(reference):
    sp = SubscriptionPayment.query.filter_by(reference=reference, tenant_id=tenant_id()).first_or_404()
    return render_template('billing_payment.html', sp=sp)


@app.route('/billing/payments/<reference>/status')
@login_required
def billing_payment_status(reference):
    if not SubscriptionPayment.query.filter_by(reference=reference, tenant_id=tenant_id()).first():
        abort(404)
    sp = _refresh_subscription(reference)
    return jsonify(status=sp.status, message=sp.message or '',
                   paid_until=sp.period_end.strftime('%d %b %Y') if sp.period_end else None)


def send_billing_reminders(now=None):
    """Email owners 3 days before their trial/subscription ends and when it has ended."""
    now = now or datetime.utcnow()
    sent = 0
    for tenant in Tenant.query.filter(Tenant.status.in_(('trial', 'active'))):
        state = billing_state(tenant, now)
        end = state['end']
        if not end:
            continue
        if state['state'] in ('grace', 'expired'):
            key, subject = f'exp:{end:%Y-%m-%d}', 'Your SafeNet subscription has ended'
            body = (f'Your SafeNet {"trial" if not tenant.paid_until else "subscription"} for {tenant.name} ended on '
                    f'{end:%d %b %Y}. Your Wi-Fi keeps working until {tenant.service_until:%d %b %Y}; renew before then '
                    f'at {_link("billing")} to avoid interruption.\n')
        elif end - now <= timedelta(days=3):
            key, subject = f'pre:{end:%Y-%m-%d}', 'Your SafeNet subscription ends soon'
            body = (f'Your SafeNet {"trial" if not tenant.paid_until else "subscription"} for {tenant.name} ends on '
                    f'{end:%d %b %Y}. Renew at {_link("billing")} to keep your Wi-Fi running.\n')
        else:
            continue
        if tenant.billing_notice == key:
            continue
        owner = Admin.query.filter_by(tenant_id=tenant.id, role='owner').first()
        if owner and send_mail(owner.email, subject, body):
            sent += 1
        send_sms_async(_normalize_tz_phone(tenant.phone or ''), f'SafeNet: {subject.replace("Your SafeNet", "your")}. '
                       f'Renew at {_link("billing")}')
        tenant.billing_notice = key
    db.session.commit()
    return sent


def _billing_reminder_loop():
    """Hourly; one gunicorn worker at a time (MariaDB named lock)."""
    while True:
        time.sleep(3600)
        with app.app_context():
            try:
                got = db.session.execute(text("SELECT GET_LOCK('safenet_billing', 0)")).scalar()
                if got:
                    try:
                        send_billing_reminders()
                    finally:
                        db.session.execute(text("SELECT RELEASE_LOCK('safenet_billing')"))
            except Exception:
                db.session.rollback()
                log.exception('billing reminders failed')


if Config.BILLING_REMINDERS and 'gunicorn' in os.path.basename(sys.argv[0]):
    threading.Thread(target=_billing_reminder_loop, daemon=True).start()


@app.route('/platform/billing', methods=['GET', 'POST'])
@login_required
@superadmin_required
def platform_billing():
    if request.method == 'POST':
        _check_csrf()
        plan = db.get_or_404(BillingPlan, request.form.get('id', type=int)) if request.form.get('id') else BillingPlan()
        try:
            plan.name = request.form['name'].strip()[:64]
            plan.description = (request.form.get('description') or '').strip()[:255] or None
            plan.price = Decimal(request.form['price'])
            plan.max_routers = request.form.get('max_routers', type=int)
            plan.max_gateways = request.form.get('max_gateways', type=int)
            plan.sort_order = request.form.get('sort_order', type=int) or 0
            plan.is_active = bool(request.form.get('is_active'))
            if not plan.name or plan.price < 0:
                raise ValueError
        except (KeyError, ValueError, ArithmeticError):
            db.session.rollback()
            flash('Enter a name and a valid monthly price.', 'danger')
            return redirect(url_for('platform_billing'))
        db.session.add(plan)
        db.session.commit()
        flash(f'Billing plan "{plan.name}" saved.', 'success')
        return redirect(url_for('platform_billing'))
    plans = BillingPlan.query.order_by(BillingPlan.sort_order, BillingPlan.price).all()
    payments = SubscriptionPayment.query.order_by(SubscriptionPayment.id.desc()).limit(100).all()
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    paid = SubscriptionPayment.query.filter_by(status='paid')
    total = lambda q: Decimal(str(q.with_entities(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).scalar()))
    return render_template('platform/billing.html', plans=plans, payments=payments,
                           revenue_month=total(paid.filter(SubscriptionPayment.paid_at >= month_start)),
                           revenue_all=total(paid), payments_ready=clickpesa.is_configured())


# Initialize database
@app.cli.command()
def init_db():
    """Initialize the database."""
    db.create_all()
    migrations.run()
    
    # Create default admin if not exists
    if not Admin.query.filter_by(username=Config.ADMIN_USERNAME).first():
        admin = Admin(
            username=Config.ADMIN_USERNAME,
            email=Config.ADMIN_EMAIL,
            tenant_id=migrations.default_tenant().id,
            role='owner',
            is_superadmin=True,
            email_verified_at=datetime.utcnow(),
        )
        admin.set_password(Config.ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()
        print(f'Admin user created: {Config.ADMIN_USERNAME}')
    
    print('Database initialized.')


@app.cli.command('create-admin')
@click.option('--username', '-u', prompt=True, help='Admin username')
@click.option('--password', '-p', prompt=True, hide_input=True, confirmation_prompt=True, help='Admin password')
@click.option('--email', '-e', prompt=True, help='Admin email')
@click.option('--force', is_flag=True, help='Update password/email if username already exists')
@click.option('--superadmin/--no-superadmin', default=True, help='Platform super-admin (default: yes)')
def create_admin(username, password, email, force, superadmin):
    """Create a platform admin in the default tenant (or reset password with --force)."""
    username = (username or '').strip()
    email = (email or '').strip()
    if not username or not password or not email:
        click.echo('username, password, and email are required', err=True)
        raise SystemExit(1)

    admin = Admin.query.filter_by(username=username).first()
    if admin and not force:
        click.echo(f'Admin "{username}" already exists. Use --force to update password/email.', err=True)
        raise SystemExit(1)

    if admin:
        admin.email = email
        admin.set_password(password)
        admin.is_active = True
        admin.email_verified_at = admin.email_verified_at or datetime.utcnow()
        db.session.commit()
        click.echo(f'Admin updated: {username}')
    else:
        # Email must be unique
        if Admin.query.filter_by(email=email).first():
            click.echo(f'Email "{email}" is already used by another admin.', err=True)
            raise SystemExit(1)
        admin = Admin(username=username, email=email, is_active=True, role='owner',
                      tenant_id=migrations.default_tenant().id, is_superadmin=superadmin,
                      email_verified_at=datetime.utcnow())
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f'Admin created: {username}')


@app.cli.command('billing-reminders')
def billing_reminders_command():
    """Send due trial/subscription reminder emails now."""
    click.echo(f'Sent {send_billing_reminders()} reminder(s).')


@app.cli.command('seed-users')
@click.option(
    '--file', '-f', 'path',
    type=click.Path(exists=True, dir_okay=False, readable=True),
    default=None,
    help='Path to a JSON file with users. If omitted, JSON is read from stdin.',
)
@click.option(
    '--update-password/--keep-password', default=True,
    help='Overwrite the password for users that already exist (default: update).',
)
@click.option(
    '--plan', default=None,
    help='Default plan name to assign to seeded users that do not specify "plan".',
)
@click.option('--tenant', 'tenant_slug', default=migrations.DEFAULT_TENANT_SLUG,
              help='Tenant (slug) that owns the users (default: the platform tenant).')
def seed_users(path, update_password, plan, tenant_slug):
    """Seed FreeRADIUS users from a JSON list.

    JSON format (stdin or --file):
        [
          {"username": "alice", "password": "s3cret"},
          {"username": "bob",   "password": "p@ss",  "plan": "Premium", "is_active": true}
        ]

    Examples (run inside the web container):
        docker compose exec -T web flask seed-users < users.json
        cat users.json | docker compose exec -T web flask seed-users
    """
    raw = open(path, 'r', encoding='utf-8').read() if path else sys.stdin.read()
    if not raw.strip():
        click.echo('No input received.', err=True)
        sys.exit(2)
    try:
        users = json.loads(raw)
    except json.JSONDecodeError as exc:
        click.echo(f'Invalid JSON: {exc}', err=True)
        sys.exit(2)
    if not isinstance(users, list):
        click.echo('Top-level JSON must be a list of user objects.', err=True)
        sys.exit(2)

    tenant = Tenant.query.filter_by(slug=tenant_slug).first()
    if not tenant:
        click.echo(f'Tenant "{tenant_slug}" not found.', err=True)
        sys.exit(2)

    created = updated = skipped = 0
    for idx, entry in enumerate(users, start=1):
        if not isinstance(entry, dict):
            click.echo(f'[{idx}] skipped: not an object', err=True)
            skipped += 1
            continue
        username = (entry.get('username') or '').strip()
        password = entry.get('password')
        if not username or not password:
            click.echo(f'[{idx}] skipped: missing username/password', err=True)
            skipped += 1
            continue
        is_active = bool(entry.get('is_active', True))
        plan_name = entry.get('plan', plan)

        plan_obj = None
        if plan_name:
            plan_obj = Plan.query.filter_by(tenant_id=tenant.id, name=plan_name).first()
            if not plan_obj:
                click.echo(
                    f'[{idx}] {username}: plan "{plan_name}" not found, '
                    'continuing without plan',
                    err=True,
                )

        user = RadUser.query.filter_by(username=username).first()
        if user is not None and user.tenant_id != tenant.id:
            click.echo(f'[{idx}] skipped: {username} belongs to another tenant', err=True)
            skipped += 1
            continue
        is_new = user is None
        if is_new:
            user = RadUser(username=username, is_active=is_active, tenant_id=tenant.id)
            if plan_obj is not None:
                user.plan_id = plan_obj.id
            db.session.add(user)
        else:
            user.is_active = is_active
            if plan_obj is not None:
                user.plan_id = plan_obj.id

        radcheck = RadCheck.query.filter_by(
            username=username, attribute='Cleartext-Password'
        ).first()
        if radcheck is None:
            db.session.add(RadCheck(
                username=username,
                attribute='Cleartext-Password',
                op=':=',
                value=password,
            ))
        elif update_password:
            radcheck.op = ':='
            radcheck.value = password

        if plan_obj is not None:
            existing = RadUserGroup.query.filter_by(
                username=username, groupname=plan_obj.group_name
            ).first()
            if existing is None:
                RadUserGroup.query.filter_by(username=username).delete()
                db.session.add(RadUserGroup(
                    username=username, groupname=plan_obj.group_name, priority=1
                ))

        if is_new:
            created += 1
        else:
            updated += 1

    db.session.commit()
    click.echo(
        f'Done. created={created} updated={updated} skipped={skipped} '
        f'total_input={len(users)}'
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

