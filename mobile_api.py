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


def _guest_phone():
    token = _bearer()
    try:
        data = A._tokens('mobile-guest').loads(token or '', max_age=GUEST_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        abort(401)
    phone = data.get('g') if isinstance(data, dict) else None
    if not phone:
        abort(401)
    return phone


# ---------------------------------------------------------------- request setup and errors
@bp.before_request
def _setup():
    g.mobile = True
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
        return _err(tr('Confirm your email first: open the link we sent to {email}.', email=admin.email), 403)
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
    return {'id': v.id, 'code': v.code, 'state': v.state, 'batch': v.batch, 'plan': v.plan.name if v.plan else None,
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
    A._ruijie_push_soon()
    return jsonify(batch=batch, items=[_voucher_json(v) for v in made])


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
@bp.route('/api/m/guest/login', methods=['POST'])
def guest_login():
    """Phone number + a code bought with it (or for it): proves the phone is theirs."""
    d = request.get_json(silent=True) or {}
    ip_key = f'ip:{A._client_ip()}'
    if A._rate_limited('mguest', ip_key, 10, 15):
        return _err(tr('Too many wrong attempts. Please wait 15 minutes.'), 429)
    phone = A._normalize_tz_phone(str(d.get('phone') or ''))
    code = re.sub(r'\s+', '', str(d.get('code') or ''))[:32]
    ok = False
    if phone and code:
        v = Voucher.query.filter_by(code=code).first()
        if v is not None:
            ok = Payment.query.filter(Payment.voucher_id == v.id, Payment.status == 'paid',
                                      or_(Payment.phone == phone, Payment.gift_phone == phone)).first() is not None or \
                 OutageCredit.query.filter_by(gift_voucher_id=v.id, phone=phone).first() is not None
    if not ok:
        A._rate_hit('mguest', ip_key)
        return _err(tr("That phone number and code don't match. Use a code you paid for with this number."), 401)
    return jsonify(token=A._tokens('mobile-guest').dumps({'g': phone}), phone=phone)


@bp.route('/api/m/guest/home')
def guest_home():
    phone = _guest_phone()
    pays = Payment.query.filter(Payment.status == 'paid', or_(Payment.phone == phone, Payment.gift_phone == phone)) \
        .order_by(Payment.paid_at.desc()).limit(500).all()
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
        sites = list(dict.fromkeys(n for n in (_site_name(p.site_id) for p in mine) if n))
        contact = SmsContact.query.filter_by(tenant_id=tid, phone=phone).first()
        hs = A._hotspot_settings(tenant)
        b_codes = []
        for v, pay, credits, gift in A._phone_codes(tid, phone, days=90):
            item = A._guest_voucher_json(v)
            item.update(business=tenant.name, business_id=tid, site=_site_name(v.site_id),
                        made_up=sum(x.minutes or 0 for x in credits), gift=gift is not None,
                        bought_for_friend=bool(pay and pay.gift_phone and pay.gift_phone != phone))
            total_data += item['down'] + item['up']
            b_codes.append(item)
        codes += b_codes
        total_spent += spent
        businesses.append({'id': tid, 'name': tenant.name, 'support': hs.get('support'), 'sites': sites, 'spent': spent,
                           'purchases': len([p for p in mine if p.phone == phone]), 'currency': tenant.currency or 'TZS',
                           'last': _iso(mine[0].paid_at) if mine else None, 'your_name': contact.name if contact else None,
                           'buy_url': f'{A.Config.PUBLIC_URL}/app/{tenant.slug}',
                           'active': sum(1 for c in b_codes if c['state'] == 'active')})
    rank = {'active': 0, 'unused': 1, 'expired': 2, 'disabled': 3}
    codes.sort(key=lambda c: (rank.get(c['state'], 9), -(c['seconds_left'] or 0)))
    history = [{'business': p.tenant.name if p.tenant else '', 'site': _site_name(p.site_id),
                'package': p.package_name, 'amount': _money(p.amount), 'currency': p.currency, 'at': _iso(p.paid_at),
                'code': p.voucher.code if p.voucher else None, 'for': p.gift_phone if p.gift_phone and p.gift_phone != phone else None,
                'from': p.phone if p.gift_phone == phone and p.phone != phone else None} for p in pays[:50]]
    return jsonify(phone=phone, spent=total_spent, data=total_data, purchases=len([p for p in pays if p.phone == phone]),
                   businesses=businesses, codes=codes, history=history)
