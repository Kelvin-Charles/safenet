"""JSON API for the SafeNet mobile app (mobile/).

Two kinds of people use the app:
  * business accounts (owners, admins, staff, partners): sign in with their dashboard username and password and get a
    token; every request sends it as "Authorization: Bearer <token>" and the site it works on as "X-Site-Id" (none =
    all sites). The token is the same login as the web: the dashboard's helpers (current_tenant, current_site, roles,
    the partners' read-only rule) apply unchanged.
  * Wi-Fi customers (guests): sign in with their phone number and a code they bought with it, and see what they
    bought, at which businesses and sites, their time and data left, and what they spent, at every SafeNet business.

Pages the app doesn't have its own screen for yet open in the app's browser, already signed in (/api/m/web-link).
"""
import hashlib
import re
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, abort, g, jsonify, redirect, request
from flask_login import current_user, login_user
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import desc, func, or_

from i18n import tr
from models import (db, Admin, Package, Payment, Plan, RadAcct, RadCheck, RadReply, RadUserGroup, RateEvent, Site,
                    SmsContact, Tenant, Voucher, Withdrawal, OutageCredit, Outage)

bp = Blueprint('mobile', __name__)
A = None                     # the app module (set by init): its helpers, looked up when called so tests can replace them

BUSINESS_DAYS = 180          # a business sign-in lasts this long (changing the password ends it sooner)
GUEST_DAYS = 365
WEB_LINK_SECONDS = 120
PER_PAGE = 30
# what a partner (read-only account) may send besides looking
VIEWER_POSTS = {'mobile.login', 'mobile.web_link', 'mobile.guest_login'}


def init(flask_app, core):
    global A
    A = core
    flask_app.register_blueprint(bp)
    core.login_manager.request_loader(_user_from_token)


# ---------------------------------------------------------------- tokens
def _key(admin):
    """Part of the token that changes when the password changes (signs the app out)."""
    return hashlib.sha256((admin.password_hash or '').encode()).hexdigest()[:12]


def _business_token(admin):
    return A._tokens('mobile').dumps({'u': admin.id, 'k': _key(admin)})


def _bearer():
    raw = request.headers.get('Authorization') or ''
    return raw[7:].strip() if raw.lower().startswith('bearer ') else None


def _user_from_token(req):
    """Flask-Login: a business account from the app's token (only on the app's API)."""
    if not req.path.startswith('/api/m/') or req.path.startswith('/api/m/guest/'):
        return None
    token = _bearer()
    if not token:
        return None
    try:
        data = A._tokens('mobile').loads(token, max_age=BUSINESS_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
    admin = db.session.get(Admin, data.get('u')) if isinstance(data, dict) else None
    if admin is None or not admin.is_active or data.get('k') != _key(admin):
        return None
    if not admin.is_superadmin and admin.tenant and admin.tenant.status == 'suspended':
        return None
    return admin


# ---------------------------------------------------------------- request setup and errors
@bp.before_request
def _setup():
    g.mobile = True
    lang = (request.headers.get('Accept-Language') or '')[:2]
    if lang in A.i18n.LANGS:          # texts from the server in the app's language
        g.lang = lang
    raw = request.headers.get('X-Site-Id') or ''
    g.site_id = int(raw) if raw.isdigit() else None


def _err(message, status):
    return jsonify(error=message), status


@bp.errorhandler(400)
def _bad(e):
    return _err(getattr(e, 'description', None) or tr('Check what you entered.'), 400)


@bp.errorhandler(401)
def _unauth(e):
    return _err(tr('Please sign in again.'), 401)


@bp.errorhandler(403)
def _forbidden(e):
    return _err(tr("You don't have permission to do that."), 403)


@bp.errorhandler(404)
def _missing(e):
    return _err(tr('Not found.'), 404)


def _need_login(role=None):
    """The signed-in business account (401 if none; 403 without `role`, or for a platform account with no business)."""
    if not current_user.is_authenticated:
        abort(401)
    if role and not current_user.has_role(role):
        abort(403)
    if A.current_tenant() is None:
        abort(403)
    return current_user


def _no_viewer():
    if current_user.is_viewer:
        abort(403)


def _money(x):
    return float(x or 0)


def _iso(dt):
    return A._iso(dt)


def _site_name(site_id):
    if not site_id:
        return None
    names = g.setdefault('site_names', {})
    if site_id not in names:
        site = db.session.get(Site, site_id)
        names[site_id] = site.name if site else None
    return names[site_id]


# ---------------------------------------------------------------- business: sign in, who am I
@bp.route('/api/m/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or '').strip()[:64]
    password = str(data.get('password') or '')[:200]
    user_key, ip_key = f'user:{username.lower()}', f'ip:{A._client_ip()}'
    if A._rate_limited('login', user_key, A.LOGIN_LIMITS[0][1], 15) or A._rate_limited('login', ip_key, A.LOGIN_LIMITS[1][1], 15):
        return _err(tr('Too many failed attempts. Please wait 15 minutes, or reset your password.'), 429)
    admin = Admin.query.filter(or_(Admin.username == username, Admin.email == username.lower())).first() if username else None
    if admin is None or not password or not admin.check_password(password):
        A._rate_hit('login', user_key, ip_key)
        return _err(tr('Invalid username or password.'), 401)
    if not admin.is_active:
        return _err(tr('Your account has been disabled.'), 403)
    if not admin.email_verified_at:
        return jsonify(error=tr('Confirm your email first: open the link we sent to {email}.', email=admin.email),
                       unverified=True, email=admin.email), 403
    if not admin.is_superadmin and admin.tenant and admin.tenant.status == 'suspended':
        return _err(tr('This account is suspended. Please contact support.'), 403)
    if admin.tenant is None:
        return _err(tr('This account has no business. Open a business on the web first.'), 403)
    admin.last_login = datetime.utcnow()
    db.session.commit()
    return jsonify(token=_business_token(admin), me=_me_json(admin))


def _me_json(admin):
    tenant = (A.current_tenant() if current_user.is_authenticated else None) or admin.tenant
    sites = A.tenant_sites(tenant.id)
    if admin.site_id and not admin.is_superadmin:
        sites = [s for s in sites if s.id == admin.site_id]
    can_money = admin.has_role('admin') or (admin.is_viewer and not admin.site_id)
    return {
        'kind': 'business',
        'user': {'id': admin.id, 'username': admin.username, 'email': admin.email, 'role': admin.role,
                 'language': admin.language or 'en', 'viewer': admin.is_viewer},
        'tenant': {'id': tenant.id, 'name': tenant.name, 'slug': tenant.slug, 'currency': tenant.currency or 'TZS',
                   'status': tenant.status, 'payment_mode': tenant.payment_mode,
                   'trial_ends': _iso(tenant.trial_ends_at),
                   'guest_app': f'{A.Config.PUBLIC_URL}/app/{tenant.slug}'},
        'sites': [{'id': s.id, 'name': s.name, 'reyee': bool(s.ruijie_ready)} for s in sites],
        'fixed_site': admin.site_id if admin.site_id and not admin.is_superadmin else None,
        'can': {'money': can_money, 'customers': admin.has_role('admin'), 'packages': admin.has_role('admin'),
                'change': not admin.is_viewer, 'withdraw': admin.has_role('owner'), 'sms': A.sms_is_configured()},
    }


@bp.route('/api/m/config')
def config():
    """What the sign-in screen offers: registering a business, signing in by SMS."""
    return jsonify(signup=bool(A.Config.SIGNUP_ENABLED), trial_days=A.Config.TRIAL_DAYS, sms_login=A.sms_is_configured(),
                   forgot_url=f'{A.Config.PUBLIC_URL}/forgot', terms_url=f'{A.Config.PUBLIC_URL}/')


@bp.route('/api/m/signup', methods=['POST'])
def signup():
    """Register a business, as on the web: a trial business and its owner; the owner confirms their email, then signs in."""
    if not A.Config.SIGNUP_ENABLED:
        abort(404)
    d = request.get_json(silent=True) or {}
    business = re.sub(r'\s+', ' ', str(d.get('business_name') or '')).strip()
    username = str(d.get('username') or '').strip()
    email = str(d.get('email') or '').strip().lower()
    phone = str(d.get('phone') or '').strip()[:20]
    password = str(d.get('password') or '')
    fields = {}
    if not 2 <= len(business) <= 100:
        fields['business_name'] = tr('Enter your business name.')
    if not 3 <= len(username) <= 64 or not re.match(r'^[a-zA-Z0-9_.-]+$', username):
        fields['username'] = tr('Use letters, numbers, dots, hyphens and underscores only (at least 3).')
    if len(email) > 120 or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        fields['email'] = tr('Enter a valid email address.')
    if phone and not A._normalize_tz_phone(phone):
        fields['phone'] = tr('Enter your phone number, e.g. 0712 345 678.')
    if not 8 <= len(password) <= 128:
        fields['password'] = tr('At least 8 characters.')
    if not d.get('accept'):
        fields['accept'] = tr('Accept the terms of service to continue.')
    if not fields:
        if Admin.query.filter_by(username=username).first():
            fields['username'] = tr('That username is taken.')
        elif Admin.query.filter(func.lower(Admin.email) == email).first():
            fields['email'] = tr('An account with this email already exists. Log in or reset your password.')
    if fields:
        return jsonify(error=next(iter(fields.values())), fields=fields), 400
    ip_key = f'ip:{A._client_ip()}'
    if A._rate_limited('signup', ip_key, 5, 60):
        return _err(tr('Too many new accounts from this connection. Please try again in an hour.'), 429)
    A._rate_hit('signup', ip_key)
    tenant = Tenant(name=business, slug=A._unique_slug(business), status='trial', phone=phone or None,
                    trial_ends_at=datetime.utcnow() + timedelta(days=A.Config.TRIAL_DAYS))
    A.refresh_service_until(tenant)
    db.session.add(tenant)
    db.session.flush()
    owner = Admin(username=username, email=email, tenant_id=tenant.id, role='owner')
    owner.set_password(password)
    db.session.add(owner)
    db.session.commit()
    A._send_verification(owner)
    return jsonify(ok=True, email=email, trial_days=A.Config.TRIAL_DAYS)


@bp.route('/api/m/resend', methods=['POST'])
def resend():
    """Send the email confirmation link again."""
    email = str((request.get_json(silent=True) or {}).get('email') or '').strip().lower()[:120]
    if email and not (A._rate_limited('mail', f'ip:{A._client_ip()}', 5, 60) or A._rate_limited('mail', f'to:{email}', 3, 60)):
        A._rate_hit('mail', f'ip:{A._client_ip()}', f'to:{email}')
        admin = Admin.query.filter(func.lower(Admin.email) == email).first()
        if admin and not admin.email_verified_at:
            A._send_verification(admin)
    return jsonify(ok=True)


@bp.route('/api/m/me')
def me():
    return jsonify(_me_json(_need_login()))


@bp.route('/api/m/language', methods=['POST'])
def language():
    user = _need_login()
    lang = (request.get_json(silent=True) or {}).get('lang')
    if lang in A.i18n.LANGS and user.language != lang:
        user.language = lang
        db.session.commit()
    return jsonify(ok=True, language=user.language)


@bp.route('/api/m/web-link', methods=['POST'])
def web_link():
    """A one-time link that opens a dashboard page in the app's browser, signed in as this account."""
    user = _need_login()
    path = str((request.get_json(silent=True) or {}).get('path') or '/dashboard')[:300]
    if not path.startswith('/') or path.startswith('//'):
        path = '/dashboard'
    token = A._tokens('mobile-web').dumps({'u': user.id, 'k': _key(user), 'p': path, 's': g.site_id,
                                          'n': A.secrets.token_hex(8)})
    return jsonify(url=f'{A.Config.PUBLIC_URL}/m/enter/{token}')


@bp.route('/m/enter/<token>')
def enter(token):
    try:
        data = A._tokens('mobile-web').loads(token, max_age=WEB_LINK_SECONDS)
    except (BadSignature, SignatureExpired):
        return redirect('/login')
    used = hashlib.sha256(token.encode()).hexdigest()[:40]
    if RateEvent.query.filter_by(kind='mweb', key=used).first():          # each link works once
        return redirect('/login')
    admin = db.session.get(Admin, data.get('u'))
    if admin is None or not admin.is_active or data.get('k') != _key(admin):
        return redirect('/login')
    db.session.add(RateEvent(kind='mweb', key=used))
    db.session.commit()
    login_user(admin)
    from flask import session
    if data.get('s'):
        session['site_id'] = data['s']
    session['in_app'] = True          # the page drops the web menu and top bar (base.html)
    return redirect(data.get('p') or '/dashboard')


# ---------------------------------------------------------------- business: home
@bp.route('/api/m/dashboard')
def dashboard():
    _need_login()
    tid, tenant, site = A.tenant_id(), A.current_tenant(), A.current_site()
    A._omada_sync_soon()
    view = A._site_filters(tid, site)
    now = datetime.utcnow()
    midnight = A._local_midnight_utc()
    offset = A._local_offset()
    month_start = (now + offset).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - offset
    last_seen = func.coalesce(RadAcct.acctupdatetime, RadAcct.acctstarttime)
    sessions = lambda: view['sessions'](RadAcct.query)
    online = sessions().filter(RadAcct.acctstoptime.is_(None), last_seen >= now - timedelta(minutes=A.LIVE_STALE_MINUTES)).count()
    reyee_online = 0
    for st in ([site] if site else A.tenant_sites(tid)):
        if st.ruijie_clients and st.ruijie_clients_at and (now - st.ruijie_clients_at).total_seconds() < 300:
            reyee_online += len(A.json.loads(st.ruijie_clients))
    today_rows = sessions().filter(or_(RadAcct.acctstoptime.is_(None), RadAcct.acctstoptime >= midnight), last_seen >= midnight)
    down, up = today_rows.with_entities(func.coalesce(func.sum(RadAcct.acctoutputoctets), 0),
                                        func.coalesce(func.sum(RadAcct.acctinputoctets), 0)).one()
    today = A._collected(tid, site, midnight)
    month = A._collected(tid, site, month_start)
    days = []
    for i in range(7):
        start = midnight - timedelta(days=6 - i)
        c = A._collected(tid, site, start, start + timedelta(days=1))
        days.append({'label': (start + offset).strftime('%a'), 'date': (start + offset).strftime('%d %b'), 'total': _money(c['total'])})
    can_money = current_user.has_role('admin') or (current_user.is_viewer and not current_user.site_id)
    balance = A.tenant_balance(tid)[0] if can_money and tenant.payment_mode == 'platform' else None
    vq = view['vouchers'](A.scoped(Voucher))
    codes = {'unused': vq.filter(Voucher.status == 'unused').count(),
             'active': vq.filter(Voucher.status == 'active', Voucher.expires_at > now).count()}
    pending = view['payments'](A.scoped(Payment)).filter(Payment.status == 'pending', Payment.created_at < now - timedelta(minutes=10),
                                                         Payment.created_at >= now - timedelta(days=1)).count()
    sites = []
    if site is None:
        for s in A.tenant_sites(tid):
            sites.append({'id': s.id, 'name': s.name, 'month': _money(A._collected(tid, s, month_start)['total'])})
    recent = []
    for p in view['payments'](A.scoped(Payment)).filter(Payment.status == 'paid').order_by(Payment.paid_at.desc()).limit(8):
        recent.append({'phone': p.phone, 'package': p.package_name, 'amount': _money(p.amount), 'at': _iso(p.paid_at),
                       'site': _site_name(p.site_id)})
    hour = (now + offset).hour
    greeting = tr('Good morning') if hour < 12 else (tr('Good afternoon') if hour < 17 else tr('Good evening'))
    return jsonify(greeting=greeting, currency=tenant.currency or 'TZS', site=site.name if site else None,
                   online=online + reyee_online, down_today=int(down), up_today=int(up),
                   today={'total': _money(today['total']), 'online': _money(today['online']), 'cash': _money(today['vouchers']),
                          'sales': today['online_count'] + today['voucher_count']},
                   month={'total': _money(month['total']), 'sales': month['online_count'] + month['voucher_count']},
                   week=days, balance=_money(balance) if balance is not None else None, codes=codes,
                   pending_payments=pending, sites=sites, recent=recent)


@bp.route('/api/m/live')
def live():
    _need_login()
    return A.api_live()


@bp.route('/api/m/live/disconnect', methods=['POST'])
def live_disconnect():
    _need_login()
    _no_viewer()
    username = str((request.get_json(silent=True) or {}).get('username') or '')[:64]
    owned = {n for (n,) in db.session.execute(A.tenant_usernames())}
    if username not in owned:
        abort(404)
    sent = A.disconnect_subscriber(A.tenant_id(), username)
    db.session.commit()
    return jsonify(ok=True, routers=sent)


# ---------------------------------------------------------------- business: vouchers
def _voucher_json(v, phone=None):
    return {'id': v.id, 'code': v.code if v.code_final else None, 'state': v.state, 'reyee_why': v.ruijie_why, 'batch': v.batch, 'plan': v.plan.name if v.plan else None,
            'minutes': v.validity_minutes, 'validity': v.validity_label, 'price': _money(v.price) if v.price is not None else None,
            'devices': v.max_devices or 1, 'free': bool(v.is_free), 'created': _iso(v.created_at),
            'started': _iso(v.first_used_at), 'expires': _iso(v.expires_at), 'phone': phone,
            'sites': [s.name for s in v.sites], 'site': _site_name(v.site_id),
            'reyee': v.ruijie_state}


@bp.route('/api/m/vouchers')
def vouchers():
    _need_login()
    a = request.args
    now = datetime.utcnow()
    q = A._voucher_query(a.get('batch', '')[:64], a.get('state', '')[:16], a.get('search', '').strip()[:32])
    page = q.order_by(Voucher.created_at.desc(), Voucher.id.desc()).paginate(page=a.get('page', 1, type=int), per_page=PER_PAGE, error_out=False)
    ids = [v.id for v in page.items]
    phones = {p.voucher_id: p.gift_phone or p.phone for p in Payment.query.filter(Payment.voucher_id.in_(ids))} if ids else {}
    base = A._voucher_query()
    stats = {'unused': base.filter(Voucher.status == 'unused').count(),
             'active': base.filter(Voucher.status == 'active', Voucher.expires_at > now).count(),
             'expired': base.filter(Voucher.status != 'disabled', Voucher.expires_at <= now).count()}
    return jsonify(items=[_voucher_json(v, phones.get(v.id)) for v in page.items], page=page.page, pages=page.pages,
                   total=page.total, stats=stats, currency=A.current_tenant().currency or 'TZS')


@bp.route('/api/m/vouchers/options')
def voucher_options():
    _need_login()
    packages = A.scoped(Package).filter_by(is_active=True).order_by(Package.sort_order, Package.price).all()
    return jsonify(plans=[{'id': p.id, 'name': p.name} for p in A.scoped(Plan).filter_by(is_active=True).order_by(Plan.name)],
                   packages=[{'id': p.id, 'name': p.name, 'minutes': p.validity_minutes, 'price': _money(p.price),
                              'devices': p.max_devices or 1, 'plan_id': p.plan_id} for p in packages],
                   sites=[{'id': s.id, 'name': s.name} for s in A.tenant_sites()])


@bp.route('/api/m/vouchers', methods=['POST'])
def create_vouchers():
    _need_login()
    _no_viewer()
    d = request.get_json(silent=True) or {}
    try:
        count = int(d.get('count', 1))
        minutes = int(d.get('minutes') or 0)
        devices = int(d.get('devices') or 1)
        price = Decimal(str(d['price'])) if d.get('price') not in (None, '') and not d.get('free') else None
    except (ValueError, ArithmeticError):
        return _err(tr('Check the numbers.'), 400)
    package = A.scoped(Package).filter_by(id=d.get('package_id')).first() if d.get('package_id') else None
    plan_id = d.get('plan_id')
    if package is not None:
        minutes, devices, plan_id = package.validity_minutes, package.max_devices or 1, package.plan_id
        price = None if d.get('free') else (price if price is not None else package.price)
    if not 1 <= count <= 500:
        return _err(tr('Make between 1 and 500 vouchers at a time.'), 400)
    if not 1 <= minutes <= 366 * 1440:
        return _err(tr('Choose how long each voucher lasts.'), 400)
    if not 1 <= devices <= 20:
        return _err(tr('Devices: 1 to 20.'), 400)
    if price is not None and price < 0:
        return _err(tr('Check the numbers.'), 400)
    plan = A.scoped(Plan).filter_by(id=plan_id).first() if plan_id else None
    ids = {int(x) for x in d.get('site_ids') or [] if str(x).isdigit()}
    sites = [s for s in A.tenant_sites() if s.id in ids] if ids and len(A.tenant_sites()) > 1 else []
    batch = str(d.get('batch') or '').strip()[:64] or ('Free trial ' if d.get('free') else '') + datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    made = A._create_vouchers(count, plan, minutes, price, batch, max_devices=devices, is_free=bool(d.get('free')),
                              site_id=A.site_for_new_things().id, sites=sites)
    db.session.commit()
    ids = [v.id for v in made]
    A._ruijie_push_now(made)          # Reyee: made on Ruijie Cloud first, so the codes shown are the final ones
    made = Voucher.query.filter(Voucher.id.in_(ids)).order_by(Voucher.id).all()
    return jsonify(batch=batch, items=[_voucher_json(v) for v in made], waiting=sum(1 for v in made if not v.code_final))


@bp.route('/api/m/vouchers/<int:vid>/toggle', methods=['POST'])
def toggle_voucher(vid):
    _need_login()
    _no_viewer()
    v = A.owned_or_404(Voucher, vid)
    if v.status == 'disabled':
        v.status = 'active' if v.first_used_at else 'unused'
        v.disabled_reason = None
    else:
        v.status = 'disabled'
        A.disconnect_subscriber(v.tenant_id, v.code)
    db.session.commit()
    return jsonify(_voucher_json(v))


@bp.route('/api/m/vouchers/<int:vid>', methods=['DELETE'])
def delete_voucher(vid):
    _need_login()
    _no_viewer()
    v = A.owned_or_404(Voucher, vid)
    if v.first_used_at:
        A.disconnect_subscriber(v.tenant_id, v.code)
    for model in (RadCheck, RadReply, RadUserGroup):
        model.query.filter_by(username=v.code).delete()
    db.session.delete(v)
    db.session.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- business: customers
@bp.route('/api/m/customers')
def customers():
    _need_login('admin')
    tenant = A.current_tenant()
    a = request.args
    site_id = a.get('site_id', type=int) or None
    days = a.get('days', type=int) if a.get('days', type=int) in A.OFFER_SMS_DAYS else None
    tag = (a.get('tag') or '').strip()[:40] or None
    state = a.get('state') if a.get('state') in A.CUSTOMER_STATES else None
    quiet = a.get('quiet', type=int) if a.get('quiet', type=int) in A.CUSTOMER_QUIET else None
    search = (a.get('q') or '').strip()[:40]
    q = SmsContact.query.filter(SmsContact.tenant_id == tenant.id)
    if any((site_id, days, tag, state, quiet)):
        q = q.filter(SmsContact.phone.in_(list(A._customer_phones(tenant, site_id, days, tag, state, quiet)) or ['-']))
    if search:
        digits = re.sub(r'\D', '', search)
        conds = [SmsContact.name.ilike(f'%{search}%'), SmsContact.tags.ilike(f'%{search}%')]
        if len(digits) >= 3:
            conds.append(SmsContact.phone.like(f'%{digits.lstrip("0")}%'))
        q = q.filter(or_(*conds))
    page = q.order_by(SmsContact.last_paid_at.is_(None), SmsContact.last_paid_at.desc(), SmsContact.id.desc()).paginate(
        page=a.get('page', 1, type=int), per_page=PER_PAGE, error_out=False)
    active = A._active_phones(tenant.id)
    return jsonify(items=[_customer_json(c, active) for c in page.items], page=page.page, pages=page.pages, total=page.total,
                   everyone=SmsContact.query.filter_by(tenant_id=tenant.id).count(), tags=A._tenant_tags(tenant.id),
                   currency=tenant.currency or 'TZS', choices={'days': list(A.OFFER_SMS_DAYS), 'quiet': list(A.CUSTOMER_QUIET)})


def _customer_json(c, active):
    return {'id': c.id, 'phone': c.phone, 'local_phone': c.local_phone, 'name': c.name, 'purchases': c.purchases or 0,
            'spent': _money(c.spent), 'first_paid': _iso(c.first_paid_at), 'last_paid': _iso(c.last_paid_at),
            'last_package': c.last_package, 'last_site': c.last_site.name if getattr(c, 'last_site', None) else None,
            'tags': c.tag_list, 'note': c.note, 'stopped': c.stopped_at is not None, 'active': c.phone in active}


@bp.route('/api/m/customers/<int:cid>')
def customer(cid):
    _need_login('admin')
    c = A.owned_or_404(SmsContact, cid)
    codes = []
    for v, pay, credits, gift in A._phone_codes(c.tenant_id, c.phone, days=365)[:30]:
        item = A._guest_voucher_json(v)
        item['made_up'] = sum(x.minutes or 0 for x in credits)
        item['gift'] = gift is not None
        item['site'] = _site_name(v.site_id)
        codes.append(item)
    return jsonify(customer=_customer_json(c, A._active_phones(c.tenant_id)), codes=codes)


@bp.route('/api/m/customers/<int:cid>', methods=['POST'])
def edit_customer(cid):
    _need_login('admin')
    c = A.owned_or_404(SmsContact, cid)
    d = request.get_json(silent=True) or {}
    if 'name' in d:
        c.name = re.sub(r'\s+', ' ', str(d.get('name') or '')).strip()[:80] or None
    if 'tags' in d:
        raw = d['tags'] if isinstance(d['tags'], list) else str(d['tags'] or '').split(',')
        tags = [str(t).strip()[:30] for t in raw if str(t).strip()]
        c.tags = ', '.join(dict.fromkeys(tags))[:160] or None
    if 'note' in d:
        c.note = str(d.get('note') or '').strip()[:255] or None
    db.session.commit()
    return jsonify(_customer_json(c, A._active_phones(c.tenant_id)))


# ---------------------------------------------------------------- business: money
@bp.route('/api/m/payments')
def payments():
    _need_login()
    a = request.args
    q = A._site_filters(A.tenant_id(), A.current_site())['payments'](A.scoped(Payment))
    if a.get('status') in ('paid', 'pending', 'failed', 'review'):
        q = q.filter(Payment.status == a['status'])
    search = (a.get('search') or '').strip()[:32]
    if search:
        q = q.filter(or_(Payment.phone.like(f'%{search}%'), Payment.reference.like(f'%{search}%')))
    page = q.order_by(Payment.created_at.desc()).paginate(page=a.get('page', 1, type=int), per_page=PER_PAGE, error_out=False)
    items = [{'id': p.id, 'reference': p.reference, 'phone': p.phone, 'gift_phone': p.gift_phone, 'package': p.package_name,
              'amount': _money(p.amount), 'status': p.status, 'message': p.message, 'created': _iso(p.created_at),
              'paid': _iso(p.paid_at), 'code': p.voucher.code if p.voucher else None,
              'site': _site_name(p.site_id), 'name': getattr(p, 'payer_name', None)} for p in page.items]
    return jsonify(items=items, page=page.page, pages=page.pages, total=page.total, currency=A.current_tenant().currency or 'TZS')


@bp.route('/api/m/earnings')
def earnings():
    _need_login()
    if not (current_user.has_role('admin') or (current_user.is_viewer and not current_user.site_id)):
        abort(403)
    tenant = A.current_tenant()
    balance, earned, withdrawn = A.tenant_balance(tenant.id)
    paid = A.scoped(Payment).filter(Payment.status == 'paid')
    total = lambda col, q=paid: _money(q.with_entities(func.coalesce(func.sum(col), 0)).scalar())
    sms_count, sms_amount = A.sms_totals(tenant.id)
    withdrawals = [{'id': w.id, 'amount': _money(w.amount), 'status': w.status, 'method': getattr(w, 'method', None),
                    'phone': getattr(w, 'phone', None), 'created': _iso(w.created_at)}
                   for w in A.scoped(Withdrawal).order_by(Withdrawal.created_at.desc()).limit(30)]
    return jsonify(currency=tenant.currency or 'TZS', platform=tenant.payment_mode == 'platform',
                   balance=_money(balance), earned=_money(earned), withdrawn=_money(withdrawn),
                   gross=total(Payment.amount), fees=total(Payment.fee_amount, paid.filter(Payment.provider_account == 'platform')),
                   sms={'count': sms_count, 'amount': _money(sms_amount)}, min_withdrawal=A.Config.MIN_WITHDRAWAL,
                   fee_percent=float(A._fee_percent(tenant)), withdrawals=withdrawals)


@bp.route('/api/m/packages')
def packages():
    _need_login('admin')
    items = A.scoped(Package).order_by(Package.sort_order, Package.price).all()
    return jsonify(currency=A.current_tenant().currency or 'TZS', items=[
        {'id': p.id, 'name': p.name, 'description': p.description, 'price': _money(p.price), 'minutes': p.validity_minutes,
         'validity': A.format_minutes(p.validity_minutes), 'devices': p.max_devices or 1, 'active': bool(p.is_active),
         'on_portal': bool(p.show_on_portal), 'site': _site_name(p.site_id)} for p in items])


@bp.route('/api/m/packages/<int:pid>', methods=['POST'])
def edit_package(pid):
    _need_login('admin')
    p = A.owned_or_404(Package, pid)
    d = request.get_json(silent=True) or {}
    if 'active' in d:
        p.is_active = bool(d['active'])
    if 'on_portal' in d:
        p.show_on_portal = bool(d['on_portal'])
    if 'price' in d:
        try:
            price = Decimal(str(d['price']))
        except ArithmeticError:
            return _err(tr('Check the numbers.'), 400)
        if price <= 0:
            return _err(tr('Check the numbers.'), 400)
        p.price = price
    db.session.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- Wi-Fi customers (guests)
OTP_MINUTES = 10
DEVICE_DAYS = 730          # a phone that signed in with an SMS code is remembered this long


def _otp_key(phone, otp):
    secret = A.app.config['SECRET_KEY']
    digest = hashlib.sha256(f'{phone}:{otp}:{secret}'.encode()).hexdigest()[:40]
    return f'{phone}:{digest}'


def _has_bought(phone):
    return Payment.query.filter(Payment.status == 'paid', or_(Payment.phone == phone, Payment.gift_phone == phone)).first() is not None or \
        OutageCredit.query.filter_by(phone=phone).first() is not None


@bp.route('/api/m/guest/send-code', methods=['POST'])
def guest_send_code():
    """Sign in with the phone number alone: SafeNet texts a 6-digit code to a number that has bought Wi-Fi."""
    phone = A._normalize_tz_phone(str((request.get_json(silent=True) or {}).get('phone') or ''))
    if not phone:
        return _err(tr('Enter your phone number, e.g. 0712 345 678.'), 400)
    if not A.sms_is_configured():
        return _err(tr('Sign-in by SMS is not available right now. Sign in with your voucher code.'), 503)
    ip_key, phone_key = f'ip:{A._client_ip()}', f'to:{phone}'
    if A._rate_limited('motpsend', ip_key, 10, 60) or A._rate_limited('motpsend', phone_key, 3, 60):
        return _err(tr('Too many codes asked for. Please wait an hour, or sign in with your voucher code.'), 429)
    if not _has_bought(phone):
        return _err(tr("This number hasn't bought Wi-Fi with SafeNet yet. Sign in with your voucher code."), 404)
    since = datetime.utcnow() - timedelta(minutes=OTP_MINUTES)
    last = RateEvent.query.filter(RateEvent.kind == 'motp', RateEvent.key.like(f'{phone}:%'), RateEvent.created_at >= since) \
        .order_by(RateEvent.created_at.desc()).first()
    if last is not None:            # a code already went out and still works: no second SMS (each one costs)
        left = int(OTP_MINUTES * 60 - (datetime.utcnow() - last.created_at).total_seconds())
        return jsonify(ok=True, phone=phone, minutes=OTP_MINUTES, already_sent=True, seconds_left=max(left, 0))
    A._rate_hit('motpsend', ip_key, phone_key)
    otp = f'{A.secrets.randbelow(900000) + 100000}'
    db.session.add(RateEvent(kind='motp', key=_otp_key(phone, otp)))
    db.session.commit()
    A.send_sms_async(phone, f'SafeNet: {otp} ' + ('ni namba yako ya kuingia. Inaisha baada ya dakika 10.' if request.headers.get('Accept-Language', '').startswith('sw')
                                                  else 'is your sign-in code. It expires in 10 minutes.'))
    return jsonify(ok=True, phone=phone, minutes=OTP_MINUTES, already_sent=False, seconds_left=OTP_MINUTES * 60)


@bp.route('/api/m/guest/login', methods=['POST'])
def guest_login():
    """Sign in with a phone number and the code SafeNet texted to it (sees everything bought by or for that phone),
    or with a voucher code alone (sees that code)."""
    d = request.get_json(silent=True) or {}
    ip_key = f'ip:{A._client_ip()}'
    if A._rate_limited('mguest', ip_key, 10, 15):
        return _err(tr('Too many wrong attempts. Please wait 15 minutes.'), 429)
    phone = A._normalize_tz_phone(str(d.get('phone') or ''))
    otp = re.sub(r'\D', '', str(d.get('otp') or ''))[:6]
    code = re.sub(r'\s+', '', str(d.get('code') or ''))[:32]
    if phone and d.get('devices') is not None and not otp:
        # a phone that proved this number before (with an SMS code) signs in again without a new SMS
        for raw in list(d.get('devices') or [])[:10]:
            try:
                dev = A._tokens('mobile-device').loads(str(raw), max_age=DEVICE_DAYS * 86400)
            except (BadSignature, SignatureExpired):
                continue
            if isinstance(dev, dict) and dev.get('g') == phone:
                return jsonify(token=A._tokens('mobile-guest').dumps({'g': phone}), phone=phone, device=str(raw))
        return jsonify(error=tr('This phone needs a code by SMS the first time.'), need_code=True), 401
    if phone and otp:
        if A._rate_limited('motpbad', f'to:{phone}', 5, 15):
            return _err(tr('Too many wrong attempts. Please wait 15 minutes.'), 429)
        since = datetime.utcnow() - timedelta(minutes=OTP_MINUTES)
        row = RateEvent.query.filter(RateEvent.kind == 'motp', RateEvent.key == _otp_key(phone, otp), RateEvent.created_at >= since).first()
        if row is None:
            A._rate_hit('motpbad', f'to:{phone}')
            A._rate_hit('mguest', ip_key)
            return _err(tr("That code isn't right or has expired. Check the SMS, or ask for a new code."), 401)
        RateEvent.query.filter(RateEvent.kind == 'motp', RateEvent.key.like(f'{phone}:%')).delete(synchronize_session=False)
        db.session.commit()             # each code works once
        device = A._tokens('mobile-device').dumps({'g': phone, 'd': A.secrets.token_hex(8)})
        return jsonify(token=A._tokens('mobile-guest').dumps({'g': phone}), phone=phone, device=device)
    voucher = Voucher.query.filter_by(code=code).first() if code else None
    if voucher is None:
        A._rate_hit('mguest', ip_key)
        return _err(tr("That code isn't valid. Check it and try again."), 401)
    return jsonify(token=A._tokens('mobile-guest').dumps({'v': [voucher.code]}), code=voucher.code)


def _guest_who():
    """(phone, code) of the signed-in customer: one of the two."""
    try:
        data = A._tokens('mobile-guest').loads(_bearer() or '', max_age=GUEST_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        abort(401)
    if not isinstance(data, dict) or not (data.get('g') or data.get('v')):
        abort(401)
    return data.get('g'), data.get('v')


def _business_json(tenant, mine, b_codes, spent, purchases, contact=None):
    hs = A._hotspot_settings(tenant)
    return {'id': tenant.id, 'name': tenant.name, 'support': hs.get('support'),
            'sites': list(dict.fromkeys(n for n in [_site_name(p.site_id) for p in mine] + [c.get('site') for c in b_codes] if n)),
            'spent': spent, 'purchases': purchases, 'currency': tenant.currency or 'TZS',
            'last': _iso(mine[0].paid_at) if mine else None, 'your_name': contact.name if contact else None,
            'buy_url': f'{A.Config.PUBLIC_URL}/app/{tenant.slug}', 'active': sum(1 for c in b_codes if c['state'] == 'active')}


def _history_json(pays, phone=None, limit=None):
    """Purchases, newest first, each with its business and site (so the app can show them per site)."""
    return [{'business': p.tenant.name if p.tenant else '', 'business_id': p.tenant_id, 'site': _site_name(p.site_id), 'site_id': p.site_id,
             'package': p.package_name, 'amount': _money(p.amount), 'currency': p.currency, 'at': _iso(p.paid_at),
             'code': p.voucher.code if p.voucher else None, 'offer': p.offer_name,
             'for': p.gift_phone if phone and p.gift_phone and p.gift_phone != phone else None,
             'from': p.phone if phone and p.gift_phone == phone and p.phone != phone else None} for p in pays[:limit]]


def _places_json(pays, codes, phone=None):
    """Every SafeNet site the customer bought at (or holds codes for): purchases, money spent, last visit, codes running."""
    places = {}
    for p in pays:
        x = places.setdefault((p.tenant_id, p.site_id), {'business': p.tenant.name if p.tenant else '', 'business_id': p.tenant_id,
                                                          'site': _site_name(p.site_id), 'site_id': p.site_id, 'purchases': 0, 'spent': 0.0,
                                                          'currency': p.currency, 'last': None, 'first': None, 'active': 0})
        if not phone or p.phone == phone:           # what they paid (not what friends paid for them)
            x['purchases'] += 1
            x['spent'] += _money(p.amount)
        at = _iso(p.paid_at)
        x['last'] = max(filter(None, (x['last'], at)), default=None)
        x['first'] = min(filter(None, (x['first'], at)), default=None)
    for c in codes:
        x = places.get((c.get('business_id'), c.get('site_id')))
        if x is not None and c['state'] == 'active':
            x['active'] += 1
    return sorted(places.values(), key=lambda x: x['last'] or '', reverse=True)


@bp.route('/api/m/guest/home')
def guest_home():
    phone, code = _guest_who()
    if code:
        return _code_home(code if isinstance(code, list) else [code])
    pays = Payment.query.filter(Payment.status == 'paid', or_(Payment.phone == phone, Payment.gift_phone == phone)) \
        .order_by(Payment.paid_at.desc()).limit(2000).all()
    tenant_ids = list(dict.fromkeys(p.tenant_id for p in pays))
    tenant_ids += [t for (t,) in db.session.query(Outage.tenant_id).join(OutageCredit).filter(OutageCredit.phone == phone).distinct()
                   if t not in tenant_ids]
    businesses, codes, total_spent, total_data = [], [], 0.0, 0
    for tid in tenant_ids:
        tenant = db.session.get(Tenant, tid)
        if tenant is None:
            continue
        mine = [p for p in pays if p.tenant_id == tid]
        spent = sum(_money(p.amount) for p in mine if p.phone == phone)
        b_codes = []
        for v, pay, credits, gift in A._phone_codes(tid, phone, days=3650)[:60]:       # running ones first
            item = A._guest_voucher_json(v)
            item.update(business=tenant.name, business_id=tid, site=_site_name(v.site_id),
                        made_up=sum(x.minutes or 0 for x in credits), gift=gift is not None,
                        bought_for_friend=bool(pay and pay.gift_phone and pay.gift_phone != phone))
            total_data += item['down'] + item['up']
            b_codes.append(item)
        codes += b_codes
        total_spent += spent
        businesses.append(_business_json(tenant, mine, b_codes, spent, len([p for p in mine if p.phone == phone]),
                                         SmsContact.query.filter_by(tenant_id=tid, phone=phone).first()))
    rank = {'active': 0, 'unused': 1, 'expired': 2, 'disabled': 3}
    codes.sort(key=lambda c: (rank.get(c['state'], 9), -(c['seconds_left'] or 0)))
    return jsonify(phone=phone, code=None, spent=total_spent, data=total_data, purchases=len([p for p in pays if p.phone == phone]),
                   businesses=businesses, codes=codes, history=_history_json(pays, phone), places=_places_json(pays, codes, phone))


def _code_home(codes):
    """Signed in with voucher codes: those codes, where they work, what was paid for them."""
    vs = Voucher.query.filter(Voucher.code.in_([str(c)[:32] for c in codes[:20]])).all()
    if not vs:
        abort(401)
    by_tenant, items, pays_all = {}, [], []
    for v in vs:
        tenant = db.session.get(Tenant, v.tenant_id)
        pays = Payment.query.filter_by(voucher_id=v.id, status='paid').all()
        item = A._guest_voucher_json(v)
        credits = OutageCredit.query.filter_by(voucher_id=v.id).all()
        item.update(business=tenant.name, business_id=tenant.id, site=_site_name(v.site_id), made_up=sum(x.minutes or 0 for x in credits),
                    gift=OutageCredit.query.filter_by(gift_voucher_id=v.id).first() is not None, bought_for_friend=False)
        spent = sum(_money(p.amount) for p in pays) or (_money(v.price) if v.price is not None and v.first_used_at else 0.0)
        b = by_tenant.setdefault(tenant.id, {'tenant': tenant, 'pays': [], 'codes': [], 'spent': 0.0})
        b['pays'] += pays
        b['codes'].append(item)
        b['spent'] += spent
        items.append(item)
        pays_all += pays
    rank = {'active': 0, 'unused': 1, 'expired': 2, 'disabled': 3}
    items.sort(key=lambda c: (rank.get(c['state'], 9), -(c['seconds_left'] or 0)))
    pays_all.sort(key=lambda p: p.paid_at or datetime.min, reverse=True)
    businesses = [_business_json(b['tenant'], sorted(b['pays'], key=lambda p: p.paid_at or datetime.min, reverse=True), b['codes'],
                                 b['spent'], len(b['pays'])) for b in by_tenant.values()]
    return jsonify(phone=None, code=vs[0].code, spent=sum(b['spent'] for b in by_tenant.values()),
                   data=sum(x['down'] + x['up'] for x in items), purchases=len(pays_all), businesses=businesses, codes=items,
                   history=_history_json(pays_all), places=_places_json(pays_all, items))



# ================================================================ business: manage (packages, offers, SMS, plans, team, settings, sites)
def _f(d):
    """The app's JSON as form fields, for the dashboard's own form helpers."""
    from werkzeug.datastructures import MultiDict
    return MultiDict({k: ('1' if v is True else '' if v in (False, None) else str(v)) for k, v in (d or {}).items()})


def _local(dt):
    return (dt + A._local_offset()).strftime('%Y-%m-%dT%H:%M') if dt else None


# ---------------------------------------------------------------- packages (full)
def _package_body(p, d):
    name = str(d.get('name') or '').strip()[:64]
    try:
        price = Decimal(str(d.get('price')))
        minutes = int(d.get('minutes') or 0)
        devices = int(d.get('devices') or 1)
    except (ArithmeticError, ValueError, TypeError):
        return tr('Check the numbers.')
    if not name:
        return tr('Give the package a name.')
    if price <= 0 or not 1 <= minutes <= 366 * 1440 or not 1 <= devices <= 20:
        return tr('Check the price, how long it lasts and the devices.')
    site_id = d.get('site_id') or None
    if site_id and not any(x.id == site_id for x in A.tenant_sites()):
        return tr('Choose a site.')
    plan_id = d.get('plan_id') or None
    if plan_id and not A.scoped(Plan).filter_by(id=plan_id).first():
        return tr('Choose a speed plan.')
    p.name, p.price, p.validity_minutes, p.max_devices = name, price, minutes, devices
    p.description = str(d.get('description') or '').strip()[:200] or None
    p.plan_id, p.site_id = plan_id, site_id
    p.is_active = bool(d.get('active', True))
    p.show_on_portal = bool(d.get('on_portal', True))
    p.sort_order = int(d.get('sort_order') or 0)
    return None


@bp.route('/api/m/packages/form')
def package_form():
    _need_login('admin')
    return jsonify(plans=[{'id': p.id, 'name': p.name} for p in A.scoped(Plan).filter_by(is_active=True).order_by(Plan.name)],
                   sites=[{'id': s.id, 'name': s.name} for s in A.tenant_sites()], currency=A.current_tenant().currency or 'TZS')


@bp.route('/api/m/packages/<int:pid>/full')
def package_full(pid):
    _need_login('admin')
    p = A.owned_or_404(Package, pid)
    return jsonify({'id': p.id, 'name': p.name, 'description': p.description, 'price': _money(p.price), 'minutes': p.validity_minutes,
                    'devices': p.max_devices or 1, 'plan_id': p.plan_id, 'site_id': p.site_id, 'active': bool(p.is_active),
                    'on_portal': bool(p.show_on_portal), 'sort_order': p.sort_order or 0})


@bp.route('/api/m/packages/new', methods=['POST'])
def package_new():
    _need_login('admin')
    p = Package(tenant_id=A.tenant_id(), currency=A.current_tenant().currency)
    problem = _package_body(p, request.get_json(silent=True) or {})
    if problem:
        db.session.rollback()
        return _err(problem, 400)
    db.session.add(p)
    db.session.commit()
    A._ruijie_refresh_soon(p)
    return jsonify(ok=True, id=p.id)


@bp.route('/api/m/packages/<int:pid>/save', methods=['POST'])
def package_save(pid):
    _need_login('admin')
    p = A.owned_or_404(Package, pid)
    problem = _package_body(p, request.get_json(silent=True) or {})
    if problem:
        db.session.rollback()
        return _err(problem, 400)
    db.session.commit()
    A._ruijie_refresh_soon(p)
    return jsonify(ok=True, id=p.id)


@bp.route('/api/m/packages/<int:pid>', methods=['DELETE'])
def package_delete(pid):
    _need_login('admin')
    p = A.owned_or_404(Package, pid)
    db.session.delete(p)
    db.session.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- offers
def _offer_json(o, sold=0):
    now = datetime.utcnow()
    return {'id': o.id, 'name': o.name, 'package_id': o.package_id, 'package': o.package.name if o.package else None,
            'site_id': o.site_id, 'site': _site_name(o.site_id), 'bonus_minutes': o.bonus_minutes or 0,
            'discount_percent': o.discount_percent or 0, 'starts': _local(o.starts_at), 'ends': _local(o.ends_at),
            'active': bool(o.is_active), 'live': bool(o.live(now)), 'ended': bool(o.ends_at and o.ends_at <= now), 'sold': sold}


@bp.route('/api/m/offers')
def offers():
    _need_login('admin')
    tid = A.tenant_id()
    sold = dict(db.session.query(Payment.offer_id, func.count(Payment.id)).filter(
        Payment.tenant_id == tid, Payment.status == 'paid', Payment.offer_id.isnot(None)).group_by(Payment.offer_id))
    items = A.scoped(A.Offer).order_by(A.Offer.id.desc()).all()
    return jsonify(items=[_offer_json(o, sold.get(o.id, 0)) for o in items],
                   packages=[{'id': p.id, 'name': p.name, 'price': _money(p.price), 'minutes': p.validity_minutes}
                             for p in A.scoped(Package).filter_by(is_active=True).order_by(Package.sort_order, Package.price)],
                   sites=[{'id': s.id, 'name': s.name} for s in A.tenant_sites()], currency=A.current_tenant().currency or 'TZS')


def _offer_fields(d):
    """App fields -> the dashboard form's fields (extra time in hours, dates as local yyyy-mm-ddThh:mm)."""
    minutes = int(d.get('bonus_minutes') or 0)
    days = minutes % 1440 == 0
    return _f({'name': d.get('name'), 'package_id': d.get('package_id'), 'site_id': d.get('site_id'),
               'bonus_value': minutes // (1440 if days else 60), 'bonus_unit': 'days' if days else 'hours',
               'discount_percent': d.get('discount_percent'), 'starts_at': d.get('starts'), 'ends_at': d.get('ends'),
               'is_active': d.get('active', True)})


@bp.route('/api/m/offers', methods=['POST'])
@bp.route('/api/m/offers/<int:oid>', methods=['POST'])
def offer_save(oid=None):
    _need_login('admin')
    offer = A.owned_or_404(A.Offer, oid) if oid else A.Offer(tenant_id=A.tenant_id())
    problem = A._offer_from_form(offer, _offer_fields(request.get_json(silent=True) or {}))
    if problem:
        db.session.rollback()
        return _err(problem, 400)
    if not oid:
        db.session.add(offer)
    db.session.commit()
    A._ruijie_refresh_soon(offer)
    return jsonify(_offer_json(offer))


@bp.route('/api/m/offers/<int:oid>/toggle', methods=['POST'])
def offer_toggle(oid):
    _need_login('admin')
    offer = A.owned_or_404(A.Offer, oid)
    offer.is_active = not offer.is_active
    db.session.commit()
    return jsonify(_offer_json(offer))


@bp.route('/api/m/offers/<int:oid>', methods=['DELETE'])
def offer_delete(oid):
    _need_login('admin')
    offer = A.owned_or_404(A.Offer, oid)
    Payment.query.filter_by(offer_id=offer.id).update({'offer_id': None}, synchronize_session=False)
    db.session.delete(offer)
    db.session.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- SMS to customers
def _sms_choices(d):
    sites = A.tenant_sites()
    site_id = d.get('site_id') or None
    if site_id and not any(x.id == site_id for x in sites):
        site_id = None
    days = d.get('days') if d.get('days') in A.OFFER_SMS_DAYS else None
    tag = str(d.get('tag') or '').strip()[:40] or None
    state = d.get('state') if d.get('state') in A.CUSTOMER_STATES else None
    quiet = d.get('quiet') if d.get('quiet') in A.CUSTOMER_QUIET else None
    ids = sorted({int(x) for x in d.get('ids') or [] if str(x).isdigit()})[:A.OFFER_SMS_MAX_PHONES]
    return site_id, days, tag, state, quiet, ids


@bp.route('/api/m/sms', methods=['POST'])
def sms_compose():
    """Who would get the message with these choices, what it costs, and (action=send) send it."""
    _need_login('admin')
    tenant = A.current_tenant()
    d = request.get_json(silent=True) or {}
    site_id, days, tag, state, quiet, ids = _sms_choices(d)
    live_offers = [o for o in A.scoped(A.Offer).order_by(A.Offer.id.desc()).all() if o.is_active and (o.ends_at is None or o.ends_at > datetime.utcnow())]
    suggestions = A._offer_suggestions(tenant, live_offers)
    offer_id = d.get('offer_id') if d.get('offer_id') in suggestions else None
    text = str(d.get('text') or '').strip()
    phones, stopped, recent = A._offer_sms_audience(tenant, site_id, days, tag, state, quiet, ids)
    if isinstance(d.get('phones'), list):                     # the owner unticked some
        ticked = {str(p) for p in d['phones']}
        phones = [p for p in phones if p in ticked]
    sample = A._offer_sms_text(tenant, text or '…', 'abcdefg')
    parts = A.sms_parts(sample)
    cost = Decimal(len(phones) * parts * A.Config.SMS_PRICE)
    balance = A.tenant_balance(tenant.id)[0] if tenant.payment_mode == 'platform' else None
    names = {c.phone: c.name for c in SmsContact.query.filter(SmsContact.tenant_id == tenant.id, SmsContact.phone.in_(phones or ['-']))}
    out = dict(count=len(phones), stopped=stopped, recent=recent, parts=parts, cost=_money(cost), price=A.Config.SMS_PRICE,
               balance=_money(balance) if balance is not None else None, currency=tenant.currency or 'TZS', sample=sample,
               max_text=A.OFFER_SMS_MAX_TEXT, ready=A.sms_is_configured(),
               people=[{'phone': p, 'local': A.portal_ui.local_phone(p), 'name': names.get(p)}
                       for p in phones[:500]],
               offers=[{'id': o.id, 'name': o.name, 'text': suggestions[o.id]} for o in live_offers],
               sites=[{'id': s.id, 'name': s.name} for s in A.tenant_sites()], tags=A._tenant_tags(tenant.id),
               choices={'days': list(A.OFFER_SMS_DAYS), 'quiet': list(A.CUSTOMER_QUIET)})
    if d.get('action') != 'send':
        return jsonify(out)
    sending = SmsCampaignQ(tenant.id)
    problem = None
    if not A.sms_is_configured():
        problem = tr('SMS is not available right now. Contact SafeNet.')
    elif not text:
        problem = tr('Write the message.')
    elif len(text) > A.OFFER_SMS_MAX_TEXT:
        problem = tr('The message can be up to {n} characters.', n=A.OFFER_SMS_MAX_TEXT)
    elif not phones:
        problem = tr('No customers to send to: nobody has paid yet with these choices, or they all got an offer in the last 24 hours.')
    elif len(phones) > A.OFFER_SMS_MAX_PHONES:
        problem = tr('Up to {n} customers per send: choose one site or fewer days.', n=A.OFFER_SMS_MAX_PHONES)
    elif balance is not None and cost > balance:
        problem = tr('Your SafeNet Pay balance ({cur} {balance}) is less than the cost ({cur} {cost}).', cur=tenant.currency or 'TZS',
                     balance=f'{balance:,.0f}', cost=f'{cost:,.0f}')
    elif sending:
        problem = tr('Your last offer is still being sent. Try again when it has finished.')
    if problem:
        return _err(problem, 400)
    tokens = A._sms_contacts(tenant.id, phones)
    campaign = A.SmsCampaign(tenant_id=tenant.id, site_id=site_id, offer_id=offer_id, kind='offer' if offer_id else 'notice',
                             text=text, days=days, recipients=len(phones), parts=parts, status='sending', created_by_id=current_user.id)
    db.session.add(campaign)
    db.session.commit()
    targets = [(p, A._offer_sms_text(tenant, text, tokens[p])) for p in phones]
    A.threading.Thread(target=A._send_offer_campaign, args=(campaign.id, targets), daemon=True).start()
    out['sent'] = len(phones)
    return jsonify(out)


def SmsCampaignQ(tid):
    return A.SmsCampaign.query.filter(A.SmsCampaign.tenant_id == tid, A.SmsCampaign.status == 'sending',
                                      A.SmsCampaign.created_at >= datetime.utcnow() - timedelta(hours=2)).first()


@bp.route('/api/m/sms/history')
def sms_history():
    _need_login('admin')
    rows = A.SmsCampaign.query.filter_by(tenant_id=A.tenant_id()).order_by(A.SmsCampaign.id.desc()).limit(30).all()
    return jsonify(currency=A.current_tenant().currency or 'TZS', items=[
        {'id': c.id, 'kind': c.kind, 'text': c.text, 'recipients': c.recipients, 'sent': c.sent or 0, 'amount': _money(c.amount),
         'status': c.status, 'at': _iso(c.created_at), 'site': _site_name(c.site_id)} for c in rows])


# ---------------------------------------------------------------- speed plans
def _plan_json(p):
    return {'id': p.id, 'name': p.name, 'description': p.description, 'down': p.download_speed, 'up': p.upload_speed,
            'active': bool(p.is_active), 'cap_gb': int(p.data_cap / 1073741824) if p.data_cap else None, 'cap_period': p.data_cap_period}


SPEED = re.compile(r'^\d{1,5}(\.\d{1,2})?[kKmMgG]$')


def _plan_body(p, d):
    name = str(d.get('name') or '').strip()[:64]
    down, up = str(d.get('down') or '').strip(), str(d.get('up') or '').strip()
    if not name:
        return tr('Give the plan a name.')
    if A.scoped(Plan).filter(Plan.name == name, Plan.id != (p.id or 0)).first():
        return tr('Plan name already exists.')
    for v in (down, up):
        if v and not SPEED.match(v):
            return tr('Speeds look like 2M (2 megabits a second) or 512k.')
    try:
        cap = int(d.get('cap_gb') or 0)
    except (ValueError, TypeError):
        return tr('Check the numbers.')
    p.name, p.download_speed, p.upload_speed = name, down.upper() if down else None, up.upper() if up else None
    p.description = str(d.get('description') or '').strip()[:500] or None
    p.is_active = bool(d.get('active', True))
    if cap > 0:
        p.data_cap = cap * 1073741824
        p.data_cap_period = d.get('cap_period') if d.get('cap_period') in ('daily', 'weekly', 'monthly') else 'monthly'
        p.last_reset = p.last_reset or datetime.utcnow()
    else:
        p.data_cap, p.data_cap_period = None, None
    return None


@bp.route('/api/m/plans')
def plans():
    _need_login('admin')
    return jsonify(items=[_plan_json(p) for p in A.scoped(Plan).order_by(Plan.name)])


@bp.route('/api/m/plans', methods=['POST'])
@bp.route('/api/m/plans/<int:pid>', methods=['POST'])
def plan_save(pid=None):
    _need_login('admin')
    d = request.get_json(silent=True) or {}
    if pid:
        p = A.owned_or_404(Plan, pid)
    else:
        p = Plan(tenant_id=A.tenant_id(), vendor='standard', group_name=A._new_group_name(str(d.get('name') or 'plan')[:64]))
    problem = _plan_body(p, d)
    if problem:
        db.session.rollback()
        return _err(problem, 400)
    if not pid:
        db.session.add(p)
        db.session.flush()
    A._sync_plan_rate_limit(p)
    db.session.commit()
    return jsonify(_plan_json(p))


@bp.route('/api/m/plans/<int:pid>', methods=['DELETE'])
def plan_delete(pid):
    _need_login('admin')
    p = A.owned_or_404(Plan, pid)
    for model in (A.RadGroupCheck, A.RadGroupReply, RadUserGroup):
        model.query.filter_by(groupname=p.group_name).delete()
    db.session.delete(p)
    db.session.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- team
ROLE_LABELS = {'owner': 'Owner', 'admin': 'Admin', 'staff': 'Staff', 'viewer': 'Partner (view only)'}


@bp.route('/api/m/team')
def team():
    _need_login('admin')
    members = A.scoped(Admin).order_by(Admin.created_at).all()
    owner = current_user.is_superadmin or current_user.role == 'owner'
    return jsonify(items=[{'id': m.id, 'username': m.username, 'email': m.email, 'role': m.role, 'role_label': tr(ROLE_LABELS.get(m.role, m.role)),
                           'active': bool(m.is_active), 'site': _site_name(m.site_id), 'last_login': _iso(m.last_login),
                           'me': m.id == current_user.id, 'manageable': A._manageable(m)} for m in members],
                   roles=[r for r in ('staff', 'admin', 'viewer') if owner or r == 'staff'],
                   sites=[{'id': s.id, 'name': s.name} for s in A.tenant_sites()])


@bp.route('/api/m/team', methods=['POST'])
def team_add():
    _need_login('admin')
    d = request.get_json(silent=True) or {}
    owner = current_user.is_superadmin or current_user.role == 'owner'
    role = d.get('role') if d.get('role') in (('staff', 'admin', 'viewer') if owner else ('staff',)) else None
    username, email, password = str(d.get('username') or '').strip(), str(d.get('email') or '').strip().lower(), str(d.get('password') or '')
    if role is None:
        return _err(tr('Choose a role.'), 400)
    if not 3 <= len(username) <= 64 or not re.match(r'^[a-zA-Z0-9_.-]+$', username):
        return _err(tr('Use letters, numbers, dots, hyphens and underscores only (at least 3).'), 400)
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) or len(email) > 120:
        return _err(tr('Enter a valid email address.'), 400)
    if not 8 <= len(password) <= 128:
        return _err(tr('The temporary password needs at least 8 characters.'), 400)
    if role != 'viewer' and A._plan_limit_reached(A.current_tenant(), 'staff'):
        return _err(tr('Your plan does not allow more staff accounts. Upgrade on the Billing page.'), 400)
    if Admin.query.filter_by(username=username).first():
        return _err(tr('That username is taken.'), 400)
    if Admin.query.filter(func.lower(Admin.email) == email).first():
        return _err(tr('That email already has an account.'), 400)
    site_id = d.get('site_id') if role == 'viewer' and any(x.id == d.get('site_id') for x in A.tenant_sites()) else None
    m = Admin(username=username, email=email, tenant_id=A.tenant_id(), role=role, email_verified_at=datetime.utcnow(), site_id=site_id)
    m.set_password(password)
    db.session.add(m)
    db.session.commit()
    tenant = A.current_tenant()
    A.send_mail(email, f'You were added to {tenant.name} on SafeNet',
                f'Hi {m.username},\n\n{current_user.username} added you to {tenant.name}.\n'
                f'Log in at {A.Config.PUBLIC_URL}/login (or in the SafeNet app) with username "{m.username}" and the temporary '
                f'password they gave you, then change it with "Forgot password".\n')
    return jsonify(ok=True, id=m.id)


@bp.route('/api/m/team/<int:mid>/toggle', methods=['POST'])
def team_toggle(mid):
    _need_login('admin')
    m = A.owned_or_404(Admin, mid)
    if not A._manageable(m):
        abort(403)
    m.is_active = not m.is_active
    db.session.commit()
    return jsonify(ok=True, active=m.is_active)


@bp.route('/api/m/team/<int:mid>', methods=['DELETE'])
def team_delete(mid):
    _need_login('admin')
    m = A.owned_or_404(Admin, mid)
    if not A._manageable(m):
        abort(403)
    db.session.delete(m)
    db.session.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- business settings
@bp.route('/api/m/settings')
def settings():
    _need_login('admin')
    t = A.current_tenant()
    return jsonify(name=t.name, hotspot_name=t.hotspot_name, support_phone=t.support_phone, phone=t.phone, phone_pending=t.phone_pending,
                   currency=t.currency, terms=t.terms, block_tethering=bool(t.block_tethering), sms_to_guests=bool(t.sms_to_guests),
                   notify_phone=t.notify_phone, sale_sms=bool(t.notify_sale_sms), daily_sms=bool(t.notify_daily_sms),
                   daily_email=bool(t.notify_daily_email), owner=current_user.has_role('owner'), sms_price=A.Config.SMS_PRICE)


@bp.route('/api/m/settings', methods=['POST'])
def settings_save():
    _need_login('admin')
    t = A.current_tenant()
    d = request.get_json(silent=True) or {}
    if 'name' in d:
        name = re.sub(r'\s+', ' ', str(d['name'] or '')).strip()[:100]
        if not name:
            return _err(tr('Enter your business name.'), 400)
        t.name = name
    for key, size in (('hotspot_name', 64), ('support_phone', 32), ('terms', 4000)):
        if key in d:
            setattr(t, key, str(d[key] or '').strip()[:size] or None)
    if 'block_tethering' in d:
        t.block_tethering = bool(d['block_tethering'])
    if current_user.has_role('owner'):
        if 'notify_phone' in d:
            raw = str(d['notify_phone'] or '').strip()
            phone = A._normalize_tz_phone(raw) if raw else None
            if raw and not phone:
                db.session.rollback()
                return _err(tr('Enter a valid mobile number for alerts, e.g. 0712 345 678.'), 400)
            t.notify_phone = phone
        for key, col in (('sale_sms', 'notify_sale_sms'), ('daily_sms', 'notify_daily_sms'), ('daily_email', 'notify_daily_email')):
            if key in d:
                setattr(t, col, bool(d[key]))
        if (t.notify_sale_sms or t.notify_daily_sms) and not A._owner_phone(t):
            db.session.rollback()
            return _err(tr('Add the mobile number the alerts should go to.'), 400)
    db.session.commit()
    return settings()


# ---------------------------------------------------------------- sites and devices
@bp.route('/api/m/sites')
def sites():
    _need_login()
    tid = A.tenant_id()
    now = datetime.utcnow()
    midnight = A._local_midnight_utc()
    month_start = (now + A._local_offset()).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - A._local_offset()
    rows = []
    items = A.tenant_sites(tid)
    if current_user.site_id and not current_user.is_superadmin:
        items = [s for s in items if s.id == current_user.site_id]
    for site in items:
        view = A._site_filters(tid, site)
        online = view['sessions'](RadAcct.query.filter(RadAcct.acctstoptime.is_(None), func.coalesce(
            RadAcct.acctupdatetime, RadAcct.acctstarttime) >= now - timedelta(minutes=A.LIVE_STALE_MINUTES))).count()
        if site.ruijie_clients and site.ruijie_clients_at and (now - site.ruijie_clients_at).total_seconds() < 300:
            online += len(A.json.loads(site.ruijie_clients))
        kind = 'Reyee' if site.ruijie_ready else 'Omada' if getattr(site, 'omada_site_id', None) or getattr(site, 'omada_enabled', False) else \
            'Ruijie' if site.wifidog_enabled else None
        rows.append({'id': site.id, 'name': site.name, 'kind': kind, 'online': online,
                     'today': _money(A._collected(tid, site, midnight)['total']), 'month': _money(A._collected(tid, site, month_start)['total'])})
    devices = []
    for gw in A.scoped(A.Gateway).order_by(A.Gateway.name):
        devices.append({'name': gw.name, 'kind': 'Gateway', 'site': _site_name(gw.site_id), 'last': _iso(gw.last_seen_at),
                        'state': A._device_state(gw.last_seen_at, now) if gw.is_active else 'offline'})
    for r in A.scoped(A.Router).order_by(A.Router.name):
        devices.append({'name': r.name, 'kind': 'MikroTik' if r.vendor == 'mikrotik' else 'Router', 'site': _site_name(r.site_id),
                        'last': _iso(r.last_handshake_at), 'state': A._device_state(r.last_handshake_at, now) if r.is_active else 'offline'})
    for st in items:
        if st.wifidog_enabled:
            devices.append({'name': tr('{site} access points', site=st.name), 'kind': 'Ruijie', 'site': st.name, 'last': _iso(st.wifidog_seen_at),
                            'state': A._device_state(st.wifidog_seen_at, now)})
        if st.ruijie_ready:
            seen = st.ruijie_clients_at
            devices.append({'name': tr('{site} on Ruijie Cloud', site=st.name), 'kind': 'Reyee', 'site': st.name, 'last': _iso(seen),
                            'state': 'online' if seen and (now - seen).total_seconds() < 900 else 'degraded' if seen else 'offline'})
    return jsonify(sites=rows, devices=devices, currency=A.current_tenant().currency or 'TZS')


@bp.route('/api/m/sites', methods=['POST'])
@bp.route('/api/m/sites/<int:sid>', methods=['POST'])
def site_save(sid=None):
    _need_login('admin')
    name = re.sub(r'\s+', ' ', str((request.get_json(silent=True) or {}).get('name') or '')).strip()[:64]
    if not name:
        return _err(tr('Give the site a name.'), 400)
    if sid:
        site = A.owned_or_404(Site, sid)
        site.name = name
    else:
        if A._plan_limit_reached(A.current_tenant(), 'sites'):
            return _err(tr('Your plan does not allow more sites. Upgrade on the Billing page.'), 400)
        site = Site(tenant_id=A.tenant_id(), name=name)
        db.session.add(site)
    db.session.commit()
    return jsonify(ok=True, id=site.id)



# ---------------------------------------------------------------- guests: buy a package in the app
def _guest_tenants(phone, codes):
    """The businesses a signed-in customer may buy from: the ones they bought from (or hold codes of)."""
    if phone:
        ids = {t for (t,) in db.session.query(Payment.tenant_id).filter(Payment.status == 'paid', or_(Payment.phone == phone, Payment.gift_phone == phone)).distinct()}
        ids |= {t for (t,) in db.session.query(Outage.tenant_id).join(OutageCredit).filter(OutageCredit.phone == phone).distinct()}
        return ids
    return {t for (t,) in db.session.query(Voucher.tenant_id).filter(Voucher.code.in_([str(c)[:32] for c in codes[:20]])).distinct()}


def _guest_codes(phone, codes, tenant):
    if phone:
        return [v for v, *_ in A._phone_codes(tenant.id, phone, days=90)]
    return Voucher.query.filter(Voucher.tenant_id == tenant.id, Voucher.code.in_([str(c)[:32] for c in codes[:20]])).all()


def _shop_site(tenant, mine, wanted):
    sites = A.tenant_sites(tenant.id)
    if wanted and any(x.id == wanted for x in sites):
        return wanted
    return next((v.site_id for v in mine if v.site_id), None) or sites[0].id


HERE_DAYS = 3                 # a site's address counts for this long after it was last seen
HERE_MINUTES = 120            # the "you are here" pass lasts this long


@bp.route('/api/m/here')
def here():
    """Which SafeNet Wi-Fi is this phone on? Its request comes from the site's internet address, which SafeNet saw on
    that site's login pages, access points or gateway box. Also before the guest has paid (SafeNet is reachable then)."""
    ip = A._client_ip()
    since = datetime.utcnow() - timedelta(days=HERE_DAYS)
    rows = A.SiteAddress.query.filter(A.SiteAddress.ip == ip, A.SiteAddress.seen_at >= since) \
        .order_by(A.SiteAddress.seen_at.desc()).limit(20).all()
    sites = [db.session.get(Site, r.site_id) for r in rows]
    sites = [x for x in sites if x is not None]
    tenants = {x.tenant_id for x in sites}
    if len(tenants) != 1:             # none, or an address several businesses share (one ISP's shared address): don't guess
        return jsonify(found=False, ambiguous=len(tenants) > 1)
    site = sites[0]
    tenant = db.session.get(Tenant, site.tenant_id)
    if tenant is None or A.tenant_blocked(tenant):
        return jsonify(found=False, ambiguous=False)
    hs = A._hotspot_settings(tenant)
    packages = A._guest_packages(tenant, site.id)
    return jsonify(found=True, business={'id': tenant.id, 'name': hs.get('name') or tenant.name, 'support': hs.get('support')},
                   site={'id': site.id, 'name': site.name}, reyee=bool(site.ruijie_ready),
                   can_buy=A.paylib.is_ready(A._tenant_account(tenant)) and bool(packages),
                   cheapest=min((float(p['price']) for p in packages), default=None), currency=tenant.currency or 'TZS',
                   here=A._tokens('mobile-here').dumps({'t': tenant.id, 's': site.id}))


def _here_pass():
    """The "you are on this SafeNet Wi-Fi" pass the app got from /api/m/here: {'t': business, 's': site}, or None."""
    raw = request.headers.get('X-Here') or ''
    if not raw:
        return None
    try:
        data = A._tokens('mobile-here').loads(raw, max_age=HERE_MINUTES * 60)
    except (BadSignature, SignatureExpired):
        return None
    return data if isinstance(data, dict) and data.get('t') else None


def _who_codes():
    """(phone, codes, here) of who is buying: a signed-in customer, and/or someone on a SafeNet Wi-Fi right now."""
    phone, codes = None, []
    here = _here_pass()
    if _bearer():
        try:
            phone, code = _guest_who()
            codes = code if isinstance(code, list) else [code] if code else []
        except Exception:
            if here is None:
                raise
    elif here is None:
        abort(401)
    return phone, codes, here


def _allowed(phone, codes, here):
    ids = _guest_tenants(phone, codes) if (phone or codes) else set()
    if here:
        ids.add(here['t'])
    return ids


@bp.route('/api/m/guest/shop/<int:tid>')
def guest_shop(tid):
    phone, codes, here = _who_codes()
    if tid not in _allowed(phone, codes, here):
        abort(404)
    tenant = db.session.get(Tenant, tid)
    if tenant is None or A.tenant_blocked(tenant):
        abort(404)
    mine = _guest_codes(phone, codes, tenant)
    wanted = request.args.get('site_id', type=int) or (here['s'] if here and here['t'] == tid else None)
    site_id = _shop_site(tenant, mine, wanted)
    packages = A._guest_packages(tenant, site_id)
    payer = phone or next((p.phone for p in Payment.query.filter(Payment.voucher_id.in_([v.id for v in mine] or [0]), Payment.status == 'paid')), None)
    networks = [{**n, 'logo': f"{A.Config.PUBLIC_URL}/static/img/{A.portal_ui.NETWORKS[n['id']]['logo']}",
                 'prefixes': list(A.portal_ui.NETWORKS[n['id']]['prefixes'])} for n in A.payment_networks(tenant)]
    hs = A._hotspot_settings(tenant)
    return jsonify(business={'id': tenant.id, 'name': tenant.name, 'support': hs.get('support')}, site_id=site_id,
                   sites=[{'id': x.id, 'name': x.name} for x in A.tenant_sites(tenant.id)], packages=packages, networks=networks,
                   can_buy=A.paylib.is_ready(A._tenant_account(tenant)) and bool(packages), can_gift=A._sms_on(tenant),
                   phone=payer, reyee=bool(db.session.get(Site, site_id).ruijie_ready))


@bp.route('/api/m/guest/buy', methods=['POST'])
def guest_buy():
    """Buy a package from the app (the PIN prompt goes to the phone given), for this customer or a friend."""
    phone, codes, here = _who_codes()
    d = request.get_json(silent=True) or {}
    tid = d.get('business_id')
    if tid not in _allowed(phone, codes, here):
        abort(404)
    tenant = db.session.get(Tenant, tid)
    if tenant is None or A.tenant_blocked(tenant):
        abort(404)
    ip_key = f'ip:{A._client_ip()}'
    if A._rate_limited('appbuy', ip_key, 6, 10):
        return _err(tr('Too many payment requests. Please wait a few minutes.'), 429)
    mine = _guest_codes(phone, codes, tenant)
    site_id = _shop_site(tenant, mine, d.get('site_id') or (here['s'] if here and here['t'] == tid else None))
    package = A._site_packages(Package.query.filter_by(id=d.get('package_id'), tenant_id=tenant.id, is_active=True, show_on_portal=True),
                               site_id).first()
    if package is None:
        return _err(tr('Choose a package.'), 400)
    gift = str(d.get('gift_phone') or '') if d.get('gift') else None
    mac = None
    if not gift:      # for this customer: the last device that used one of their codes reconnects by itself
        last = RadAcct.query.filter(RadAcct.username.in_([v.code for v in mine])).order_by(RadAcct.acctstarttime.desc()).first() if mine else None
        mac = last.callingstationid if last else None
    A._rate_hit('appbuy', ip_key)
    payment, error, status = A._start_purchase(tenant, site_id, package, str(d.get('phone') or ''), str(d.get('network') or '')[:16] or None,
                                               mac=mac, nas='mobile-app', gift_phone=gift)
    if error:
        return _err(error, status)
    return jsonify(reference=payment.reference, amount=_money(payment.charged), currency=payment.currency, phone=payment.phone,
                   package=payment.package_name, gift_phone=payment.gift_phone or '')


@bp.route('/api/m/guest/pay/<reference>')
def guest_pay(reference):
    """Is the payment through? Then its code (and, signed in with codes, a token that holds the new one too)."""
    phone, codes, here = _who_codes()
    payment = Payment.query.filter_by(reference=reference[:20], nas_identifier='mobile-app').first()
    if payment is None or payment.tenant_id not in _allowed(phone, codes, here):
        abort(404)
    payment = A._refresh_payment(payment.reference)
    out = {'status': payment.status, 'message': payment.message or '', 'gift_phone': payment.gift_phone or '',
           'package': payment.package_name, 'amount': _money(payment.charged), 'currency': payment.currency}
    if payment.status == 'paid' and payment.voucher:
        v = payment.voucher
        out.update(code=v.code if not payment.gift_phone else None, minutes=v.validity_minutes,
                   reyee=v.ruijie_state is not None, ready=v.ruijie_state not in ('pending', 'sending', 'catchup'))
        if not out['ready']:
            A._ruijie_push_soon()
        if not phone and not payment.gift_phone and v.code not in codes:
            out['token'] = A._tokens('mobile-guest').dumps({'v': (codes + [v.code])[-20:]})
    return jsonify(out)
