from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, abort, session, g, has_request_context, make_response, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
from config import Config
from models import db, BillingPlan, SubscriptionPayment, SessionKick, Withdrawal, VpnServer, Router, Admin, Plan, PlanAttribute, RadUser, RadCheck, RadReply, RadUserGroup, RadGroupCheck, RadGroupReply, RadAcct, Nas, RadPostAuth, Voucher, Package, Payment, Tenant, Gateway, Site, WifidogSession, PlatformSetting
from forms import LoginForm, AdminForm, PlanForm, PlanAttributeForm, UserForm, NasForm, SearchForm, VoucherGenerateForm, PackageForm, SignupForm, EmailForm, ResetPasswordForm, TenantSettingsForm, TeamMemberForm, GatewayForm, PaymentSettingsForm, WithdrawalForm, PortalSettingsForm
from flask_wtf.csrf import generate_csrf, validate_csrf
from wtforms.validators import ValidationError
from sqlalchemy import func, or_, and_, not_, desc, text
import clickpesa
import payments as paylib   # (app has a route called payments)
import snippe
from gateway import portal_ui
from sms import send_sms_async
from models import format_minutes
import radclient
import threading
import math
import os
import secretbox
import omada
import migrations
from mailer import send_mail
from tenancy import (current_tenant, tenant_id, scoped, owned_or_404, tenant_usernames, role_required, superadmin_required,
                     tenant_sites, current_site, site_for_new_things)
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
        'impersonating': current_user.is_authenticated and bool(session.get('impersonator_id')),
        'signup_enabled': Config.SIGNUP_ENABLED,
        'billing': billing_state(tenant) if tenant else None,
        'sites': tenant_sites(tenant.id) if tenant else [],
        'site': current_site() if tenant else None,
    }


BILLING_ENDPOINTS = {'billing', 'billing_pay', 'billing_payment', 'billing_payment_status', 'logout', 'static'}


@app.before_request
def block_suspended_tenants():
    if current_user.is_authenticated and not current_user.is_superadmin:
        tenant = current_user.tenant
        if session.get('impersonator_id'):
            if request.endpoint in ('logout', 'stop_impersonating'):
                return None
            if tenant is not None and tenant.status == 'suspended':
                flash(f'{tenant.name} is suspended, so its owner cannot use SafeNet.', 'warning')
                return redirect(url_for('stop_impersonating'))
        if tenant is None or tenant.status == 'suspended' or not current_user.is_active:
            logout_user()
            flash('This account is suspended. Please contact support.', 'danger')
            return redirect(url_for('login'))
        if tenant_blocked(tenant) and request.endpoint not in BILLING_ENDPOINTS:
            flash('Your SafeNet subscription has expired and your Wi-Fi is paused. Renew to continue.', 'danger')
            return redirect(url_for('billing'))


# Partners / shareholders (role "viewer"): read-only pages only; a partner limited to one
# site also doesn't see the business-wide pages (earnings balance, all sites, customer accounts).
VIEWER_PAGES = {'dashboard', 'live', 'api_live', 'payments', 'accounting', 'accounting_detail', 'vouchers',
                'docs', 'logout', 'static', 'landing', 'stop_impersonating', 'portal', 'portal_logo'}
VIEWER_BUSINESS_PAGES = VIEWER_PAGES | {'earnings', 'sites_page', 'users', 'auth_logs', 'switch_site'}
VIEWER_CHANGES = {'switch_site', 'stop_impersonating'}      # the only POSTs a partner may make


@app.before_request
def partners_are_read_only():
    if not (current_user.is_authenticated and getattr(current_user, 'is_viewer', False)):
        return None
    allowed = VIEWER_PAGES if current_user.site_id else VIEWER_BUSINESS_PAGES
    if request.endpoint in allowed and (request.method in ('GET', 'HEAD') or request.endpoint in VIEWER_CHANGES):
        return None
    if request.path.startswith('/api/'):
        return jsonify(error='Your account can view only.'), 403
    flash('Your account can view but not change anything.', 'info')
    return redirect(url_for('dashboard'))


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
    if session.get('impersonator_id'):
        return redirect(url_for('stop_impersonating'))
    session.pop('tenant_id', None); session.pop('site_id', None)
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


def _site_filters(tid, site):
    """Query filters limiting sessions, payments and vouchers to one site (None = all sites)."""
    mine = RadAcct.username.in_(tenant_usernames(tid))
    if site is None:
        return {'sessions': lambda q: q.filter(mine), 'payments': lambda q: q, 'vouchers': lambda q: q,
                'devices': lambda q: q}
    def names(sid):
        q = db.session.query(Gateway.name).filter(Gateway.tenant_id == tid)
        found = [n for (n,) in (q.filter(Gateway.site_id == sid) if sid else q)]
        site_ids = [sid] if sid else [x.id for x in tenant_sites(tid)]
        return found + [f'omada-{i}' for i in site_ids] + [f'wifidog-{i}' for i in site_ids]

    def ips(sid):
        q = db.session.query(Nas.nasname).filter(Nas.tenant_id == tid)
        return [n for (n,) in (q.filter(Nas.site_id == sid) if sid else q)]

    here = or_(RadAcct.calledstationid.in_(names(site.id) or ['-']), RadAcct.nasipaddress.in_(ips(site.id) or ['-']))
    if site.id == tenant_sites(tid)[0].id:
        # The main site also gets sessions from devices SafeNet doesn't know (e.g. an older shared gateway key)
        here = or_(here, not_(or_(RadAcct.calledstationid.in_(names(None) or ['-']), RadAcct.nasipaddress.in_(ips(None) or ['-']))))
    return {'sessions': lambda q: q.filter(mine, here),
            'payments': lambda q: q.filter(Payment.site_id == site.id),
            'vouchers': lambda q: q.filter(Voucher.site_id == site.id),
            'devices': lambda q: q.filter_by(site_id=site.id)}


def _collected(tid, site, since, until=None):
    """Money in (online payments + cash vouchers first used) between two times."""
    view = _site_filters(tid, site)
    pay = view['payments'](Payment.query.filter(Payment.tenant_id == tid, Payment.status == 'paid', Payment.paid_at >= since))
    cash = view['vouchers'](Voucher.query.filter(Voucher.tenant_id == tid, Voucher.first_used_at >= since,
                                                 Voucher.batch != 'online-payments', Voucher.price.isnot(None)))
    if until is not None:
        pay, cash = pay.filter(Payment.paid_at < until), cash.filter(Voucher.first_used_at < until)
    online = Decimal(str(pay.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar()))
    vouchers = Decimal(str(cash.with_entities(func.coalesce(func.sum(Voucher.price), 0)).scalar()))
    return {'online': online, 'vouchers': vouchers, 'total': online + vouchers,
            'online_count': pay.count(), 'voucher_count': cash.count()}


def _session_where(row, tid):
    """Readable place of a session: 'Omada · Mwenge', 'Ruijie · Mwenge', a gateway name or router IP."""
    where = row.calledstationid or row.nasipaddress or ''
    kind, _, sid = where.partition('-')
    if kind in ('omada', 'wifidog') and sid.isdigit():
        site = db.session.get(Site, int(sid))
        if site is not None and site.tenant_id == tid:
            return f"{'Omada' if kind == 'omada' else 'Ruijie'} · {site.name}"
    return where


def _device_state(last_seen, now):
    if not last_seen:
        return 'offline'
    age = (now - last_seen).total_seconds()
    return 'online' if age < 180 else ('degraded' if age < 900 else 'offline')


DOCS = [
    # slug, short name, icon, title, summary
    ('start', 'Start here', 'bi-signpost-split', 'Connect your Wi-Fi to SafeNet',
     'Pick the setup that matches the equipment you have, then follow its step-by-step guide.'),
    ('omada', 'TP-Link Omada (EAP)', 'bi-wifi', 'TP-Link Omada access points',
     'EAP225 and other Omada access points: plug in, point them to SafeNet, and sell internet. No extra box needed.'),
    ('ruijie', 'Ruijie (RG-AP)', 'bi-broadcast-pin', 'Ruijie access points',
     'Ruijie enterprise access points (RG-AP820-L and others) connect straight to SafeNet with WiFiDog. Just the access point and internet.'),
    ('gateway', 'SafeNet gateway box', 'bi-hdd-network', 'SafeNet gateway box with any access point',
     'A small Linux computer between the internet and any access point. Every SafeNet feature, with any brand of Wi-Fi.'),
    ('mikrotik', 'MikroTik', 'bi-router', 'MikroTik routers',
     'Connect a MikroTik hotspot to SafeNet with one script. Vouchers, customer accounts and speed limits.'),
    ('other-routers', 'Other routers', 'bi-diagram-3', 'Other routers (RADIUS)',
     'Any router or controller that can check logins with a RADIUS server.'),
    ('selling', 'Start selling', 'bi-bag-check', 'After connecting: start selling',
     'Packages, the login page, vouchers and payments: what to set up once your Wi-Fi is connected.'),
    ('troubleshooting', 'Troubleshooting', 'bi-life-preserver', 'Troubleshooting',
     'The common problems, what causes them and how to fix them.'),
]
DOC_PAGES = [dict(zip(('slug', 'short', 'icon', 'title', 'summary'), d)) for d in DOCS]


@app.route('/docs')
@app.route('/docs/<slug>')
def docs(slug='start'):
    """Public setup guides (no login needed, so installers can follow them too)."""
    index = {p['slug']: i for i, p in enumerate(DOC_PAGES)}
    if slug not in index:
        abort(404)
    i = index[slug]
    home = Tenant.query.filter_by(slug=migrations.DEFAULT_TENANT_SLUG).first()
    public = Config.PUBLIC_URL or request.host_url.rstrip('/')
    return render_template(f'docs/{slug}.html', pages=DOC_PAGES, page=DOC_PAGES[i], wifidog_base=Config.WIFIDOG_BASE,
                           server_ip=_server_ip(),
                           prev=DOC_PAGES[i - 1] if i > 0 else None,
                           next=DOC_PAGES[i + 1] if i + 1 < len(DOC_PAGES) else None,
                           public_url=public, public_host=urlparse(public).hostname or request.host,
                           omada_host=Config.OMADA_HOSTED_HOST, omada_hosted=_omada_hosted_available(),
                           repo_url='https://github.com/Kelvin-Charles/safenet.git',
                           support=(home.support_phone if home else None) or Config.HOTSPOT_SUPPORT)


@app.route('/dashboard')
@login_required
def dashboard():
    tid, tenant, site = tenant_id(), current_tenant(), current_site()
    view = _site_filters(tid, site)
    now = datetime.utcnow()
    midnight = _local_midnight_utc()
    offset = datetime.now() - now                                  # server local time - UTC
    month_start_local = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = month_start_local - offset
    last_seen = func.coalesce(RadAcct.acctupdatetime, RadAcct.acctstarttime)
    sessions = lambda: view['sessions'](RadAcct.query)

    # Devices (gateways + VPN routers) and their health
    devices = []
    for gw in view['devices'](scoped(Gateway)).order_by(Gateway.name):
        devices.append({'name': gw.name, 'kind': 'Gateway', 'site': gw.site_id, 'last': gw.last_seen_at,
                        'state': _device_state(gw.last_seen_at, now) if gw.is_active else 'offline', 'where': gw.name})
    for r in view['devices'](scoped(Router)).order_by(Router.name):
        devices.append({'name': r.name, 'kind': 'MikroTik' if r.vendor == 'mikrotik' else 'Router', 'site': r.site_id,
                        'last': r.last_handshake_at, 'state': _device_state(r.last_handshake_at, now) if r.is_active else 'offline',
                        'where': r.tunnel_ip})
    for st in ([site] if site else tenant_sites(tid)):
        if st.wifidog_enabled:
            devices.append({'name': f'{st.name} access points', 'kind': 'Ruijie / WiFiDog', 'site': st.id, 'last': st.wifidog_seen_at,
                            'state': _device_state(st.wifidog_seen_at, now), 'where': f'wifidog-{st.id}'})
    online_now = sessions().filter(RadAcct.acctstoptime.is_(None), last_seen >= now - timedelta(minutes=LIVE_STALE_MINUTES))
    per_device = dict(online_now.with_entities(RadAcct.calledstationid, func.count()).group_by(RadAcct.calledstationid).all())
    per_ip = dict(online_now.with_entities(RadAcct.nasipaddress, func.count()).group_by(RadAcct.nasipaddress).all())
    for d in devices:
        d['users'] = per_device.get(d['where'], 0) or per_ip.get(d['where'], 0)
    health = {k: sum(1 for d in devices if d['state'] == k) for k in ('online', 'degraded', 'offline')}
    last_telemetry = max((d['last'] for d in devices if d['last']), default=None)

    users_online = online_now.count()
    via_hotspot = online_now.filter(RadAcct.username.in_(db.session.query(Voucher.code).filter(Voucher.tenant_id == tid))).count()

    # Traffic
    today_rows = sessions().filter(or_(RadAcct.acctstoptime.is_(None), RadAcct.acctstoptime >= midnight),
                                   last_seen >= midnight)
    down_today, up_today = today_rows.with_entities(func.coalesce(func.sum(RadAcct.acctoutputoctets), 0),
                                                    func.coalesce(func.sum(RadAcct.acctinputoctets), 0)).one()
    down_today, up_today = int(down_today), int(up_today)
    total_bytes = int(sessions().with_entities(func.coalesce(func.sum(func.coalesce(RadAcct.acctinputoctets, 0)
                                                                      + func.coalesce(RadAcct.acctoutputoctets, 0)), 0)).scalar())
    since_midnight = max(1, (now - midnight).total_seconds())
    hours = []
    for i in range(24):
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23 - i)
        hours.append({'label': (start + offset).strftime('%H:00'), 'start': start, 'down': 0, 'up': 0})
    for last, down, up in sessions().filter(last_seen >= hours[0]['start']).with_entities(
            last_seen, RadAcct.acctoutputoctets, RadAcct.acctinputoctets).limit(20000):
        idx = int((last - hours[0]['start']).total_seconds() // 3600)
        if 0 <= idx < 24:
            hours[idx]['down'] += down or 0
            hours[idx]['up'] += up or 0
    peak = max([h['down'] + h['up'] for h in hours] + [1])

    # Money
    today = _collected(tid, site, midnight)
    period = _collected(tid, site, month_start)
    all_time = _collected(tid, site, datetime(2000, 1, 1))
    fees = view['payments'](Payment.query.filter(Payment.tenant_id == tid, Payment.status == 'paid', Payment.paid_at >= month_start)) \
        .with_entities(func.coalesce(func.sum(Payment.fee_amount), 0)).scalar()
    balance, earned, withdrawn = tenant_balance(tid)
    days = []
    for i in range(7):
        day_start = midnight - timedelta(days=6 - i)
        c = _collected(tid, site, day_start, day_start + timedelta(days=1))
        days.append({'label': (day_start + offset).strftime('%a'), 'date': (day_start + offset).strftime('%d %b'), 'total': c['total']})
    week_total = sum(d['total'] for d in days)
    day_peak = max([d['total'] for d in days] + [Decimal(1)])

    # Sites split (all-sites view)
    site_split = []
    if site is None:
        for s_ in tenant_sites(tid):
            site_split.append({'site': s_, 'total': _collected(tid, s_, month_start)['total']})

    # Subscribers
    users = scoped(RadUser)
    soon = now + timedelta(days=3)
    subs = {
        'active': users.filter(RadUser.is_active.is_(True), or_(RadUser.expires_at.is_(None), RadUser.expires_at > soon)).count(),
        'expiring': users.filter(RadUser.is_active.is_(True), RadUser.expires_at > now, RadUser.expires_at <= soon).count(),
        'expired': users.filter(RadUser.is_active.is_(True), RadUser.expires_at <= now).count(),
        'disabled': users.filter(RadUser.is_active.is_(False)).count(),
    }
    subs['total'] = sum(subs.values())

    # Recent connections
    recent = sessions().order_by(desc(last_seen)).limit(10).all()
    codes = {v.code: v for v in scoped(Voucher).filter(Voucher.code.in_([r.username for r in recent]))} if recent else {}
    cutoff = now - timedelta(minutes=LIVE_STALE_MINUTES)
    recent_rows = [{'user': r.username, 'mac': r.callingstationid, 'ip': r.framedipaddress,
                    'access': ('Voucher' if r.username in codes else 'Account') + (f' · {r.groupname}' if r.groupname else ''),
                    'router': _session_where(r, tid), 'last': r.acctupdatetime or r.acctstarttime,
                    'online': r.acctstoptime is None and (r.acctupdatetime or r.acctstarttime) >= cutoff} for r in recent]

    # Alerts
    alerts = []
    for d in devices:
        if d['state'] == 'offline':
            alerts.append(('danger', f"{d['kind']} {d['name']} is offline" + (f" (last seen {(d['last'] + offset):%d %b %H:%M})" if d['last'] else ' (never connected)')))
        elif d['state'] == 'degraded':
            alerts.append(('warning', f"{d['kind']} {d['name']} has not reported for a few minutes"))
    stuck = view['payments'](scoped(Payment).filter(Payment.status == 'pending', Payment.created_at < now - timedelta(minutes=10))).count()
    if stuck:
        alerts.append(('warning', f'{stuck} mobile-money payment{"s" if stuck > 1 else ""} still pending after 10 minutes'))
    failed = view['payments'](scoped(Payment).filter(Payment.status == 'failed', Payment.created_at >= midnight)).count()
    if failed:
        alerts.append(('info', f'{failed} payment{"s" if failed > 1 else ""} failed today'))
    if subs['expiring']:
        alerts.append(('info', f"{subs['expiring']} customer account{'s' if subs['expiring'] > 1 else ''} expire within 3 days"))

    hour = datetime.now().hour
    greeting = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 17 else 'Good evening')
    return render_template('dashboard.html', greeting=greeting, site=site, devices=devices, health=health,
                           last_telemetry=last_telemetry, users_online=users_online, via_hotspot=via_hotspot,
                           down_today=down_today, up_today=up_today, total_bytes=total_bytes,
                           avg_rate=(down_today + up_today) / since_midnight, hours=hours, peak=peak,
                           today=today, period=period, all_time=all_time, fees=Decimal(str(fees)),
                           balance=balance, withdrawn=withdrawn, days=days, week_total=week_total, day_peak=day_peak,
                           site_split=site_split, subs=subs, recent=recent_rows, alerts=alerts, offset=offset,
                           period_label=f"{month_start_local:%d %b %Y} – {datetime.now():%d %b %Y}",
                           currency=tenant.currency, now=now, platform_mode=tenant.payment_mode == 'platform')


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
        if _plan_limit_reached(current_tenant(), 'customers'):
            flash('Your plan does not allow more customers. Upgrade on the Billing page.', 'warning')
            return redirect(url_for('users'))
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
            site_id=site_for_new_things().id,
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
    
    query = _site_filters(tenant_id(), current_site())['sessions'](RadAcct.query)
    
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
    session = _site_filters(tenant_id(), current_site())['sessions'](RadAcct.query) \
        .filter(RadAcct.radacctid == session_id).first_or_404()
    
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

    for s in RadAcct.query.filter(RadAcct.username == username, RadAcct.acctstoptime.is_(None),
                                  RadAcct.calledstationid.like('omada-%'),
                                  func.coalesce(RadAcct.acctupdatetime, RadAcct.acctstarttime) >= recent):
        site = db.session.get(Site, int(s.calledstationid.split('-', 1)[1])) if s.calledstationid[6:].isdigit() else None
        if site is not None and site.tenant_id == tid:
            _omada_unauth_async(site, s.callingstationid)
            s.acctstoptime, s.acctterminatecause = datetime.utcnow(), 'Admin-Reset'

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


def _create_vouchers(count, plan, minutes, price, batch, tenant=None, max_devices=1, is_free=False, site_id=None):
    """Adds `count` vouchers (and their RADIUS rows) to the session; caller commits."""
    # Codes double as RADIUS usernames, so avoid clashes with both tables.
    taken = {c for (c,) in db.session.query(Voucher.code)}
    taken |= {u for (u,) in db.session.query(RadCheck.username).distinct()}
    created = []
    for _ in range(count):
        code = _new_voucher_code(taken)
        voucher = Voucher(tenant_id=tenant if tenant is not None else tenant_id(),
                          code=code, plan_id=plan.id if plan else None, batch=batch,
                          validity_minutes=minutes, price=None if is_free else price,
                          max_devices=max_devices or 1, is_free=bool(is_free), site_id=site_id)
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
    query = _site_filters(tenant_id(), current_site())['vouchers'](scoped(Voucher))
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
    stats.update(_free_trial_stats(tenant_id()))
    return render_template('vouchers/list.html', pagination=pagination, batches=batches,
                           batch=batch, state=state, search=search, stats=stats,
                           currency=current_tenant().currency)


def _mac_key(mac):
    return (mac or '').strip().lower().replace('-', ':')[:17] or None


def _returning_code(tid, mac):
    """The voucher a phone already paid for and can still use (time left, not disabled), so a guest
    who reconnects is let back in without typing the code again. None if there is none."""
    raw = re.sub(r'[^0-9A-Fa-f]', '', mac or '').upper()
    if len(raw) != 12:
        return None
    dashed = '-'.join(raw[i:i + 2] for i in range(0, 12, 2))
    now = datetime.utcnow() + timedelta(seconds=60)
    candidates = [c for (c,) in db.session.query(Voucher.code).filter(Voucher.tenant_id == tid, Voucher.first_mac == dashed.lower().replace('-', ':'),
                                                                     Voucher.status == 'active', Voucher.expires_at > now)
                  .order_by(Voucher.expires_at.desc()).limit(5)]
    used = db.session.query(RadAcct.username).filter(RadAcct.callingstationid == dashed) \
        .order_by(RadAcct.acctstarttime.desc()).limit(20).all()
    names = [u for (u,) in used if u not in candidates]
    if names:
        candidates += [c for (c,) in db.session.query(Voucher.code).filter(Voucher.tenant_id == tid, Voucher.code.in_(names),
                                                                          Voucher.status == 'active', Voucher.expires_at > now)
                       .order_by(Voucher.expires_at.desc())]
    for code in candidates:
        # not if an admin disconnected it after this phone last logged in with it
        last = db.session.query(func.max(RadAcct.acctstarttime)).filter(RadAcct.username == code,
                                                                          RadAcct.callingstationid == dashed).scalar()
        kicked = SessionKick.query.filter(SessionKick.tenant_id == tid, SessionKick.username == code,
                                          *([SessionKick.created_at >= last] if last else [])).first()
        if not kicked:
            return code
    return None


def _free_trial_stats(tid):
    """How many phones used a free trial, and how many of them paid for a package afterwards."""
    tried = dict(db.session.query(Voucher.first_mac, func.min(Voucher.first_used_at))
                 .filter(Voucher.tenant_id == tid, Voucher.is_free.is_(True), Voucher.first_mac.isnot(None))
                 .group_by(Voucher.first_mac))
    bought = set()
    if tried:
        for mac, paid_at in (db.session.query(Payment.client_mac, Payment.created_at)
                             .filter(Payment.tenant_id == tid, Payment.status == 'paid', Payment.client_mac.isnot(None))):
            key = _mac_key(mac)
            if key in tried and paid_at >= tried[key]:
                bought.add(key)
    return {'free_used': len(tried), 'free_bought': len(bought)}


@app.route('/vouchers/generate', methods=['GET', 'POST'])
@login_required
def generate_vouchers():
    form = VoucherGenerateForm()
    form.plan_id.choices = [(0, '-- No Plan --')] + [(p.id, p.name) for p in scoped(Plan).filter_by(is_active=True).all()]

    if form.validate_on_submit():
        plan = scoped(Plan).filter_by(id=form.plan_id.data).first() if form.plan_id.data else None
        minutes = form.validity_value.data * (1440 if form.validity_unit.data == 'days' else 60)
        price = Decimal(form.price.data.strip()) if form.price.data and not form.is_free.data else None
        batch = (form.batch.data or '').strip() or \
            ('Free trial ' if form.is_free.data else '') + datetime.utcnow().strftime('%Y%m%d-%H%M%S')

        _create_vouchers(form.count.data, plan, minutes, price, batch, max_devices=form.max_devices.data,
                         is_free=form.is_free.data, site_id=site_for_new_things().id)
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
                                            preview=True, lang_url=lang_url, networks=payment_networks(tenant) if tenant else payment_networks(),
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


# ---------------------------------------------------------------------------
# TP-Link Omada external portal: the controller sends guests here, SafeNet sells
# or checks the code, then tells the controller to let the guest online.
# ---------------------------------------------------------------------------
OMADA_PARAMS = ('clientMac', 'clientIp', 'apMac', 'gatewayMac', 'ssidName', 'radioId', 'vid', 'site', 'redirectUrl')
OMADA_DEFAULT_SECONDS = 86400
_omada_failures = {}


def _omada_site(token):
    site = Site.query.filter_by(portal_token=token[:24]).first() if token else None
    if site is None or not site.omada_ready:
        abort(404)
    tenant = db.session.get(Tenant, site.tenant_id)
    if tenant is None or tenant_blocked(tenant):
        abort(404)
    return site, tenant


def _omada_hosted_available():
    return bool(Config.OMADA_HOSTED_URL and Config.OMADA_HOSTED_USER and Config.OMADA_HOSTED_PASSWORD)


def _omada_controller(site):
    if site.omada_hosted:
        if not _omada_hosted_available():
            raise omada.OmadaError("SafeNet's Omada Controller is not set up on this server")
        return omada.Controller(Config.OMADA_HOSTED_URL, Config.OMADA_HOSTED_USER, Config.OMADA_HOSTED_PASSWORD)
    return omada.Controller(site.omada_url, site.omada_user, secretbox.decrypt(site.omada_password_enc),
                            verify_tls=site.omada_verify_tls)


def _omada_guest(token):
    """The Omada details of this guest, kept from the controller's redirect."""
    guest = session.get('omada') or {}
    return guest if guest.get('token') == token else {}


def _omada_too_many(key, limit):
    now = time.time()
    recent = [t for t in _omada_failures.get(key, []) if now - t < 300]
    _omada_failures[key] = recent
    return len(recent) >= limit


def _omada_page(site, tenant, **kw):
    return _hotspot_page(site, tenant, url_for('omada_portal', token=site.portal_token), **kw)


def _hotspot_page(site, tenant, base, *, view='login', error='', tab=None, **extra):
    """SafeNet's guest login/status/waiting page for a site, with its forms posting under `base`."""
    cfg = portal_config(tenant)
    if cfg.get('logo_version'):
        cfg['logo_url'] = url_for('portal_logo', slug=tenant.slug, v=cfg['logo_version'])
    th = portal_ui.theme(cfg)
    wanted = request.args.get('lang')
    lang = wanted if wanted in portal_ui.LANGS else request.cookies.get('sn_lang') if request.cookies.get('sn_lang') in portal_ui.LANGS else th['language']
    if view == 'status':
        html_out = portal_ui.status_page(th, lang, base=base, logout=False, lang_url=base, **extra)
    elif view == 'wait':
        html_out = portal_ui.waiting_page(th, lang, base=base, lang_url=base, **extra)
    elif view == 'gift':
        html_out = portal_ui.gift_page(th, lang, base=base, lang_url=base, **extra)
    else:
        packages = [{'id': p.id, 'name': p.name, 'description': p.description or '', 'price': f'{p.price:.0f}',
                     'currency': p.currency, 'validity_minutes': p.validity_minutes}
                    for p in _site_packages(Package.query.filter_by(tenant_id=tenant.id, is_active=True, show_on_portal=True),
                                            site.id).order_by(Package.sort_order, Package.price)]
        html_out = portal_ui.login_page(th, lang, packages=packages, error=error, tab=tab,
                                        action=base + '/login', buy_action=base + '/buy',
                                        buy_enabled=paylib.is_ready(_tenant_account(tenant)),
                                        lang_url=base, networks=payment_networks(tenant),
                                        logo_base=url_for('static', filename='img/'))
    resp = make_response(html_out)
    resp.headers['Cache-Control'] = 'no-store'
    if wanted in portal_ui.LANGS:
        resp.set_cookie('sn_lang', wanted, max_age=31536000, samesite='Lax')
    return resp


def _omada_let_in(site, tenant, guest, username, password):
    """Check the code, then ask the controller to let the guest online. Returns (info, error)."""
    mac = guest.get('clientMac', '')
    ok, message, info = _gateway_authenticate(tenant, username, password, mac)
    _log_auth(username, ok)
    if not ok:
        db.session.commit()
        return None, message
    seconds = info['session_timeout'] or OMADA_DEFAULT_SECONDS
    try:
        _omada_controller(site).authorize(mac, seconds, site=guest.get('site'), ap_mac=guest.get('apMac'),
                                          ssid=guest.get('ssidName'), radio_id=guest.get('radioId'),
                                          gateway_mac=guest.get('gatewayMac'), vid=guest.get('vid'))
    except omada.OmadaError as e:
        db.session.rollback()
        log.warning('Omada authorize for site %s failed: %s', site.id, e)
        site.omada_error = str(e)[:255]
        db.session.commit()
        return None, "Your code is fine, but the Wi-Fi didn't accept the login. Please try again in a minute."
    now = datetime.utcnow()
    sid = secrets.token_hex(8)
    db.session.add(RadAcct(acctsessionid=sid, acctuniqueid=hashlib.md5(f'omada:{site.id}:{sid}'.encode()).hexdigest(),
                           username=username[:64], nasipaddress=(request.remote_addr or '')[:15], groupname='',
                           acctterminatecause='', calledstationid=f'omada-{site.id}',
                           callingstationid=mac.upper().replace(':', '-')[:50],
                           framedipaddress=(guest.get('clientIp') or '')[:15], nasporttype='Wireless-802.11',
                           acctstarttime=now, acctupdatetime=now, acctsessiontime=0,
                           acctinputoctets=0, acctoutputoctets=0))
    site.omada_checked_at, site.omada_error = now, None
    db.session.commit()
    _omada_rate_async(site, mac, info.get('upload'), info.get('download'))
    return {'seconds': seconds, 'user': username}, None


@app.route('/omada/<token>')
def omada_portal(token):
    site, tenant = _omada_site(token)
    if request.args.get('clientMac'):
        session['omada'] = {'token': site.portal_token, **{k: request.args.get(k, '')[:500] for k in OMADA_PARAMS}}
        code = _returning_code(tenant.id, request.args.get('clientMac'))
        if code:
            guest = _omada_guest(site.portal_token)
            info, error = _omada_let_in(site, tenant, guest, code, code)
            if not error:
                log.info('omada: %s back online with %s', guest.get('clientMac'), code)
                return _omada_page(site, tenant, view='status', user=code, remaining=info['seconds'],
                                   dst=guest.get('redirectUrl', ''))
    return _omada_page(site, tenant)


@app.route('/omada/<token>/login', methods=['POST'])
def omada_login(token):
    site, tenant = _omada_site(token)
    guest = _omada_guest(site.portal_token)
    err = lambda m: _omada_page(site, tenant, error=m, tab='voucher')
    if not guest.get('clientMac'):
        return err('Please connect to the Wi-Fi again and open any website to get here.')
    if not request.form.get('agree'):
        return err('Please accept the terms of use to continue.')
    # Wrong codes: a few per phone, more per site (every guest there shares one public IP)
    key, site_key = f"{site.id}:{guest['clientMac']}", f'{site.id}:{request.remote_addr}'
    if _omada_too_many(key, 6) or _omada_too_many(site_key, 60):
        return err('Too many wrong attempts. Please wait a few minutes and try again.')
    username = (request.form.get('username') or '').strip()[:64]
    password = request.form.get('password') or ''
    if not username:
        username = password = re.sub(r'\s+', '', request.form.get('code') or '')[:32]
    if not username:
        return err('Enter your voucher code.')
    info, error = _omada_let_in(site, tenant, guest, username, password)
    if error:
        _omada_failures.setdefault(key, []).append(time.time())
        _omada_failures.setdefault(site_key, []).append(time.time())
        return err(error)
    return _omada_page(site, tenant, view='status', user=info['user'], remaining=info['seconds'],
                       dst=guest.get('redirectUrl', ''))


@app.route('/omada/<token>/buy', methods=['POST'])
def omada_buy(token):
    site, tenant = _omada_site(token)
    guest = _omada_guest(site.portal_token)
    err = lambda m: _omada_page(site, tenant, error=m, tab='buy')
    if not guest.get('clientMac'):
        return err('Please connect to the Wi-Fi again and open any website to get here.')
    if not request.form.get('agree'):
        return err('Please accept the terms of use to continue.')
    package = _site_packages(Package.query.filter_by(id=request.form.get('package_id', type=int), tenant_id=tenant.id,
                                                     is_active=True, show_on_portal=True), site.id).first()
    if not package:
        return err('Choose a package.')
    phone = re.sub(r'\D', '', request.form.get('phone', ''))
    if len(phone) == 9:                      # typed after the +255 prefix
        phone = '255' + phone
    network = (request.form.get('network') or '')[:16] or None
    if payment_networks(tenant) and not network:
        return err('Choose your mobile-money network.')
    payment, error, _ = _start_purchase(tenant, site.id, package, phone, network, guest.get('clientMac'),
                                        guest.get('clientIp'), f'omada-{site.id}', gift_phone=_gift_phone_field())
    if error:
        return err(error)
    session['omada_ref'] = payment.reference
    return redirect(url_for('omada_wait', token=site.portal_token, ref=payment.reference))


@app.route('/omada/<token>/buy/wait')
def omada_wait(token):
    site, tenant = _omada_site(token)
    guest = _omada_guest(site.portal_token)
    ref = (request.args.get('ref') or '')[:20]
    if not guest.get('clientMac') or session.get('omada_ref') != ref:
        return redirect(url_for('omada_portal', token=site.portal_token))
    payment = _refresh_payment(ref)
    if payment is None or payment.tenant_id != tenant.id:
        return redirect(url_for('omada_portal', token=site.portal_token))
    if payment.status == 'paid' and payment.voucher and payment.gift_phone:
        session.pop('omada_ref', None)
        return _omada_page(site, tenant, view='gift', code=payment.voucher.code, friend=payment.gift_phone,
                           package=payment.package_name)
    if payment.status == 'paid' and payment.voucher:
        code = payment.voucher.code
        session.pop('omada_ref', None)
        info, error = _omada_let_in(site, tenant, guest, code, code)
        if error:
            return _omada_page(site, tenant, error=f'Payment received. Your voucher code is {code}. {error}', tab='voucher')
        return _omada_page(site, tenant, view='status', user=code, remaining=info['seconds'], new_code=code,
                           dst=guest.get('redirectUrl', ''))
    if payment.status in ('failed', 'review'):
        session.pop('omada_ref', None)
        return _omada_page(site, tenant, error=f"Payment not completed: {payment.message or 'The payment was not completed.'}", tab='buy')
    timed_out = (datetime.utcnow() - payment.created_at).total_seconds() > 120 and not request.args.get('again')
    return _omada_page(site, tenant, view='wait', ref=ref, timed_out=timed_out,
                       info={'amount': f'{payment.amount:.0f}', 'currency': payment.currency, 'phone': payment.phone,
                             'package': payment.package_name, 'gift_phone': payment.gift_phone or ''})


# ---------------------------------------------------------------------------
# Omada access points managed from SafeNet alone (Open API on SafeNet's controller):
# SafeNet creates the controller site, the guest Wi-Fi and the portal, and adopts
# the tenant's access points. Tenants never open the controller.
# ---------------------------------------------------------------------------
OMADA_STATUS = {0: ('Offline', 'secondary'), 1: ('Online', 'success'), 2: ('Waiting to be added', 'warning'),
                3: ('Not responding', 'warning'), 4: ('Isolated', 'danger')}
OMADA_DETAIL = {10: 'Setting up', 11: 'Setting up', 12: 'Updating firmware', 13: 'Restarting', 22: 'Adding',
                23: 'Adding', 24: 'Adding failed', 25: 'Adding failed', 26: 'Managed by another controller',
                27: 'Managed by another controller'}


def _omada_openapi_available():
    return bool(_omada_hosted_available() and Config.OMADA_OPENAPI_CLIENT_ID and Config.OMADA_OPENAPI_CLIENT_SECRET)


_openapi_clients = {}


def _openapi():
    """One client per controller/app, so its access token is reused until it expires."""
    key = (Config.OMADA_HOSTED_URL, Config.OMADA_OPENAPI_CLIENT_ID, Config.OMADA_OPENAPI_CLIENT_SECRET)
    if key not in _openapi_clients:
        _openapi_clients[key] = omada.OpenApi(*key)
    return _openapi_clients[key]


def _omada_site_name(site, tenant):
    many = Site.query.filter_by(tenant_id=tenant.id).count() > 1
    return (f'{tenant.name} - {site.name}' if many else tenant.name)[:64]


def _omada_provision(site, tenant, wifi_name):
    """Create or update everything in the controller for this site. Raises OmadaError."""
    api = _openapi()
    if not site.portal_token:
        site.portal_token = secrets.token_urlsafe(12)[:16]
    site.omada_hosted = True
    if not site.omada_site_id:
        name = _omada_site_name(site, tenant)
        site_id = api.find_site(name)
        if not site_id:
            device_pw = omada.device_password()
            site_id = api.create_site(name, 'safenet', device_pw)
            site.omada_device_password_enc = secretbox.encrypt(device_pw)
        if not site_id:
            raise omada.OmadaError('the controller did not create the site')
        site.omada_site_id = site_id
    ssid_id = api.ensure_ssid(site.omada_site_id, wifi_name)
    public = Config.PUBLIC_URL.rstrip('/')
    api.ensure_portal(site.omada_site_id, ssid_id, f"{public}/omada/{site.portal_token}")
    api.ensure_pre_auth(site.omada_site_id, urlparse(public).hostname)
    others = [x.omada_site_id for x in Site.query.filter(Site.omada_site_id.isnot(None), Site.id != site.id)]
    api.ensure_operator_site(site.omada_site_id, Config.OMADA_HOSTED_USER, Config.OMADA_HOSTED_PASSWORD,
                             others[0] if others else site.omada_site_id)
    site.omada_ssid = wifi_name[:32]
    site.omada_checked_at, site.omada_error = datetime.utcnow(), None


def _omada_rate_async(site, mac, upload, download):
    """Apply the package's speed limit to this guest (SafeNet's controller only)."""
    if not (site and site.omada_hosted and site.omada_site_id and mac and _omada_openapi_available()):
        return
    site_id = site.omada_site_id

    def run():
        try:
            _openapi().set_client_rate(site_id, mac, upload, download)
            log.info('omada speed for %s at %s: up %s down %s', mac, site_id, upload or '-', download or '-')
        except omada.OmadaError as e:
            log.warning('omada speed for %s failed: %s', mac, e)
    threading.Thread(target=run, daemon=True).start()


def _omada_unauth_async(site, mac):
    if not (site and site.omada_hosted and site.omada_site_id and mac and _omada_openapi_available()):
        return
    site_id = site.omada_site_id

    def run():
        try:
            _openapi().unauth(site_id, mac)
            log.info('omada unauth %s at %s', mac, site_id)
        except omada.OmadaError as e:
            log.warning('omada unauth %s failed: %s', mac, e)
    threading.Thread(target=run, daemon=True).start()


@app.route('/sites/<int:site_id>/wifi')
@login_required
@role_required('admin')
def site_wifi(site_id):
    site = owned_or_404(Site, site_id)
    if not _omada_openapi_available():
        flash("Adding access points from SafeNet isn't switched on for this server yet.", 'warning')
        return redirect(url_for('sites_page'))
    devices, error = [], None
    if site.omada_site_id:
        try:
            devices = _openapi().devices(site.omada_site_id)
        except omada.OmadaError as e:
            error = str(e)
    for d in devices:
        label, color = OMADA_STATUS.get(d.get('status'), ('Unknown', 'secondary'))
        d['label'], d['color'] = OMADA_DETAIL.get(d.get('detailStatus'), label), color
    return render_template('sites_wifi.html', site=site, devices=devices, error=error,
                           omada_host=Config.OMADA_HOSTED_HOST)


@app.route('/sites/<int:site_id>/wifi/setup', methods=['POST'])
@login_required
@role_required('admin')
def site_wifi_setup(site_id):
    _check_csrf()
    site = owned_or_404(Site, site_id)
    if not _omada_openapi_available():
        abort(404)
    name = (request.form.get('wifi_name') or '').strip()[:32]
    if not name:
        flash('Enter the Wi-Fi name guests will see.', 'danger')
        return redirect(url_for('site_wifi', site_id=site.id))
    try:
        _omada_provision(site, current_tenant(), name)
        flash(f'Your Wi-Fi "{name}" is ready. Now add your access point below.', 'success')
    except omada.OmadaError as e:
        site.omada_error = str(e)[:255]
        flash(f'Could not set up the Wi-Fi: {e}', 'danger')
    db.session.commit()
    return redirect(url_for('site_wifi', site_id=site.id))


@app.route('/sites/<int:site_id>/wifi/adopt', methods=['POST'])
@login_required
@role_required('admin')
def site_wifi_adopt(site_id):
    _check_csrf()
    site = owned_or_404(Site, site_id)
    if not _omada_openapi_available() or not site.omada_site_id:
        abort(404)
    back = redirect(url_for('site_wifi', site_id=site.id))
    api = _openapi()
    try:
        mac = api.mac(request.form.get('mac'))
        known = {(d.get('mac') or '').upper() for d in api.devices(site.omada_site_id)}
        if mac in known:
            flash(f'{mac} is already one of your access points.', 'info')
            return back
        if mac not in {(d.get('mac') or '').upper() for d in api.pending(site.omada_site_id)}:
            flash(f"SafeNet can't see {mac} yet. Check it is plugged in with internet and pointed to {Config.OMADA_HOSTED_HOST}, "
                  'wait 2 minutes, then try again.', 'warning')
            return back
        user, password = (request.form.get('username') or '').strip(), request.form.get('password') or ''
        api.adopt(site.omada_site_id, mac, user or None, password or None)
        result = {}
        for _ in range(8):
            time.sleep(1.5)
            result = api.adopt_result(site.omada_site_id, mac)
            if result.get('adoptErrorCode') is not None:
                break
        code = result.get('adoptErrorCode')
        if code == 0 or code is None:
            flash(f'{mac} is being added. It restarts once and shows "Online" in 1–3 minutes.', 'success')
        elif result.get('adoptFailedType') == -2:
            flash(f'{mac} needs its own login: enter the username and password you set on the access point, then try again.', 'warning')
        else:
            flash(f'The access point did not accept (code {code}). Restart it and try again in 2 minutes.', 'danger')
    except omada.OmadaError as e:
        flash(str(e)[0].upper() + str(e)[1:], 'danger')
    return back


# ---------------------------------------------------------------------------
# WiFiDog: access points with a WiFiDog client (Ruijie RG-AP series, Reyee
# gateways and others) use SafeNet as their authentication server at
# /wifidog/<site token>/  (login/ auth/ ping/ portal/ gw_message.php).
# The access point redirects guests to login/, SafeNet sells or checks the code,
# sends the browser back to the access point with a one-time token, and the
# access point asks auth/?stage=login|counters|logout, expecting "Auth: 1" or "Auth: 0".
# ---------------------------------------------------------------------------
WIFIDOG_PARAMS = ('gw_address', 'gw_port', 'gw_id', 'mac', 'ip', 'url')
WIFIDOG_MAX_SECONDS = 30 * 86400
# Where an access point's own address can be (local networks only)
WIFIDOG_LOCAL_NETS = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
                                                         '100.64.0.0/10', '169.254.0.0/16', 'fc00::/7', 'fe80::/10')]


def _wifidog_site(token):
    site = Site.query.filter_by(portal_token=(token or '')[:24]).first()
    if site is None or not site.wifidog_enabled:
        return None, None
    tenant = db.session.get(Tenant, site.tenant_id)
    if tenant is None or tenant_blocked(tenant):
        return None, None
    return site, tenant


def _wifidog_text(body):
    resp = make_response(body)
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _wifidog_mac(value):
    mac = re.sub(r'[^0-9A-Fa-f]', '', value or '').upper()
    return '-'.join(mac[i:i + 2] for i in range(0, 12, 2)) if len(mac) == 12 else ''


def _wifidog_guest(token):
    guest = session.get('wifidog') or {}
    return guest if guest.get('token') == token else {}


def _wifidog_back_to_gateway(guest, token):
    """URL on the access point that finishes the login (it then asks us auth/?stage=login)."""
    try:
        address = ipaddress.ip_address(guest.get('gw_address', ''))
        port = int(guest.get('gw_port') or 2060)
    except ValueError:
        return None
    if not any(address in net for net in WIFIDOG_LOCAL_NETS) or not 0 < port < 65536:
        return None                                   # never send guests to an arbitrary host
    host = f'[{address}]' if address.version == 6 else str(address)
    return f'http://{host}:{port}/wifidog/auth?token={token}'


def _wifidog_let_in(site, tenant, guest, username, password):
    """Check the code and create the one-time token. Returns (redirect URL, error)."""
    mac = _wifidog_mac(guest.get('mac'))
    ok, message, info = _gateway_authenticate(tenant, username, password, mac)
    _log_auth(username, ok)
    if not ok:
        db.session.commit()
        return None, message
    seconds = min(info['session_timeout'] or OMADA_DEFAULT_SECONDS, WIFIDOG_MAX_SECONDS)
    token = secrets.token_urlsafe(24)
    back = _wifidog_back_to_gateway(guest, token)
    if not back:
        db.session.rollback()
        return None, 'Please connect to the Wi-Fi again and open any website to get here.'
    db.session.add(WifidogSession(tenant_id=tenant.id, site_id=site.id, token=token, username=username[:64], mac=mac or None,
                                  ip=(guest.get('ip') or '')[:45] or None, gw_id=(guest.get('gw_id') or '')[:64] or None,
                                  expires_at=datetime.utcnow() + timedelta(seconds=seconds)))
    db.session.commit()
    session['wifidog_token'] = token
    return back, None


def _wifidog_still_allowed(ws, tenant):
    """Why a guest must now be cut off, or None."""
    now = datetime.utcnow()
    if now >= ws.expires_at:
        return 'Session-Timeout'
    if tenant_blocked(tenant):
        return 'Admin-Reset'
    voucher = Voucher.query.filter_by(code=ws.username, tenant_id=tenant.id).first()
    if voucher is not None:
        if voucher.status == 'disabled' or (voucher.expires_at and voucher.expires_at <= now):
            return 'Session-Timeout' if voucher.status != 'disabled' else 'Admin-Reset'
    else:
        user = RadUser.query.filter_by(username=ws.username, tenant_id=tenant.id).first()
        if user is None or not user.is_active or (user.expires_at and user.expires_at <= now):
            return 'Admin-Reset'
    if SessionKick.query.filter(SessionKick.tenant_id == tenant.id, SessionKick.username == ws.username,
                                SessionKick.created_at >= ws.created_at).first():
        return 'Admin-Reset'
    return None


def _wifidog_end(ws, cause):
    now = datetime.utcnow()
    ws.status, ws.ended_at = 'ended', now
    row = RadAcct.query.filter_by(acctuniqueid=ws.acct_uid).first() if ws.acct_uid else None
    if row is not None and row.acctstoptime is None:
        row.acctstoptime, row.acctterminatecause = now, cause
        row.acctsessiontime = int((now - row.acctstarttime).total_seconds())


def _wifidog_auth(site, tenant):
    """auth/?stage=login|counters|logout&ip=&mac=&token=&incoming=&outgoing=&gw_id="""
    stage = (request.args.get('stage') or '').lower()
    ws = WifidogSession.query.filter_by(token=(request.args.get('token') or '')[:48], site_id=site.id).first()
    if ws is None or ws.status == 'ended':
        return _wifidog_text('Auth: 0')
    now = datetime.utcnow()
    mac = _wifidog_mac(request.args.get('mac'))
    if mac and ws.mac and mac != ws.mac:
        log.info('wifidog token for %s used by %s: refused', ws.mac, mac)
        return _wifidog_text('Auth: 0')
    try:
        incoming = max(0, int(request.args.get('incoming') or 0))
        outgoing = max(0, int(request.args.get('outgoing') or 0))
    except ValueError:
        incoming = outgoing = 0
    ws.last_seen_at = now
    if stage == 'login':
        if ws.status != 'new' or _wifidog_still_allowed(ws, tenant):
            db.session.commit()
            return _wifidog_text('Auth: 0')
        ws.status, ws.mac = 'active', ws.mac or mac or None
        ws.ip = (request.args.get('ip') or ws.ip or '')[:45] or None
        ws.gw_id = (request.args.get('gw_id') or ws.gw_id or '')[:64] or None
        ws.acct_uid = hashlib.md5(f'wifidog:{site.id}:{ws.token}'.encode()).hexdigest()
        db.session.add(RadAcct(acctsessionid=ws.token[:32], acctuniqueid=ws.acct_uid, username=ws.username,
                               nasipaddress=(request.remote_addr or '')[:15], groupname='', acctterminatecause='',
                               calledstationid=f'wifidog-{site.id}', callingstationid=(ws.mac or '')[:50],
                               framedipaddress=(ws.ip or '')[:15], nasporttype='Wireless-802.11',
                               acctstarttime=now, acctupdatetime=now, acctsessiontime=0,
                               acctinputoctets=0, acctoutputoctets=0))
        site.wifidog_seen_at = now
        db.session.commit()
        log.info('wifidog login %s mac=%s site=%s', ws.username, ws.mac, site.id)
        return _wifidog_text('Auth: 1')
    if ws.status != 'active':
        return _wifidog_text('Auth: 0')
    ws.incoming, ws.outgoing = max(ws.incoming or 0, incoming), max(ws.outgoing or 0, outgoing)
    row = RadAcct.query.filter_by(acctuniqueid=ws.acct_uid).first() if ws.acct_uid else None
    if row is not None:
        # WiFiDog "incoming" is what the guest downloaded; radacct output = to the user
        row.acctoutputoctets, row.acctinputoctets = ws.incoming, ws.outgoing
        row.acctupdatetime = now
        row.acctsessiontime = int((now - row.acctstarttime).total_seconds())
    site.wifidog_seen_at = now
    if stage == 'logout':
        _wifidog_end(ws, 'User-Request')
        db.session.commit()
        return _wifidog_text('Auth: 0')
    cause = _wifidog_still_allowed(ws, tenant)
    if cause:
        _wifidog_end(ws, cause)
        db.session.commit()
        log.info('wifidog cut off %s (%s)', ws.username, cause)
        return _wifidog_text('Auth: 0')
    db.session.commit()
    return _wifidog_text('Auth: 1')


@app.route('/wifidog/<token>/', defaults={'rest': ''}, methods=['GET', 'POST'])
@app.route('/wifidog/<token>/<path:rest>', methods=['GET', 'POST'])
def wifidog(token, rest):
    """Everything the access point calls. Paths are matched loosely because firmwares differ
    in how they join the server path and the WiFiDog endpoint names."""
    parts = [p for p in rest.lower().split('/') if p]
    log.info('wifidog %s /%s %s', token[:6], rest, {k: v for k, v in request.args.items() if k != 'token'})
    site, tenant = _wifidog_site(token)
    if 'ping' in parts:
        if site is not None:
            site.wifidog_seen_at = datetime.utcnow()
            site.wifidog_gw_id = (request.args.get('gw_id') or site.wifidog_gw_id or '')[:64] or None
            db.session.commit()
        return _wifidog_text('Pong')
    if site is None:
        return _wifidog_text('Auth: 0') if (request.args.get('stage') or 'auth' in parts) else ('', 404)
    if request.args.get('stage') or 'auth' in parts:
        return _wifidog_auth(site, tenant)
    public = Config.PUBLIC_URL.rstrip('/')
    if request.host.endswith(':5001') and public.startswith('https://'):
        # Access points reach us over plain HTTP; guests' browsers continue on HTTPS
        qs = request.query_string.decode('latin-1')
        return redirect(f"{public}/wifidog/{token}/{rest}" + (f'?{qs}' if qs else ''))
    base = f'/wifidog/{site.portal_token}/guest'
    if 'portal' in parts:
        ws = WifidogSession.query.filter_by(token=session.get('wifidog_token') or '-', site_id=site.id).first()
        if ws is not None and ws.status != 'ended':
            guest = _wifidog_guest(site.portal_token)
            return _hotspot_page(site, tenant, base, view='status', user=ws.username,
                                 remaining=max(0, int((ws.expires_at - datetime.utcnow()).total_seconds())),
                                 new_code=session.pop('wifidog_new_code', None), dst=guest.get('url', ''))
        return redirect(base)
    if any(p.startswith('gw_message') for p in parts):
        message = {'denied': 'Your session has ended. Log in again or buy a package.',
                   'activate': 'Please log in to continue.',
                   'failed_validation': 'Your code could not be confirmed. Please try again.'}.get(
            (request.args.get('message') or '').lower(), 'Please log in to continue.')
        return _hotspot_page(site, tenant, base, error=message)
    # login/ (or the bare server path): the access point sends a new guest here
    if request.args.get('gw_address') or request.args.get('mac'):
        session['wifidog'] = {'token': site.portal_token, **{k: (request.args.get(k) or '')[:500] for k in WIFIDOG_PARAMS}}
        site.wifidog_seen_at = datetime.utcnow()
        site.wifidog_gw_id = (request.args.get('gw_id') or site.wifidog_gw_id or '')[:64] or None
        db.session.commit()
        code = _returning_code(tenant.id, request.args.get('mac'))
        if code:
            back, error = _wifidog_let_in(site, tenant, _wifidog_guest(site.portal_token), code, code)
            if back:
                log.info('wifidog: %s back online with %s', request.args.get('mac'), code)
                return redirect(back)
    return _hotspot_page(site, tenant, base)


@app.route('/wifidog/<token>/guest')
def wifidog_guest_page(token):
    site, tenant = _wifidog_site(token)
    if site is None:
        abort(404)
    return _hotspot_page(site, tenant, f'/wifidog/{site.portal_token}/guest')


@app.route('/wifidog/<token>/guest/login', methods=['POST'])
def wifidog_login(token):
    site, tenant = _wifidog_site(token)
    if site is None:
        abort(404)
    base = f'/wifidog/{site.portal_token}/guest'
    guest = _wifidog_guest(site.portal_token)
    err = lambda m: _hotspot_page(site, tenant, base, error=m, tab='voucher')
    if not guest.get('gw_address'):
        return err('Please connect to the Wi-Fi again and open any website to get here.')
    if not request.form.get('agree'):
        return err('Please accept the terms of use to continue.')
    key, site_key = f"wd:{site.id}:{guest.get('mac')}", f'wd:{site.id}:{request.remote_addr}'
    if _omada_too_many(key, 6) or _omada_too_many(site_key, 60):
        return err('Too many wrong attempts. Please wait a few minutes and try again.')
    username = (request.form.get('username') or '').strip()[:64]
    password = request.form.get('password') or ''
    if not username:
        username = password = re.sub(r'\s+', '', request.form.get('code') or '')[:32]
    if not username:
        return err('Enter your voucher code.')
    back, error = _wifidog_let_in(site, tenant, guest, username, password)
    if error:
        _omada_failures.setdefault(key, []).append(time.time())
        _omada_failures.setdefault(site_key, []).append(time.time())
        return err(error)
    return redirect(back)


@app.route('/wifidog/<token>/guest/buy', methods=['POST'])
def wifidog_buy(token):
    site, tenant = _wifidog_site(token)
    if site is None:
        abort(404)
    base = f'/wifidog/{site.portal_token}/guest'
    guest = _wifidog_guest(site.portal_token)
    err = lambda m: _hotspot_page(site, tenant, base, error=m, tab='buy')
    if not guest.get('gw_address'):
        return err('Please connect to the Wi-Fi again and open any website to get here.')
    if not request.form.get('agree'):
        return err('Please accept the terms of use to continue.')
    package = _site_packages(Package.query.filter_by(id=request.form.get('package_id', type=int), tenant_id=tenant.id,
                                                     is_active=True, show_on_portal=True), site.id).first()
    if not package:
        return err('Choose a package.')
    phone = re.sub(r'\D', '', request.form.get('phone', ''))
    if len(phone) == 9:
        phone = '255' + phone
    network = (request.form.get('network') or '')[:16] or None
    if payment_networks(tenant) and not network:
        return err('Choose your mobile-money network.')
    payment, error, _ = _start_purchase(tenant, site.id, package, phone, network, _wifidog_mac(guest.get('mac')),
                                        guest.get('ip'), f'wifidog-{site.id}', gift_phone=_gift_phone_field())
    if error:
        return err(error)
    session['wifidog_ref'] = payment.reference
    return redirect(f'{base}/buy/wait?ref={payment.reference}')


@app.route('/wifidog/<token>/guest/buy/wait')
def wifidog_wait(token):
    site, tenant = _wifidog_site(token)
    if site is None:
        abort(404)
    base = f'/wifidog/{site.portal_token}/guest'
    guest = _wifidog_guest(site.portal_token)
    ref = (request.args.get('ref') or '')[:20]
    if not guest.get('gw_address') or session.get('wifidog_ref') != ref:
        return redirect(base)
    payment = _refresh_payment(ref)
    if payment is None or payment.tenant_id != tenant.id:
        return redirect(base)
    if payment.status == 'paid' and payment.voucher and payment.gift_phone:
        session.pop('wifidog_ref', None)
        return _hotspot_page(site, tenant, base, view='gift', code=payment.voucher.code, friend=payment.gift_phone,
                             package=payment.package_name)
    if payment.status == 'paid' and payment.voucher:
        code = payment.voucher.code
        session.pop('wifidog_ref', None)
        back, error = _wifidog_let_in(site, tenant, guest, code, code)
        if error:
            return _hotspot_page(site, tenant, base, error=f'Payment received. Your voucher code is {code}. {error}', tab='voucher')
        session['wifidog_new_code'] = code
        return redirect(back)
    if payment.status in ('failed', 'review'):
        session.pop('wifidog_ref', None)
        return _hotspot_page(site, tenant, base, error=f"Payment not completed: {payment.message or 'The payment was not completed.'}", tab='buy')
    timed_out = (datetime.utcnow() - payment.created_at).total_seconds() > 120 and not request.args.get('again')
    return _hotspot_page(site, tenant, base, view='wait', ref=ref, timed_out=timed_out,
                         info={'amount': f'{payment.amount:.0f}', 'currency': payment.currency, 'phone': payment.phone,
                               'package': payment.package_name, 'gift_phone': payment.gift_phone or ''})


@app.route('/sites/<int:site_id>/wifidog', methods=['POST'])
@login_required
@role_required('admin')
def site_wifidog(site_id):
    _check_csrf()
    site = owned_or_404(Site, site_id)
    site.wifidog_enabled = request.form.get('action') == 'enable'
    if site.wifidog_enabled and not site.portal_token:
        site.portal_token = secrets.token_urlsafe(12)[:16]
    db.session.commit()
    flash(f'Ruijie / WiFiDog access points {"switched on" if site.wifidog_enabled else "switched off"} for "{site.name}".', 'success')
    return redirect(url_for('sites_page'))


@app.route('/sites/<int:site_id>/omada', methods=['POST'])
@login_required
@role_required('admin')
def site_omada(site_id):
    """Save (or remove) a site's Omada Controller and test the connection."""
    _check_csrf()
    site = owned_or_404(Site, site_id)
    action = request.form.get('action')
    if action == 'remove':
        site.omada_url = site.omada_user = site.omada_password_enc = site.omada_error = None
        site.omada_checked_at, site.omada_hosted = None, False
        db.session.commit()
        flash(f'Omada removed from "{site.name}".', 'success')
        return redirect(url_for('sites_page'))
    if action == 'hosted':
        if not _omada_hosted_available():
            abort(404)
        site.omada_hosted = True
        site.omada_url = site.omada_user = site.omada_password_enc = None
        if not site.portal_token:
            site.portal_token = secrets.token_urlsafe(12)[:16]
        try:
            _omada_controller(site).check()
            site.omada_checked_at, site.omada_error = datetime.utcnow(), None
            flash(f'"{site.name}" now uses SafeNet\'s Omada Controller. Point your access points to {Config.OMADA_HOSTED_HOST} (steps below).', 'success')
        except omada.OmadaError as e:
            site.omada_error = str(e)[:255]
            flash(f"Saved, but SafeNet's Omada Controller did not answer: {e}", 'warning')
        db.session.commit()
        return redirect(url_for('sites_page'))
    url = (request.form.get('omada_url') or '').strip().rstrip('/')[:255]
    user = (request.form.get('omada_user') or '').strip()[:64]
    password = request.form.get('omada_password') or ''
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or not user or not (password or site.omada_password_enc):
        flash('Enter the controller address (e.g. https://203.0.113.5:8043), the hotspot operator name and password.', 'danger')
        return redirect(url_for('sites_page'))
    site.omada_url, site.omada_user, site.omada_hosted = url, user, False
    if password:
        site.omada_password_enc = secretbox.encrypt(password)
    site.omada_verify_tls = bool(request.form.get('omada_verify_tls'))
    if not site.portal_token:
        site.portal_token = secrets.token_urlsafe(12)[:16]
    try:
        _omada_controller(site).check()
        site.omada_checked_at, site.omada_error = datetime.utcnow(), None
        flash(f'Connected to the Omada Controller for "{site.name}". Now set the portal in Omada (steps below).', 'success')
    except omada.OmadaError as e:
        site.omada_error = str(e)[:255]
        flash(f'Saved, but SafeNet could not log in to the controller: {e}', 'warning')
    db.session.commit()
    return redirect(url_for('sites_page'))


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
                           clickpesa_ready=paylib.is_ready(_tenant_account(current_tenant())),
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


def platform_provider():
    """Provider SafeNet Pay uses now (the platform admin switches it in Platform: Billing)."""
    row = db.session.get(PlatformSetting, 'payment_provider')
    value = row.value if row and row.value else Config.PAYMENT_PROVIDER
    return value if value in paylib.PROVIDERS else 'clickpesa'


def _platform_account(provider=None):
    return paylib.platform_account(provider or platform_provider())


def _own_account(tenant):
    if tenant.own_provider == 'snippe':
        return paylib.Account('snippe', snippe.Credentials(secretbox.decrypt(tenant.snippe_api_key_enc),
                                                             secretbox.decrypt(tenant.snippe_webhook_key_enc)), 'own')
    return paylib.Account('clickpesa', clickpesa.Credentials(tenant.clickpesa_client_id or '',
                                                               secretbox.decrypt(tenant.clickpesa_api_key_enc),
                                                               secretbox.decrypt(tenant.clickpesa_checksum_key_enc)), 'own')


def _tenant_account(tenant):
    """Account that receives this tenant's package sales: their own, or SafeNet Pay."""
    return _own_account(tenant) if tenant.payment_mode == 'own' else _platform_account()


def _payment_account(payment):
    """The account a payment was made with (not today's setting: the admin may have switched since)."""
    if payment.provider_account == 'own':
        return _own_account(payment.tenant)
    return _platform_account(payment.provider or 'clickpesa')


def payment_networks(tenant=None):
    return paylib.networks(_tenant_account(tenant) if tenant is not None else _platform_account())


def check_network(phone, network_id, amount, currency='TZS', networks=None):
    """Error message if this number/network/amount can't be paid, else None."""
    networks = payment_networks() if networks is None else networks
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
                               tenant=payment.tenant_id, max_devices=payment.max_devices, site_id=payment.site_id)[0]
    db.session.flush()
    payment.voucher_id = voucher.id
    payment.status = 'paid'
    payment.paid_at = datetime.utcnow()
    log.info('payment %s paid: voucher %s', payment.reference, voucher.code)
    brand = _hotspot_settings(payment.tenant)
    help_line = f' Help: {brand["support"]}' if brand['support'] else ''
    valid = format_minutes(payment.validity_minutes)
    if payment.gift_phone:
        send_sms_async(payment.gift_phone, f'{brand["name"]}: 0{payment.phone[3:]} bought you {payment.package_name} of WiFi. '
                                           f'Connect to {brand["name"]} WiFi and enter code {voucher.code}. Valid {valid} '
                                           f'from first login.' + help_line, payment.reference)
        send_sms_async(payment.phone, f'{brand["name"]}: payment of {payment.currency} {payment.amount:,.0f} received. '
                                      f'We sent WiFi code {voucher.code} ({payment.package_name}) to 0{payment.gift_phone[3:]}.'
                                      + help_line, payment.reference)
        return
    send_sms_async(payment.phone, f'{brand["name"]}: payment of {payment.currency} {payment.amount:,.0f} received. '
                                  f'Your WiFi code is {voucher.code}, valid {valid} '
                                  f'from first login. Keep it to reconnect.' + help_line, payment.reference)


def _refresh_payment(reference, force=False):
    """Checks a pending payment with its provider. Locks the row so a payment is
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
            result = paylib.check(_payment_account(payment), reference, payment.provider_id)
        except paylib.PaymentError as e:
            log.warning('%s query %s failed: %s', payment.provider, reference, e)
            result = {'state': None}
        if result['state']:
            payment.provider_status = result.get('provider_status') or payment.provider_status
            payment.channel = result.get('channel') or payment.channel
            payment.message = (result.get('message') or payment.message or '')[:255] or None
            if result['state'] == 'paid':
                collected = result.get('amount')
                if collected is not None and collected < payment.amount:
                    payment.status = 'review'
                    payment.message = f'Collected {collected}, expected {payment.amount}'
                else:
                    _fulfil_payment(payment)
            elif result['state'] == 'failed':
                payment.status = 'failed'
    db.session.commit()
    return payment


@app.route('/payments')
@login_required
def payments():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '', type=str)
    search = request.args.get('search', '', type=str).strip()
    query = _site_filters(tenant_id(), current_site())['payments'](scoped(Payment))
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
    in_site = _site_filters(tid, current_site())['payments']
    paid_total = lambda since=None: in_site(db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.tenant_id == tid, Payment.status == 'paid', *( [Payment.paid_at >= since] if since else []))).scalar()
    stats = {
        'today': paid_total(today),
        'month': paid_total(month),
        'all_time': paid_total(),
        'paid_count': in_site(scoped(Payment).filter_by(status='paid')).count(),
        'pending': in_site(scoped(Payment).filter_by(status='pending')).count(),
    }
    return render_template('payments/list.html', pagination=pagination, stats=stats, status=status,
                           search=search, currency=current_tenant().currency,
                           clickpesa_ready=paylib.is_ready(_tenant_account(current_tenant())))


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


def _api_site_id():
    """Site of the gateway calling the API (older shared keys: the tenant's main site)."""
    gw = getattr(g, 'api_gateway', None)
    if gw is not None and gw.site_id:
        return gw.site_id
    return tenant_sites(g.api_tenant.id)[0].id


def _site_packages(query, site_id=None):
    """Packages sold at a site: its own plus the all-sites ones (default: the calling gateway's site)."""
    return query.filter(or_(Package.site_id.is_(None), Package.site_id == (site_id or _api_site_id())))


def _payment_json(payment):
    data = {
        'reference': payment.reference,
        'status': payment.status,
        'package': payment.package_name,
        'amount': f'{payment.amount:.0f}',
        'currency': payment.currency,
        'phone': payment.phone,
        'gift_phone': payment.gift_phone or '',
        'validity_minutes': payment.validity_minutes,
        'message': payment.message or '',
    }
    if payment.status == 'paid' and payment.voucher:
        data['code'] = payment.voucher.code
    return data


@app.route('/api/portal/packages')
@portal_api
def api_portal_packages():
    items = _site_packages(Package.query.filter_by(tenant_id=g.api_tenant.id, is_active=True, show_on_portal=True)).order_by(
        Package.sort_order, Package.price).all()
    return jsonify(packages=[{
        'id': p.id, 'name': p.name, 'description': p.description or '',
        'price': f'{p.price:.0f}', 'currency': p.currency,
        'validity_minutes': p.validity_minutes, 'validity': p.validity_label,
    } for p in items], payments_enabled=paylib.is_ready(_tenant_account(g.api_tenant)),
                   networks=payment_networks(g.api_tenant))


def _gift_phone_field():
    """Friend's number from a portal buy form, when "buy for a friend" is ticked."""
    if not request.form.get('gift'):
        return None
    return (request.form.get('gift_phone') or '').strip()[:20] or ''


def _start_purchase(tenant, site_id, package, phone, network=None, mac=None, ip=None, nas=None, gift_phone=None):
    """Create a payment and send the PIN prompt. Returns (payment or None, error, HTTP status).
    gift_phone: bought for a friend, whose number gets the code by SMS (the payer's device isn't let in)."""
    phone = _normalize_tz_phone(str(phone or ''))
    if not phone:
        return None, 'Enter a valid mobile number, e.g. 0712 345 678.', 400
    if gift_phone is not None:          # '' = "for a friend" ticked without a number
        gift_phone = _normalize_tz_phone(str(gift_phone))
        if not gift_phone:
            return None, "Enter your friend's mobile number, e.g. 0712 345 678.", 400
        if gift_phone == phone:
            gift_phone = None
    account = _tenant_account(tenant)
    if not paylib.is_ready(account):
        return None, 'Mobile payments are not available right now.', 503
    # Gateways send the network the guest picked; older ones don't, then the number decides
    problem = check_network(phone, network or None, package.price, package.currency, networks=paylib.networks(account))
    if problem:
        return None, problem, 400
    recent = Payment.query.filter(Payment.phone == phone, Payment.status == 'pending',
                                  Payment.created_at >= datetime.utcnow() - timedelta(seconds=90)).count()
    if recent:
        return None, 'A payment request was just sent to this number. Check your phone, or wait a minute.', 429

    payment = Payment(
        tenant_id=tenant.id,
        reference='SN' + secrets.token_hex(6).upper(),
        package_id=package.id, package_name=package.name, plan_id=package.plan_id,
        validity_minutes=package.validity_minutes, max_devices=package.max_devices or 1, phone=phone, gift_phone=gift_phone,
        amount=package.price, currency=package.currency,
        provider=account.provider, provider_account=account.owner,
        fee_amount=(package.price * _fee_percent(tenant) / 100).quantize(Decimal('0.01')) if account.owner == 'platform' else Decimal(0),
        nas_identifier=(nas or '')[:64] or None,
        site_id=site_id,
        client_mac=(mac or '')[:17] or None,
        client_ip=(ip or '')[:45] or None,
    )
    payment.net_amount = payment.amount - payment.fee_amount
    db.session.add(payment)
    db.session.commit()
    try:
        tx = paylib.start(account, payment.amount, phone, payment.reference, network or None,
                            webhook_url=_link('snippe_webhook') if account.provider == 'snippe' else None)
        payment.provider_id, payment.channel = tx['provider_id'], tx['channel']
        payment.provider_status = tx['provider_status']
    except paylib.PaymentError as e:
        log.warning('%s payment %s failed: %s', paylib.name(account), payment.reference, e.detail)
        payment.status, payment.message = 'failed', e.detail
        db.session.commit()
        return payment, str(e), 502
    db.session.commit()
    return payment, None, 200


@app.route('/api/portal/purchase', methods=['POST'])
@portal_api
def api_portal_purchase():
    data = request.get_json(silent=True) or {}
    package = _site_packages(Package.query.filter_by(id=data.get('package_id'), tenant_id=g.api_tenant.id,
                                                     is_active=True, show_on_portal=True)).first()
    if not package:
        return jsonify(error='That package is no longer available.'), 404
    payment, error, status = _start_purchase(g.api_tenant, _api_site_id(), package, data.get('phone', ''),
                                             str(data.get('network') or '')[:16], str(data.get('mac', '')),
                                             str(data.get('ip', '')), str(data.get('nas', '')),
                                             gift_phone=None if data.get('gift_phone') is None else str(data['gift_phone'])[:20])
    if error:
        return jsonify({**(_payment_json(payment) if payment else {}), 'error': error}), status
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
        device = _mac_key(mac)
        if voucher.is_free and device and not voucher.first_used_at and Voucher.query.filter(
                Voucher.tenant_id == tenant.id, Voucher.is_free.is_(True), Voucher.first_mac == device,
                Voucher.id != voucher.id).first():
            return False, 'This phone has already had a free trial. Buy a package to keep browsing.', None
        if not voucher.first_used_at:
            voucher.first_mac = device
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


@app.route('/api/gateway/returning', methods=['POST'])
@portal_api
def api_gateway_returning():
    """{"mac"} -> {"code"} of a voucher this phone paid for and can still use, so the gateway can
    let a returning guest straight back in. {} when there is none."""
    code = _returning_code(g.api_tenant.id, str((request.get_json(silent=True) or {}).get('mac') or '')[:17])
    return jsonify(code=code) if code else jsonify({})


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
    view = _site_filters(tid, current_site())
    open_sessions = (view['sessions'](RadAcct.query)
                     .filter(RadAcct.acctstoptime.is_(None), last_seen >= cutoff)
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

    day_sessions = view['sessions'](RadAcct.query).filter(or_(RadAcct.acctstoptime.is_(None), RadAcct.acctstoptime >= midnight))
    usage = day_sessions.with_entities(
        func.coalesce(func.sum(RadAcct.acctoutputoctets), 0),
        func.coalesce(func.sum(RadAcct.acctinputoctets), 0)).one()
    paid_today = view['payments'](scoped(Payment)).filter(Payment.status == 'paid', Payment.paid_at >= midnight)
    cash_today = view['vouchers'](scoped(Voucher)).filter(Voucher.first_used_at >= midnight, Voucher.batch != 'online-payments')
    stats = {
        'online': len(online),
        'down_today': int(usage[0]),
        'up_today': int(usage[1]),
        # login attempts aren't tied to a site: for one site, count its sessions started today
        'logins_today': (view['sessions'](RadAcct.query).filter(RadAcct.acctstarttime >= midnight).count() if current_site() else
                         RadPostAuth.query.filter(RadPostAuth.username.in_(names), RadPostAuth.authdate >= midnight,
                                                  RadPostAuth.reply == 'Access-Accept').count()),
        'rejects_today': 0 if current_site() else RadPostAuth.query.filter(RadPostAuth.username.in_(names), RadPostAuth.authdate >= midnight,
                                                                           RadPostAuth.reply != 'Access-Accept').count(),
        'online_revenue_today': float(paid_today.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar()),
        'online_sales_today': paid_today.count(),
        'cash_revenue_today': float(cash_today.with_entities(func.coalesce(func.sum(Voucher.price), 0)).scalar()),
        'vouchers_activated_today': view['vouchers'](scoped(Voucher)).filter(Voucher.first_used_at >= midnight).count(),
        'pending_payments': view['payments'](scoped(Payment)).filter_by(status='pending').count(),
    }

    events = []
    for a in ([] if current_site() else RadPostAuth.query.filter(RadPostAuth.username.in_(names)).order_by(RadPostAuth.id.desc()).limit(30)):
        ok = a.reply == 'Access-Accept'
        events.append({'at': _iso(a.authdate), 'type': 'login' if ok else 'reject',
                       'text': f'{a.username} {"logged in" if ok else "was rejected"}'})
    for s in view['sessions'](RadAcct.query).order_by(RadAcct.radacctid.desc()).limit(30):
        events.append({'at': _iso(s.acctstarttime), 'type': 'start',
                       'text': f'{s.username} started a session on {s.calledstationid or s.nasipaddress}'})
        if s.acctstoptime:
            events.append({'at': _iso(s.acctstoptime), 'type': 'stop',
                           'text': f'{s.username} disconnected ({s.acctterminatecause or "stop"})'})
    for p in view['payments'](scoped(Payment)).order_by(Payment.id.desc()).limit(20):
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
        form.role.choices = [c for c in form.role.choices if c[0] == 'staff']   # partners see the finances: owners only
    form.site_id.choices = [(0, 'The whole business (all sites)')] + [(x.id, f'Only {x.name}') for x in tenant_sites()]
    if form.validate_on_submit():
        if form.role.data != 'viewer' and _plan_limit_reached(current_tenant(), 'staff'):
            flash('Your plan does not allow more staff accounts. Upgrade on the Billing page.', 'warning')
            return redirect(url_for('team'))
        email = form.email.data.strip().lower()
        if Admin.query.filter_by(username=form.username.data).first():
            form.username.errors.append('That username is taken.')
        elif Admin.query.filter(func.lower(Admin.email) == email).first():
            form.email.errors.append('That email already has an account.')
        else:
            member = Admin(username=form.username.data, email=email, tenant_id=tenant_id(),
                           role=form.role.data, email_verified_at=datetime.utcnow(),
                           site_id=(form.site_id.data or None) if form.role.data == 'viewer' else None)
            member.set_password(form.password.data)
            db.session.add(member)
            db.session.commit()
            send_mail(email, f'You were added to {current_tenant().name} on SafeNet',
                      f'Hi {member.username},\n\n{current_user.username} added you to {current_tenant().name}.\n'
                      f'Log in at {_link("login")} with username "{member.username}" and the temporary '
                      f'password they gave you, then change it with "Forgot password".\n')
            flash(f'{member.username} added as {"a partner (view only)" if member.role == "viewer" else member.role}.', 'success')
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
SITE_ITEMS = {'gateway': Gateway, 'router': Router, 'nas': Nas, 'package': Package}
_server_ip_cache = {}


def _server_ip():
    """Public IP of SafeNet (access points allow it before guests log in)."""
    host = urlparse(Config.WIFIDOG_BASE).hostname or Config.WG_ENDPOINT
    if host not in _server_ip_cache:
        try:
            _server_ip_cache[host] = socket.gethostbyname(host)
        except OSError:
            return ''
    return _server_ip_cache[host]


def _site_from_form():
    sid = request.form.get('site_id', type=int)
    site = Site.query.filter_by(id=sid, tenant_id=tenant_id()).first() if sid else None
    return site or site_for_new_things()


def _safe_back(default):
    ref = request.referrer or ''
    path = urlparse(ref).path if urlparse(ref).netloc in ('', request.host) else ''
    return path if path.startswith('/') and not path.startswith('//') else default


@app.route('/sites')
@login_required
def sites_page():
    tid = tenant_id()
    items = tenant_sites(tid)
    midnight = _local_midnight_utc()
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for site in items:
        view = _site_filters(tid, site)
        rows.append({'site': site, 'gateways': scoped(Gateway).filter_by(site_id=site.id).count(),
                     'routers': scoped(Router).filter_by(site_id=site.id).count(),
                     'packages': scoped(Package).filter_by(site_id=site.id).count(),
                     'online': view['sessions'](RadAcct.query.filter(RadAcct.acctstoptime.is_(None),
                               func.coalesce(RadAcct.acctupdatetime, RadAcct.acctstarttime) >= datetime.utcnow() - timedelta(minutes=LIVE_STALE_MINUTES))).count(),
                     'today': _collected(tid, site, midnight), 'month': _collected(tid, site, month_start)})
    plan = current_tenant().billing_plan
    return render_template('sites.html', rows=rows, currency=current_tenant().currency,
                           limit=plan.max_sites if plan else None, omada_hosted=_omada_hosted_available(),
                           omada_host=Config.OMADA_HOSTED_HOST, wifidog_base=Config.WIFIDOG_BASE,
                           omada_openapi=_omada_openapi_available(),
                           server_ip=_server_ip(), now=datetime.utcnow())


@app.route('/sites/add', methods=['POST'])
@login_required
@role_required('admin')
def add_site():
    _check_csrf()
    name = (request.form.get('name') or '').strip()[:64]
    if not name:
        flash('Give the site a name.', 'danger')
    elif _plan_limit_reached(current_tenant(), 'sites'):
        flash('Your plan does not allow more sites. Upgrade on the Billing page.', 'warning')
    else:
        site = Site(tenant_id=tenant_id(), name=name, location=(request.form.get('location') or '').strip()[:128] or None)
        db.session.add(site)
        db.session.commit()
        session['site_id'] = site.id
        flash(f'Site "{name}" added and selected. New gateways, routers and vouchers now go to it.', 'success')
    return redirect(url_for('sites_page'))


@app.route('/sites/<int:site_id>/edit', methods=['POST'])
@login_required
@role_required('admin')
def edit_site(site_id):
    _check_csrf()
    site = owned_or_404(Site, site_id)
    name = (request.form.get('name') or '').strip()[:64]
    if name:
        site.name = name
        site.location = (request.form.get('location') or '').strip()[:128] or None
        db.session.commit()
        flash(f'Site "{name}" saved.', 'success')
    return redirect(url_for('sites_page'))


@app.route('/sites/<int:site_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_site(site_id):
    _check_csrf()
    site = owned_or_404(Site, site_id)
    others = [x for x in tenant_sites() if x.id != site.id]
    if not others:
        flash('You need at least one site.', 'warning')
        return redirect(url_for('sites_page'))
    target = others[0]
    for model in (Gateway, Router, Nas, Payment, Voucher):
        scoped(model).filter_by(site_id=site.id).update({'site_id': target.id}, synchronize_session=False)
    scoped(Package).filter_by(site_id=site.id).update({'site_id': target.id}, synchronize_session=False)
    if session.get('site_id') == site.id:
        session.pop('site_id', None)
    db.session.delete(site)
    db.session.commit()
    flash(f'Site "{site.name}" deleted. Its devices, packages and sales moved to "{target.name}".', 'success')
    return redirect(url_for('sites_page'))


@app.route('/sites/switch', methods=['POST'])
@login_required
def switch_site():
    _check_csrf()
    sid = request.form.get('site_id', type=int)
    if sid and Site.query.filter_by(id=sid, tenant_id=tenant_id()).first():
        session['site_id'] = sid
    else:
        session.pop('site_id', None)
    if request.form.get('to') == 'dashboard':
        return redirect(url_for('dashboard'))
    return redirect(_safe_back(url_for('dashboard')))


@app.route('/sites/assign', methods=['POST'])
@login_required
@role_required('admin')
def assign_site():
    """Move a gateway, router, RADIUS client or package to another site."""
    _check_csrf()
    model = SITE_ITEMS.get(request.form.get('kind'))
    if not model:
        abort(400)
    item = owned_or_404(model, request.form.get('id', type=int))
    sid = request.form.get('site_id', type=int)
    if sid:
        item.site_id = owned_or_404(Site, sid).id
    elif model is Package:
        item.site_id = None                     # sold at every site
    else:
        abort(400)
    if model is Router and item.nas:
        item.nas.site_id = item.site_id
    db.session.commit()
    flash('Site updated.', 'success')
    return redirect(_safe_back(url_for('sites_page')))


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
    gw = Gateway(tenant_id=tenant_id(), name=form.name.data.strip(), key_prefix=key[:8], key_hash=_hash_key(key),
                 site_id=_site_from_form().id)
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
    session.pop('site_id', None)
    flash(f'You are now managing {tenant.name}.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/platform/impersonate/<int:tid>', methods=['POST'])
@login_required
@superadmin_required
def impersonate(tid):
    """Log in as the tenant's owner to see exactly what they see, without their password."""
    _check_csrf()
    tenant = db.get_or_404(Tenant, tid)
    owner = Admin.query.filter_by(tenant_id=tenant.id, role='owner', is_superadmin=False) \
        .order_by(Admin.is_active.desc(), Admin.id).first()
    if not owner:
        flash(f'{tenant.name} has no owner account to log in as. Use Manage instead.', 'warning')
        return redirect(url_for('platform_tenants'))
    admin_id = current_user.id
    app.logger.info('platform admin %s logged in as %s (%s)', current_user.username, owner.username, tenant.name)
    session.pop('tenant_id', None); session.pop('site_id', None)
    login_user(owner)
    session['impersonator_id'] = admin_id
    flash(f'You are logged in as {owner.username}, the owner of {tenant.name}.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/platform/impersonate/stop', methods=['GET', 'POST'])
@login_required
def stop_impersonating():
    admin = db.session.get(Admin, session.pop('impersonator_id', 0) or 0)
    if not admin or not admin.is_superadmin or not admin.is_active:
        logout_user()
        return redirect(url_for('login'))
    session.pop('site_id', None)
    login_user(admin)
    flash('Back to your platform account.', 'info')
    return redirect(url_for('platform_tenants'))


@app.route('/platform/switch-back', methods=['POST'])
@login_required
@superadmin_required
def platform_switch_back():
    _check_csrf()
    session.pop('tenant_id', None); session.pop('site_id', None)
    return redirect(url_for('platform_tenants'))


# ---------------------------------------------------------------------------
# Earnings, payment settings and withdrawals (phase 3)
# ---------------------------------------------------------------------------
@app.route('/earnings')
@login_required
def earnings():
    if not (current_user.has_role('admin') or (current_user.is_viewer and not current_user.site_id)):
        flash("You don't have permission to open that page.", 'warning')
        return redirect(url_for('dashboard'))
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
    form = PaymentSettingsForm(payment_mode=tenant.payment_mode, client_id=tenant.clickpesa_client_id,
                               own_provider=tenant.own_provider or 'clickpesa')
    if form.validate_on_submit():
        mode = form.payment_mode.data
        tenant.own_provider = form.own_provider.data if form.own_provider.data in paylib.PROVIDERS else 'clickpesa'
        if form.client_id.data is not None:
            tenant.clickpesa_client_id = form.client_id.data.strip() or None
        if form.api_key.data:
            tenant.clickpesa_api_key_enc = secretbox.encrypt(form.api_key.data.strip())
        if form.checksum_key.data:
            tenant.clickpesa_checksum_key_enc = secretbox.encrypt(form.checksum_key.data.strip())
        if form.clear_checksum.data:
            tenant.clickpesa_checksum_key_enc = None
        if form.snippe_api_key.data:
            tenant.snippe_api_key_enc = secretbox.encrypt(form.snippe_api_key.data.strip())
        if form.snippe_webhook_key.data:
            tenant.snippe_webhook_key_enc = secretbox.encrypt(form.snippe_webhook_key.data.strip())
        own = _own_account(tenant)
        if mode == 'own' and not paylib.is_ready(own):
            db.session.rollback()
            need = 'your Snippe API key' if own.provider == 'snippe' else 'your ClickPesa Client ID and API key'
            flash(f'Enter {need} to receive payments directly.', 'danger')
            return redirect(url_for('payment_settings'))
        if mode == 'own' and own.provider == 'snippe' and not own.creds.webhook_key:
            flash('Saved. Add your Snippe webhook signing key too, so payments are confirmed the moment they arrive.', 'warning')
        tenant.payment_mode = mode
        db.session.commit()
        flash('Payment settings saved.', 'success')
        return redirect(url_for('payment_settings'))
    platform = _platform_account()
    return render_template('payment_settings.html', form=form, has_api_key=bool(tenant.clickpesa_api_key_enc),
                           has_checksum=bool(tenant.clickpesa_checksum_key_enc), fee_percent=_fee_percent(tenant),
                           has_snippe_key=bool(tenant.snippe_api_key_enc), has_snippe_webhook=bool(tenant.snippe_webhook_key_enc),
                           webhook_url=_link('clickpesa_webhook'), snippe_webhook_url=_link('snippe_webhook'),
                           platform_ready=paylib.is_ready(platform), platform_name=paylib.name(platform))


@app.route('/settings/payments/test', methods=['POST'])
@login_required
@role_required('owner')
def test_payment_settings():
    _check_csrf()
    account = _own_account(current_tenant())
    label = paylib.name(account)
    if not paylib.is_ready(account):
        flash(f'Save your {label} keys first.', 'warning')
    else:
        try:
            paylib.test(account)
            flash(f'{label} accepted your keys.', 'success')
        except paylib.PaymentError as e:
            flash(f'{label} rejected the keys: {e}', 'danger')
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
              description=f'VPN router: {name}', is_active=True, site_id=_site_from_form().id)
    db.session.add(nas)
    db.session.flush()
    router = Router(tenant_id=tenant_id(), name=name, vendor=vendor, tunnel_ip=tunnel_ip, public_key=public,
                    private_key_enc=secretbox.encrypt(private), nas_id=nas.id, site_id=nas.site_id)
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
    model = {'routers': Router, 'gateways': Gateway, 'customers': RadUser, 'staff': Admin, 'sites': Site}[kind]
    query = model.query.filter_by(tenant_id=tenant.id)
    if kind == 'staff':
        query = query.filter(Admin.role != 'viewer')      # partners only look
    return query.count() >= limit


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
    if sp.status == 'pending' and sp.method in paylib.PROVIDERS and (
            force or not sp.checked_at or (now - sp.checked_at).total_seconds() >= 3):
        sp.checked_at = now
        try:
            result = paylib.check(_platform_account(sp.method), reference, sp.provider_id)
        except paylib.PaymentError as e:
            log.warning('%s query %s failed: %s', sp.method, reference, e)
            result = {'state': None}
        if result['state']:
            sp.provider_status = result.get('provider_status') or sp.provider_status
            sp.channel = result.get('channel') or sp.channel
            sp.message = (result.get('message') or sp.message or '')[:255] or None
            if result['state'] == 'paid':
                collected = result.get('amount')
                if collected is not None and collected < sp.amount:
                    sp.status, sp.message = 'review', f'Collected {collected}, expected {sp.amount}'
                else:
                    _fulfil_subscription(sp)
            elif result['state'] == 'failed':
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
                           payments_ready=paylib.is_ready(_platform_account()), state=billing_state(tenant),
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
    account = _platform_account()
    problem = check_network(phone, None, plan.amount_for(months), networks=paylib.networks(account))
    if problem:
        flash(problem, 'danger')
        return redirect(url_for('billing'))
    if not paylib.is_ready(account):
        flash('Online payment is not available right now. Please contact SafeNet.', 'danger')
        return redirect(url_for('billing'))
    sp = SubscriptionPayment(tenant_id=tenant.id, billing_plan_id=plan.id, plan_name=plan.name, months=months,
                             amount=plan.amount_for(months), currency=plan.currency, phone=phone, method=account.provider,
                             reference='SB' + secrets.token_hex(6).upper(), created_by_id=current_user.id)
    db.session.add(sp)
    db.session.commit()
    try:
        tx = paylib.start(account, sp.amount, phone, sp.reference,
                            webhook_url=_link('snippe_webhook') if account.provider == 'snippe' else None)
        sp.provider_id, sp.channel, sp.provider_status = tx['provider_id'], tx['channel'], tx['provider_status']
    except paylib.PaymentError as e:
        sp.status, sp.message = 'failed', e.detail
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
            yearly = (request.form.get('price_yearly') or '').strip()
            plan.price_yearly = Decimal(yearly) if yearly else None
            plan.max_routers = request.form.get('max_routers', type=int)
            plan.max_sites = request.form.get('max_sites', type=int)
            plan.max_customers = request.form.get('max_customers', type=int)
            plan.max_staff = request.form.get('max_staff', type=int)
            plan.sort_order = request.form.get('sort_order', type=int) or 0
            plan.is_active = bool(request.form.get('is_active'))
            if not plan.name or plan.price < 0 or (plan.price_yearly is not None and plan.price_yearly < 0):
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
                           revenue_all=total(paid), payments_ready=paylib.is_ready(_platform_account()),
                           provider=platform_provider(), providers=paylib.PROVIDERS,
                           provider_ready={p: paylib.is_ready(_platform_account(p)) for p in paylib.PROVIDERS},
                           snippe_webhook_ready=bool(Config.SNIPPE_WEBHOOK_KEY), fee_percent=Config.PLATFORM_FEE_PERCENT)


@app.route('/platform/payment-provider', methods=['POST'])
@login_required
@superadmin_required
def platform_payment_provider():
    """Switch the provider SafeNet Pay uses for new payments (payments already started keep theirs)."""
    _check_csrf()
    provider = request.form.get('provider')
    if provider not in paylib.PROVIDERS:
        abort(400)
    if not paylib.is_ready(_platform_account(provider)):
        flash(f'Add the {paylib.PROVIDERS[provider]} keys to the server first.', 'danger')
        return redirect(url_for('platform_billing'))
    row = db.session.get(PlatformSetting, 'payment_provider') or PlatformSetting(key='payment_provider')
    row.value = provider
    db.session.add(row)
    db.session.commit()
    log.info('SafeNet Pay provider switched to %s by %s', provider, current_user.username)
    flash(f'SafeNet Pay now uses {paylib.PROVIDERS[provider]} for new payments.', 'success')
    return redirect(url_for('platform_billing'))


@app.route('/webhooks/snippe', methods=['POST'])
def snippe_webhook():
    """Snippe payment.completed / payment.failed / ... The signature is checked with the key of the
    account the payment was made with, and the payment is re-checked with Snippe before anything is granted."""
    raw = request.get_data(cache=False)
    try:
        event = json.loads(raw or b'{}')
    except ValueError:
        return jsonify(error='bad json'), 400
    ref = str(((event.get('data') or {}).get('reference')) or '')[:64]
    if not ref:
        return jsonify(received=True)
    payment = Payment.query.filter_by(provider='snippe', provider_id=ref).first()
    sub = None if payment else SubscriptionPayment.query.filter_by(method='snippe', provider_id=ref).first()
    if payment is None and sub is None:
        return jsonify(received=True)
    account = _payment_account(payment) if payment else _platform_account('snippe')
    if not snippe.verify_webhook(raw, request.headers.get('X-Webhook-Timestamp'), request.headers.get('X-Webhook-Signature'),
                                 account.creds.webhook_key):
        log.warning('snippe webhook for %s: bad or missing signature', ref)
        return jsonify(error='invalid signature'), 401
    try:
        if payment:
            _refresh_payment(payment.reference, force=True)
        else:
            _refresh_subscription(sub.reference, force=True)
    except Exception:
        db.session.rollback()
        log.exception('snippe webhook refresh %s failed', ref)
    return jsonify(received=True)


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

