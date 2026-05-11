from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
from config import Config
from models import db, Admin, Plan, PlanAttribute, RadUser, RadCheck, RadReply, RadUserGroup, RadGroupCheck, RadGroupReply, RadAcct, Nas, RadPostAuth
from forms import LoginForm, AdminForm, PlanForm, PlanAttributeForm, UserForm, NasForm, SearchForm
from sqlalchemy import func, or_, desc
import subprocess
import socket
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
    return {
        'app_name': 'SafeNet RADIUS Manager',
        'supported_vendors': Config.SUPPORTED_VENDORS,
    }


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
            
            admin.last_login = datetime.utcnow()
            db.session.commit()
            login_user(admin)
            
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('auth/login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# Dashboard
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    # Statistics
    total_users = RadUser.query.count()
    active_users = RadUser.query.filter_by(is_active=True).count()
    total_plans = Plan.query.count()
    total_nas = Nas.query.count()
    
    # Active sessions
    active_sessions = RadAcct.query.filter(RadAcct.acctstoptime.is_(None)).count()
    
    # Recent sessions
    recent_sessions = RadAcct.query.order_by(desc(RadAcct.acctstarttime)).limit(10).all()
    
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
    
    query = RadUser.query
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
    form.plan_id.choices = [(0, '-- No Plan --')] + [(p.id, p.name) for p in Plan.query.filter_by(is_active=True).all()]
    
    if form.validate_on_submit():
        # Check if username exists
        if RadUser.query.filter_by(username=form.username.data).first():
            flash('Username already exists.', 'danger')
            return render_template('users/form.html', form=form, title='Add User')
        
        # Create RadUser
        user = RadUser(
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
            plan = Plan.query.get(form.plan_id.data)
            if plan:
                # Create user-group mapping
                usergroup = RadUserGroup(
                    username=form.username.data,
                    groupname=plan.name,
                    priority=1
                )
                db.session.add(usergroup)
        
        db.session.commit()
        flash(f'User {form.username.data} created successfully.', 'success')
        return redirect(url_for('users'))
    
    # Get NAS list for testing (empty for new users - they need to be saved first)
    nas_list = Nas.query.filter_by(is_active=True).all()
    return render_template('users/form.html', form=form, nas_list=nas_list, title='Add User')


@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user = RadUser.query.get_or_404(user_id)
    form = UserForm(obj=user)
    form.plan_id.choices = [(0, '-- No Plan --')] + [(p.id, p.name) for p in Plan.query.filter_by(is_active=True).all()]
    
    # Convert data_cap from bytes to GB for display
    if user.data_cap:
        form.data_cap.data = int(user.data_cap / 1073741824)
    if user.data_cap_period:
        form.data_cap_period.data = user.data_cap_period
    
    # Get NAS list for testing
    nas_list = Nas.query.filter_by(is_active=True).all()
    
    if form.validate_on_submit():
        # Update RadUser
        user.plan_id = form.plan_id.data if form.plan_id.data > 0 else None
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
            plan = Plan.query.get(form.plan_id.data)
            if plan:
                usergroup = RadUserGroup(
                    username=user.username,
                    groupname=plan.name,
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
    user = RadUser.query.get_or_404(user_id)
    nas_id = request.json.get('nas_id') if request.is_json else request.form.get('nas_id', type=int)
    
    if not nas_id:
        if request.is_json:
            return jsonify({
                'success': False,
                'message': 'Please select a NAS device to test against'
            }), 400
        flash('Please select a NAS device to test against.', 'danger')
        return redirect(url_for('edit_user', user_id=user_id))
    
    nas = Nas.query.get_or_404(nas_id)
    
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
    user = RadUser.query.get_or_404(user_id)
    username = user.username
    
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
def plans():
    all_plans = Plan.query.order_by(Plan.created_at.desc()).all()
    return render_template('plans/list.html', plans=all_plans)


@app.route('/plans/add', methods=['GET', 'POST'])
@login_required
def add_plan():
    form = PlanForm()
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    if form.validate_on_submit():
        if Plan.query.filter_by(name=form.name.data).first():
            flash('Plan name already exists.', 'danger')
            return render_template('plans/form.html', form=form, title='Add Plan')
        
        plan = Plan(
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
        db.session.commit()
        
        flash(f'Plan {form.name.data} created successfully.', 'success')
        return redirect(url_for('edit_plan', plan_id=plan.id))
    
    return render_template('plans/form.html', form=form, title='Add Plan')


@app.route('/plans/edit/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def edit_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    form = PlanForm(obj=plan)
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    # Convert data_cap from bytes to GB for display
    if plan.data_cap:
        form.data_cap.data = int(plan.data_cap / 1073741824)
    if plan.data_cap_period:
        form.data_cap_period.data = plan.data_cap_period
    
    if form.validate_on_submit():
        plan.name = form.name.data
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
        
        db.session.commit()
        flash(f'Plan {plan.name} updated successfully.', 'success')
        return redirect(url_for('plans'))
    
    # Get attributes
    attributes = PlanAttribute.query.filter_by(plan_id=plan.id).order_by(PlanAttribute.priority).all()
    
    return render_template('plans/edit.html', form=form, plan=plan, attributes=attributes, title='Edit Plan')


@app.route('/plans/<int:plan_id>/attributes/add', methods=['GET', 'POST'])
@login_required
def add_plan_attribute(plan_id):
    plan = Plan.query.get_or_404(plan_id)
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
            groupname=plan.name,
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
def reset_plan_data_cap(plan_id):
    """Reset data cap counter for all users in a plan"""
    plan = Plan.query.get_or_404(plan_id)
    plan.last_reset = datetime.utcnow()
    
    # Reset all users in this plan
    users = RadUser.query.filter_by(plan_id=plan_id).all()
    for user in users:
        if user.data_cap_period == plan.data_cap_period or not user.data_cap_period:
            user.last_reset = datetime.utcnow()
    
    db.session.commit()
    flash(f'Data cap reset for plan {plan.name} and all users in this plan. Counter will reset based on {plan.data_cap_period or "monthly"} period.', 'success')
    return redirect(url_for('edit_plan', plan_id=plan_id))


@app.route('/plans/<int:plan_id>/attributes/<int:attr_id>/delete', methods=['POST'])
@login_required
def delete_plan_attribute(plan_id, attr_id):
    attribute = PlanAttribute.query.get_or_404(attr_id)
    plan = Plan.query.get_or_404(plan_id)
    
    # Also delete from radgroupreply
    RadGroupReply.query.filter_by(
        groupname=plan.name,
        attribute=attribute.attribute
    ).delete()
    
    db.session.delete(attribute)
    db.session.commit()
    
    flash('Attribute deleted successfully.', 'success')
    return redirect(url_for('edit_plan', plan_id=plan_id))


@app.route('/plans/delete/<int:plan_id>', methods=['POST'])
@login_required
def delete_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    plan_name = plan.name
    
    # Delete related records
    RadGroupCheck.query.filter_by(groupname=plan_name).delete()
    RadGroupReply.query.filter_by(groupname=plan_name).delete()
    RadUserGroup.query.filter_by(groupname=plan_name).delete()
    
    db.session.delete(plan)
    db.session.commit()
    
    flash(f'Plan {plan_name} deleted successfully.', 'success')
    return redirect(url_for('plans'))


# NAS management routes
@app.route('/nas')
@login_required
def nas_list():
    all_nas = Nas.query.order_by(Nas.created_at.desc()).all()
    return render_template('nas/list.html', nas_list=all_nas)


@app.route('/nas/add', methods=['GET', 'POST'])
@login_required
def add_nas():
    form = NasForm()
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    if form.validate_on_submit():
        if Nas.query.filter_by(nasname=form.nasname.data).first():
            flash('NAS with this IP address already exists.', 'danger')
            return render_template('nas/form.html', form=form, title='Add NAS')
        
        nas = Nas(
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
def edit_nas(nas_id):
    nas = Nas.query.get_or_404(nas_id)
    form = NasForm(obj=nas)
    form.vendor.choices = Config.SUPPORTED_VENDORS
    
    if form.validate_on_submit():
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
def test_nas_connection(nas_id):
    """Test RADIUS connection to a NAS device"""
    nas = Nas.query.get_or_404(nas_id)
    
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
def delete_nas(nas_id):
    nas = Nas.query.get_or_404(nas_id)
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
    
    query = RadAcct.query
    
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
    session = RadAcct.query.get_or_404(session_id)
    
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
    
    query = RadPostAuth.query
    
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
    total_auths = RadPostAuth.query.count()
    accepted = RadPostAuth.query.filter_by(reply='Access-Accept').count()
    rejected = RadPostAuth.query.filter_by(reply='Access-Reject').count()
    challenged = RadPostAuth.query.filter_by(reply='Access-Challenge').count()
    
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


# Initialize database
@app.cli.command()
def init_db():
    """Initialize the database."""
    db.create_all()
    
    # Create default admin if not exists
    if not Admin.query.filter_by(username=Config.ADMIN_USERNAME).first():
        admin = Admin(
            username=Config.ADMIN_USERNAME,
            email=Config.ADMIN_EMAIL
        )
        admin.set_password(Config.ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()
        print(f'Admin user created: {Config.ADMIN_USERNAME}')
    
    print('Database initialized.')


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
def seed_users(path, update_password, plan):
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
            plan_obj = Plan.query.filter_by(name=plan_name).first()
            if not plan_obj:
                click.echo(
                    f'[{idx}] {username}: plan "{plan_name}" not found, '
                    'continuing without plan',
                    err=True,
                )

        user = RadUser.query.filter_by(username=username).first()
        is_new = user is None
        if is_new:
            user = RadUser(username=username, is_active=is_active)
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
                username=username, groupname=plan_obj.name
            ).first()
            if existing is None:
                RadUserGroup.query.filter_by(username=username).delete()
                db.session.add(RadUserGroup(
                    username=username, groupname=plan_obj.name, priority=1
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

