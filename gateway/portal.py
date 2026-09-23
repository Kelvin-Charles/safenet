#!/usr/bin/env python3
"""SafeNet captive portal gateway.

Runs on the machine between the guest Wi-Fi and the internet. Unknown
devices are held on the splash page by nftables (see safenet-gw-firewall);
this server checks their voucher or username/password with SafeNet over
RADIUS and opens the firewall for that device until the Session-Timeout
SafeNet returns. Sessions are reported back with RADIUS accounting.

Standard library only; configured from /etc/safenet-gateway/gateway.env.
"""
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import portal_ui as ui

log = logging.getLogger('safenet-gw')

LAN_ADDR = os.environ.get('LAN_ADDR', '10.10.0.1')
LAN_NET = ipaddress.ip_network(f"{LAN_ADDR}/{os.environ.get('LAN_PREFIX', '24')}", strict=False)
PORTAL_PORT = int(os.environ.get('PORTAL_PORT', '80'))
PORTAL_HOSTS = {LAN_ADDR, 'login.wifi'}

RADIUS_SERVER = os.environ.get('RADIUS_SERVER', '')
RADIUS_AUTH_PORT = int(os.environ.get('RADIUS_AUTH_PORT', '1812'))
RADIUS_ACCT_PORT = int(os.environ.get('RADIUS_ACCT_PORT', '1813'))
RADIUS_SECRET = os.environ.get('RADIUS_SECRET', '').encode()
NAS_IDENTIFIER = os.environ.get('NAS_IDENTIFIER', 'safenet-gateway')

DEFAULT_SESSION = int(os.environ.get('DEFAULT_SESSION_SECONDS', '3600'))
MAX_SESSION = int(os.environ.get('MAX_SESSION_SECONDS', str(7 * 86400)))
ACCT_INTERIM = int(os.environ.get('ACCT_INTERIM_SECONDS', '60'))
# How often to ask SafeNet which guests must be cut off (disabled voucher, admin kick...)
REVOKE_CHECK_SECONDS = int(os.environ.get('REVOKE_CHECK_SECONDS', '10'))

HOTSPOT_NAME = os.environ.get('HOTSPOT_NAME', 'SafeNet WiFi')
HOTSPOT_SUPPORT = os.environ.get('HOTSPOT_SUPPORT', '')
HOTSPOT_TERMS = os.environ.get(
    'HOTSPOT_TERMS',
    'Use this network lawfully. No illegal downloads, spam or attacks on other users. '
    'Vouchers are valid from first login, cannot be refunded and must not be shared. '
    'We may log connection times and data usage for billing and security.')
# Portal look and text; replaced by the tenant's settings from SafeNet in API_MODE
branding = {'name': HOTSPOT_NAME, 'support': HOTSPOT_SUPPORT, 'terms': HOTSPOT_TERMS}
LOGO_FILE = os.path.join(os.environ.get('STATE_DIRECTORY', '/var/lib/safenet-gateway'), 'logo')

# Cloud SafeNet web app, for selling packages (optional)
SAFENET_API_URL = os.environ.get('SAFENET_API_URL', '').rstrip('/')
SAFENET_API_KEY = os.environ.get('SAFENET_API_KEY', '')
# With an API key the gateway logs guests in and reports usage over HTTPS
# (works behind any ISP). AUTH_MODE=radius keeps the older RADIUS path.
API_MODE = bool(SAFENET_API_URL and SAFENET_API_KEY) and os.environ.get('AUTH_MODE', 'auto') != 'radius'

STATE_FILE = os.path.join(os.environ.get('STATE_DIRECTORY', '/var/lib/safenet-gateway'), 'sessions.json')
NFT_TABLE = 'safenet_gw'

# Failed logins allowed per device before a cool-down
MAX_FAILURES = 5
FAILURE_WINDOW = 300


# ---------------------------------------------------------------------------
# RADIUS (RFC 2865 / 2866): PAP Access-Request and Accounting-Request
# ---------------------------------------------------------------------------
ACCESS_REQUEST, ACCESS_ACCEPT, ACCESS_REJECT = 1, 2, 3
ACCOUNTING_REQUEST, ACCOUNTING_RESPONSE = 4, 5

A_USER_NAME, A_USER_PASSWORD, A_NAS_IP, A_SERVICE_TYPE = 1, 2, 4, 6
A_FRAMED_IP, A_REPLY_MESSAGE, A_SESSION_TIMEOUT, A_IDLE_TIMEOUT = 8, 18, 27, 28
A_CALLED_STATION, A_CALLING_STATION, A_NAS_IDENTIFIER = 30, 31, 32
A_ACCT_STATUS, A_ACCT_IN_OCTETS, A_ACCT_OUT_OCTETS = 40, 42, 43
A_ACCT_SESSION_ID, A_ACCT_SESSION_TIME, A_ACCT_TERMINATE = 44, 46, 49
A_ACCT_IN_GIGAWORDS, A_ACCT_OUT_GIGAWORDS, A_EVENT_TIMESTAMP = 52, 53, 55
A_NAS_PORT_TYPE, A_MESSAGE_AUTHENTICATOR = 61, 80

ACCT_START, ACCT_STOP, ACCT_INTERIM_UPDATE = 1, 2, 3
TERM_USER_REQUEST, TERM_IDLE, TERM_SESSION_TIMEOUT, TERM_ADMIN_RESET, TERM_NAS_REBOOT = 1, 4, 5, 6, 11


class RadiusError(Exception):
    pass


def _attr(kind, value):
    return struct.pack('!BB', kind, len(value) + 2) + value


def _str(kind, text):
    return _attr(kind, text.encode()[:253])


def _int(kind, number):
    return _attr(kind, struct.pack('!I', int(number) & 0xFFFFFFFF))


def _ip(kind, addr):
    return _attr(kind, socket.inet_aton(addr))


def _pap_hide(password, authenticator):
    data = password.encode()[:128]
    data += b'\0' * ((16 - len(data) % 16) % 16 or (16 if not data else 0))
    out, prev = b'', authenticator
    for i in range(0, len(data), 16):
        key = hashlib.md5(RADIUS_SECRET + prev).digest()
        prev = bytes(a ^ b for a, b in zip(data[i:i + 16], key))
        out += prev
    return out


def _parse_attrs(data):
    attrs = {}
    i = 0
    while i + 2 <= len(data):
        kind, length = data[i], data[i + 1]
        if length < 2 or i + length > len(data):
            break
        attrs.setdefault(kind, []).append(data[i + 2:i + length])
        i += length
    return attrs


def _exchange(packet, port, ident, request_auth, tries=3, timeout=3.0):
    """Send, wait for a reply with our id, and verify its Response Authenticator."""
    addr = socket.getaddrinfo(RADIUS_SERVER, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        for _ in range(tries):
            sock.sendto(packet, addr)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    reply, _ = sock.recvfrom(4096)
                except socket.timeout:
                    break
                if len(reply) < 20 or reply[1] != ident:
                    continue
                length = struct.unpack('!H', reply[2:4])[0]
                reply = reply[:length]
                expected = hashlib.md5(reply[:4] + request_auth + reply[20:] + RADIUS_SECRET).digest()
                if not hmac.compare_digest(expected, reply[4:20]):
                    log.warning('RADIUS reply with bad authenticator (wrong shared secret?)')
                    continue
                return reply[0], _parse_attrs(reply[20:])
    raise RadiusError(f'no reply from {RADIUS_SERVER}:{port}')


def radius_authenticate(username, password, mac, ip):
    """Returns (accepted, attrs)."""
    ident = secrets.randbelow(256)
    request_auth = os.urandom(16)
    attrs = (_str(A_USER_NAME, username)
             + _attr(A_USER_PASSWORD, _pap_hide(password, request_auth))
             + _int(A_SERVICE_TYPE, 1)                      # Login-User
             + _ip(A_NAS_IP, LAN_ADDR)
             + _str(A_NAS_IDENTIFIER, NAS_IDENTIFIER)
             + _str(A_CALLED_STATION, NAS_IDENTIFIER)
             + _str(A_CALLING_STATION, mac.upper().replace(':', '-'))
             + _ip(A_FRAMED_IP, ip)
             + _int(A_NAS_PORT_TYPE, 19))                   # Wireless-802.11
    header_len = 20 + len(attrs) + 18
    packet = struct.pack('!BBH', ACCESS_REQUEST, ident, header_len) + request_auth + attrs + _attr(A_MESSAGE_AUTHENTICATOR, b'\0' * 16)
    packet = packet[:-16] + hmac.new(RADIUS_SECRET, packet, 'md5').digest()
    code, reply = _exchange(packet, RADIUS_AUTH_PORT, ident, request_auth)
    return code == ACCESS_ACCEPT, reply


def radius_account(status, session, terminate_cause=None):
    now = int(time.time())
    up, down = session.get('up', 0), session.get('down', 0)
    attrs = (_int(A_ACCT_STATUS, status)
             + _str(A_ACCT_SESSION_ID, session['sid'])
             + _str(A_USER_NAME, session['user'])
             + _ip(A_NAS_IP, LAN_ADDR)
             + _str(A_NAS_IDENTIFIER, NAS_IDENTIFIER)
             + _str(A_CALLED_STATION, NAS_IDENTIFIER)
             + _str(A_CALLING_STATION, session['mac'].upper().replace(':', '-'))
             + _ip(A_FRAMED_IP, session['ip'])
             + _int(A_NAS_PORT_TYPE, 19)
             + _int(A_EVENT_TIMESTAMP, now))
    if status != ACCT_START:
        attrs += (_int(A_ACCT_SESSION_TIME, max(0, now - int(session['start'])))
                  + _int(A_ACCT_IN_OCTETS, up) + _int(A_ACCT_IN_GIGAWORDS, up >> 32)
                  + _int(A_ACCT_OUT_OCTETS, down) + _int(A_ACCT_OUT_GIGAWORDS, down >> 32))
    if terminate_cause:
        attrs += _int(A_ACCT_TERMINATE, terminate_cause)
    ident = secrets.randbelow(256)
    header = struct.pack('!BBH', ACCOUNTING_REQUEST, ident, 20 + len(attrs))
    request_auth = hashlib.md5(header + b'\0' * 16 + attrs + RADIUS_SECRET).digest()
    code, _ = _exchange(header + request_auth + attrs, RADIUS_ACCT_PORT, ident, request_auth)
    if code != ACCOUNTING_RESPONSE:
        raise RadiusError(f'unexpected accounting reply code {code}')


def authenticate(username, password, mac, ip):
    """Returns (accepted, message, seconds, upload, download). Raises on network errors."""
    if API_MODE:
        data = safenet_api('POST', '/api/gateway/auth', {'username': username, 'password': password,
                                                        'mac': mac, 'ip': ip}, timeout=15)
        return (bool(data.get('ok')), data.get('message') or '', data.get('session_timeout'),
                data.get('upload'), data.get('download'))
    accepted, reply = radius_authenticate(username, password, mac, ip)
    return (accepted, _first_text(reply, A_REPLY_MESSAGE), _first_int(reply, A_SESSION_TIMEOUT), None, None)


TERM_NAMES = {TERM_USER_REQUEST: 'User-Request', TERM_IDLE: 'Idle-Timeout', TERM_SESSION_TIMEOUT: 'Session-Timeout',
              TERM_ADMIN_RESET: 'Admin-Reset', TERM_NAS_REBOOT: 'NAS-Reboot'}


def account(status, session, terminate_cause=None):
    if not API_MODE:
        return radius_account(status, session, terminate_cause)
    now = int(time.time())
    event = {'type': {ACCT_START: 'start', ACCT_STOP: 'stop', ACCT_INTERIM_UPDATE: 'interim'}[status],
             'session_id': session['sid'], 'username': session['user'], 'mac': session['mac'], 'ip': session['ip'],
             'input_octets': session.get('up', 0), 'output_octets': session.get('down', 0),
             'session_time': max(0, now - int(session['start'])), 'time': now,
             'terminate_cause': TERM_NAMES.get(terminate_cause, 'User-Request') if terminate_cause else None}
    safenet_api('POST', '/api/gateway/accounting', {'events': [event]}, timeout=15)


def refresh_branding():
    """Tenant's portal settings (and logo, cached on disk) from SafeNet."""
    if not API_MODE:
        return
    try:
        data = safenet_api('GET', '/api/gateway/config', timeout=8)
    except Exception as e:
        log.warning('fetching branding failed: %s', e)
        return
    portal = data.get('portal') or {}
    branding.update(name=data.get('hotspot_name') or branding['name'],
                    support=data.get('support') or '', terms=data.get('terms') or branding['terms'],
                    **{k: portal.get(k) for k in ('color', 'style', 'title', 'message', 'language',
                                                   'show_voucher', 'show_packages') if k in portal})
    version = portal.get('logo_version')
    if not version:
        branding.pop('logo_url', None)
    elif branding.get('logo_version') != version:
        try:
            content, content_type = safenet_fetch('/api/gateway/logo')
            with open(LOGO_FILE + '.tmp', 'wb') as f:
                f.write(content)
            os.replace(LOGO_FILE + '.tmp', LOGO_FILE)
            branding.update(logo_version=version, logo_type=content_type, logo_url=f'/logo?v={version}')
        except Exception as e:
            log.warning('fetching logo failed: %s', e)


def _first_int(attrs, kind):
    values = attrs.get(kind)
    if values and len(values[0]) == 4:
        return struct.unpack('!I', values[0])[0]
    return None


def _first_text(attrs, kind):
    values = attrs.get(kind)
    return values[0].decode('utf-8', 'replace') if values else ''


# ---------------------------------------------------------------------------
# Firewall (nftables sets created by safenet-gw-firewall)
# ---------------------------------------------------------------------------
def _nft(script):
    subprocess.run(['nft', '-f', '-'], input=script, text=True, check=True, capture_output=True)


def firewall_allow(mac, ip, seconds):
    # add+delete+add in one transaction replaces an existing element's timeout
    lines = []
    for name, key in (('allowed_mac', mac), ('up_ip', ip), ('down_ip', ip)):
        lines += [f'add element inet {NFT_TABLE} {name} {{ {key} }}',
                  f'delete element inet {NFT_TABLE} {name} {{ {key} }}',
                  f'add element inet {NFT_TABLE} {name} {{ {key} timeout {int(seconds)}s }}']
    _nft('\n'.join(lines) + '\n')


_SPEED = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*([kKmMgG]?)\s*$')


def speed_kbytes(value):
    """'10M' (bits/s, as in SafeNet plans) -> 1250 (kbytes/s); None if unlimited/invalid."""
    m = _SPEED.match(str(value or ''))
    if not m:
        return None
    bits = float(m.group(1)) * {'': 1e6, 'k': 1e3, 'm': 1e6, 'g': 1e9}[m.group(2).lower()]
    return max(8, int(bits / 8000)) if bits > 0 else None


def apply_rate_limits():
    """Rebuild the per-guest speed limits from the current sessions (one transaction)."""
    lines = [f'flush chain inet {NFT_TABLE} ratelimit']
    with sessions_lock:
        current = list(sessions.values())
    for s in current:
        up, down = speed_kbytes(s.get('up_limit')), speed_kbytes(s.get('down_limit'))
        if up:
            lines.append(f'add rule inet {NFT_TABLE} ratelimit ip saddr {s["ip"]} limit rate over {up} kbytes/second burst {max(up, 64)} kbytes drop')
        if down:
            lines.append(f'add rule inet {NFT_TABLE} ratelimit ip daddr {s["ip"]} limit rate over {down} kbytes/second burst {max(down, 64)} kbytes drop')
    try:
        _nft('\n'.join(lines) + '\n')
    except subprocess.CalledProcessError as e:
        log.error('applying speed limits failed: %s', e.stderr)


def firewall_deny(mac, ip):
    lines = []
    for name, key in (('allowed_mac', mac), ('up_ip', ip), ('down_ip', ip)):
        lines += [f'add element inet {NFT_TABLE} {name} {{ {key} }}',
                  f'delete element inet {NFT_TABLE} {name} {{ {key} }}']
    _nft('\n'.join(lines) + '\n')


def _set_elements(name):
    """{key: bytes_counted} for an nft set."""
    out = subprocess.run(['nft', '-j', 'list', 'set', 'inet', NFT_TABLE, name],
                         text=True, check=True, capture_output=True).stdout
    result = {}
    for item in json.loads(out).get('nftables', []):
        for elem in (item.get('set') or {}).get('elem', []):
            if isinstance(elem, dict) and 'elem' in elem:
                elem = elem['elem']
                result[str(elem.get('val')).lower()] = (elem.get('counter') or {}).get('bytes', 0)
            else:
                result[str(elem).lower()] = 0
    return result


def mac_for_ip(ip):
    try:
        with open('/proc/net/arp') as f:
            next(f)
            for line in f:
                fields = line.split()
                if len(fields) >= 4 and fields[0] == ip and fields[2] != '0x0':
                    return fields[3].lower()
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
sessions = {}           # mac -> {mac, ip, user, sid, start, expires, up, down, last_update}
sessions_lock = threading.Lock()
failures = {}           # mac -> [timestamps]


def save_sessions():
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(sessions, f)
    os.replace(tmp, STATE_FILE)


def load_sessions():
    """Re-open the firewall for sessions that survived a restart."""
    try:
        with open(STATE_FILE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    now = time.time()
    for mac, s in saved.items():
        remaining = int(s['expires'] - now)
        if remaining > 5:
            try:
                firewall_allow(mac, s['ip'], remaining)
                sessions[mac] = s
            except subprocess.CalledProcessError as e:
                log.error('could not restore %s: %s', mac, e.stderr)
        else:
            _background(account, ACCT_STOP, s, TERM_SESSION_TIMEOUT)
    log.info('restored %d session(s)', len(sessions))
    apply_rate_limits()


def _background(fn, *args):
    def run():
        try:
            fn(*args)
        except Exception as e:  # accounting must never break logins
            log.warning('%s failed: %s', fn.__name__, e)
    threading.Thread(target=run, daemon=True).start()


def end_session(mac, cause):
    with sessions_lock:
        s = sessions.pop(mac, None)
        if not s:
            return
        save_sessions()
    try:
        # Final byte counts, before the elements (and their counters) are removed
        s['up'] = max(s.get('up', 0), _set_elements('up_ip').get(s['ip'], 0))
        s['down'] = max(s.get('down', 0), _set_elements('down_ip').get(s['ip'], 0))
    except Exception as e:
        log.warning('reading final counters for %s failed: %s', mac, e)
    try:
        firewall_deny(mac, s['ip'])
    except subprocess.CalledProcessError as e:
        log.error('firewall deny %s: %s', mac, e.stderr)
    log.info('session ended user=%s mac=%s cause=%s', s['user'], mac, cause)
    if s.get('up_limit') or s.get('down_limit'):
        apply_rate_limits()
    _background(account, ACCT_STOP, s, cause)


def accounting_loop():
    last_branding = time.time()
    while True:
        time.sleep(30)
        if time.time() - last_branding > 300:
            last_branding = time.time()
            refresh_branding()
        try:
            allowed = _set_elements('allowed_mac')
            up = _set_elements('up_ip')
            down = _set_elements('down_ip')
        except Exception as e:
            log.warning('reading firewall sets failed: %s', e)
            continue
        now = time.time()
        with sessions_lock:
            current = list(sessions.items())
        for mac, s in current:
            s['up'] = max(s.get('up', 0), up.get(s['ip'], 0))
            s['down'] = max(s.get('down', 0), down.get(s['ip'], 0))
            if now >= s['expires'] - 1:
                end_session(mac, TERM_SESSION_TIMEOUT)
            elif mac not in allowed:
                end_session(mac, TERM_ADMIN_RESET)
            elif now - s.get('last_update', 0) >= ACCT_INTERIM:
                s['last_update'] = now
                _background(account, ACCT_INTERIM_UPDATE, s)
        with sessions_lock:
            save_sessions()


def check_revocations():
    """Disconnect guests SafeNet no longer allows. Returns how many were cut off."""
    with sessions_lock:
        by_user = {}
        for mac, s in sessions.items():
            by_user.setdefault(s['user'], []).append(mac)
    if not by_user:
        return 0
    try:
        names = safenet_api('POST', '/api/gateway/sessions/check', {'usernames': list(by_user)},
                            timeout=8).get('disconnect') or []
    except ApiError as e:
        if 'suspended' not in str(e):
            log.warning('session check failed: %s', e)
            return 0
        names = list(by_user)          # the whole network is suspended
    count = 0
    for name in names:
        for mac in by_user.get(name, []):
            log.info('disconnecting %s (%s): revoked by SafeNet', name, mac)
            end_session(mac, TERM_ADMIN_RESET)
            count += 1
    return count


def revocation_loop():
    """Within REVOKE_CHECK_SECONDS of a voucher being disabled or a user kicked."""
    while True:
        time.sleep(REVOKE_CHECK_SECONDS)
        check_revocations()


def too_many_failures(mac):
    now = time.time()
    recent = [t for t in failures.get(mac, []) if now - t < FAILURE_WINDOW]
    failures[mac] = recent
    return len(recent) >= MAX_FAILURES


def login(mac, ip, user, password):
    """Returns (session, error_message)."""
    if too_many_failures(mac):
        return None, 'Too many wrong attempts. Please wait a few minutes and try again.'
    try:
        accepted, message, seconds, up_limit, down_limit = authenticate(user, password, mac, ip)
    except (RadiusError, ApiError, OSError) as e:
        log.error('auth failed: %s', e)
        return None, "We can't reach the login server right now. Please try again in a minute."
    if not accepted:
        failures.setdefault(mac, []).append(time.time())
        log.info('login rejected user=%s mac=%s', user, mac)
        return None, message or "That code isn't valid. Check it and try again."

    seconds = seconds or DEFAULT_SESSION
    seconds = max(60, min(seconds, MAX_SESSION))
    if mac in sessions:
        end_session(mac, TERM_USER_REQUEST)
    try:
        firewall_allow(mac, ip, seconds)
    except subprocess.CalledProcessError as e:
        log.error('firewall allow %s: %s', mac, e.stderr)
        return None, 'Something went wrong on our side. Please try again.'
    now = time.time()
    session = {'mac': mac, 'ip': ip, 'user': user, 'sid': secrets.token_hex(8),
               'start': now, 'expires': now + seconds, 'up': 0, 'down': 0, 'last_update': now,
               'up_limit': up_limit, 'down_limit': down_limit}
    with sessions_lock:
        sessions[mac] = session
        save_sessions()
    if up_limit or down_limit:
        apply_rate_limits()
    failures.pop(mac, None)
    log.info('login ok user=%s mac=%s ip=%s for %ss', user, mac, ip, seconds)
    _background(account, ACCT_START, session)
    return session, None


# ---------------------------------------------------------------------------
# Buying packages (SafeNet API -> ClickPesa USSD push)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    pass


def safenet_api(method, path, body=None, timeout=25):
    if not SAFENET_API_URL or not SAFENET_API_KEY:
        raise ApiError('package sales are not configured')
    req = urllib.request.Request(
        SAFENET_API_URL + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json', 'X-SafeNet-Key': SAFENET_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read()).get('error')
        except ValueError:
            message = None
        raise ApiError(message or f'SafeNet returned {e.code}') from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ApiError(f'SafeNet unreachable: {e}') from None


def safenet_fetch(path, timeout=15):
    """(bytes, content type) of a binary SafeNet API resource."""
    req = urllib.request.Request(SAFENET_API_URL + path, headers={'X-SafeNet-Key': SAFENET_API_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(512 * 1024), resp.headers.get('Content-Type', 'application/octet-stream')


_packages_cache = {'at': 0.0, 'items': [], 'networks': []}
IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img')   # network logos (from static/img)


def portal_packages():
    """Packages for sale, cached for a minute; [] if sales are off or SafeNet is down."""
    if not SAFENET_API_URL:
        return []
    if time.time() - _packages_cache['at'] > 60:
        try:
            data = safenet_api('GET', '/api/portal/packages', timeout=8)
            items = data.get('packages', []) if data.get('payments_enabled') else []
            networks = data.get('networks') or []
        except ApiError as e:
            log.warning('fetching packages failed: %s', e)
            items, networks = _packages_cache['items'], _packages_cache['networks']
        _packages_cache.update(at=time.time(), items=items, networks=networks)
    return _packages_cache['items']


def portal_networks():
    portal_packages()
    return _packages_cache['networks']


purchases = {}          # reference -> {mac, ip, phone, amount, package, created}
purchase_attempts = {}  # mac -> [timestamps]
MAX_PURCHASES = 3       # payment requests per device per 10 minutes
PURCHASE_WAIT = 240     # seconds to keep checking before offering "check again"


def start_purchase(mac, ip, package_id, phone, network=None):
    """Returns (reference, error)."""
    now = time.time()
    recent = [t for t in purchase_attempts.get(mac, []) if now - t < 600]
    if len(recent) >= MAX_PURCHASES:
        return None, 'Too many payment requests. Please wait a few minutes.'
    purchase_attempts[mac] = recent + [now]
    try:
        data = safenet_api('POST', '/api/portal/purchase', {
            'package_id': package_id, 'phone': phone, 'mac': mac, 'ip': ip, 'nas': NAS_IDENTIFIER,
            'network': network})
    except ApiError as e:
        log.info('purchase failed mac=%s: %s', mac, e)
        return None, str(e) if 'unreachable' not in str(e) else "We can't reach the payment server right now. Please try again."
    ref = data['reference']
    purchases[ref] = {'mac': mac, 'ip': ip, 'phone': data.get('phone', phone), 'amount': data.get('amount'),
                      'currency': data.get('currency', 'TZS'), 'package': data.get('package'), 'created': now}
    log.info('purchase started ref=%s mac=%s package=%s', ref, mac, data.get('package'))
    return ref, None


# ---------------------------------------------------------------------------
# Web pages (see portal_ui.py, shared with the SafeNet web app)
# ---------------------------------------------------------------------------
def _theme():
    return ui.theme(branding)


def login_page(dst='', error='', lang='en', tab='voucher'):
    return ui.login_page(_theme(), lang, packages=portal_packages(), dst=dst, error=error, tab=tab,
                         buy_enabled=bool(SAFENET_API_URL), networks=portal_networks(), logo_base='/img/')


def status_page(session, dst='', new_code=None, lang='en'):
    return ui.status_page(_theme(), lang, user=session['user'], remaining=session['expires'] - time.time(),
                          total=session['expires'] - session.get('start', session['expires']), dst=dst, new_code=new_code)


def waiting_page(ref, info, timed_out=False, lang='en'):
    return ui.waiting_page(_theme(), lang, ref=ref, info=info, timed_out=timed_out)


def format_remaining(seconds):
    return ui.duration(int(seconds) // 60)


class PortalHandler(BaseHTTPRequestHandler):
    server_version = 'SafeNet'
    sys_version = ''

    def log_message(self, fmt, *args):
        log.debug('%s %s', self.client_address[0], fmt % args)

    def _lang(self, query=None):
        """?lang= (remembered in a cookie) > cookie > tenant default."""
        wanted = (query or {}).get('lang', [''])[0]
        if wanted in ui.LANGS:
            self._cookie = f'sn_lang={wanted}; Path=/; Max-Age=31536000; SameSite=Lax'
            return wanted
        cookie = self.headers.get('Cookie') or ''
        m = re.search(r'(?:^|;\s*)sn_lang=(en|sw)', cookie)
        return m.group(1) if m else _theme()['language']

    def _send(self, status, body='', headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        if getattr(self, '_cookie', None):
            self.send_header('Set-Cookie', self._cookie)
        if body and isinstance(body, str):
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def _redirect(self, location):
        self._send(302, '', {'Location': location})

    def _client(self):
        ip = self.client_address[0]
        try:
            if ipaddress.ip_address(ip) not in LAN_NET:
                return ip, None
        except ValueError:
            return ip, None
        return ip, mac_for_ip(ip)

    def _portal_url(self, path='/', **params):
        base = f'http://{LAN_ADDR}' + ('' if PORTAL_PORT == 80 else f':{PORTAL_PORT}')
        return base + path + (('?' + urlencode(params)) if params else '')

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]').lower()
        if host not in PORTAL_HOSTS:
            # Intercepted request (captive-portal probe or a website): send to the splash page
            original = f"http://{self.headers.get('Host', '')}{self.path}"[:500]
            return self._redirect(self._portal_url('/', dst=original))

        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == '/logo':
            return self._logo()
        if url.path.startswith('/img/'):
            return self._network_logo(url.path[5:])
        lang = self._lang(query)
        if url.path == '/buy/wait':
            return self._buy_wait(query.get('ref', [''])[0], bool(query.get('again')), lang)
        if url.path != '/':
            return self._redirect(self._portal_url('/'))
        dst = query.get('dst', [''])[0][:500]
        ip, mac = self._client()
        session = sessions.get(mac) if mac else None
        if session and session['ip'] == ip and session['expires'] > time.time():
            return self._send(200, status_page(session, dst, lang=lang))
        self._send(200, login_page(dst, lang=lang))

    def _network_logo(self, name):
        # Only the known network logo files, never an arbitrary path
        if name not in {n['logo'] for n in ui.NETWORKS.values()}:
            return self._send(404, '')
        try:
            with open(os.path.join(IMG_DIR, name), 'rb') as f:
                content = f.read()
        except OSError:
            return self._send(404, '')
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg' if name.endswith('.jpg') else 'image/png')
        self.send_header('Cache-Control', 'public, max-age=604800')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(content)

    def _logo(self):
        try:
            with open(LOGO_FILE, 'rb') as f:
                content = f.read()
        except OSError:
            return self._send(404, '')
        self.send_response(200)
        self.send_header('Content-Type', branding.get('logo_type') or 'image/png')
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(content)

    def do_POST(self):
        length = min(int(self.headers.get('Content-Length') or 0), 4096)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode('utf-8', 'replace')).items()}
        ip, mac = self._client()
        path = urlparse(self.path).path
        dst = form.get('dst', '')[:500]
        lang = self._lang()

        if path == '/logout':
            if mac:
                end_session(mac, TERM_USER_REQUEST)
            return self._redirect(self._portal_url('/'))
        if path == '/buy':
            return self._buy(form, ip, mac, dst, lang)
        if path != '/login':
            return self._redirect(self._portal_url('/'))

        if not mac:
            return self._send(200, login_page(dst, "We couldn't identify your device. Turn Wi-Fi off and on, then try again.", lang))
        if not form.get('agree'):
            return self._send(200, login_page(dst, 'Please accept the terms of use to continue.', lang))
        username = form.get('username', '').strip()
        if username:
            password = form.get('password', '')
        else:
            username = password = re.sub(r'\s+', '', form.get('code', ''))
        if not username:
            return self._send(200, login_page(dst, 'Enter your voucher code.', lang))

        session, error = login(mac, ip, username, password)
        if error:
            return self._send(200, login_page(dst, error, lang))
        self._send(200, status_page(session, dst, lang=lang))


    def _buy(self, form, ip, mac, dst, lang):
        err = lambda message: self._send(200, login_page(dst, message, lang, tab='buy'))
        if not mac:
            return err("We couldn't identify your device. Turn Wi-Fi off and on, then try again.")
        if not form.get('agree'):
            return err('Please accept the terms of use to continue.')
        try:
            package_id = int(form.get('package_id', ''))
        except ValueError:
            return err('Choose a package.')
        phone = re.sub(r'\D', '', form.get('phone', ''))
        if len(phone) == 9:                      # typed after the +255 prefix
            phone = '255' + phone
        network = form.get('network', '')[:16] or None
        if portal_networks() and not network:
            return err('Choose your mobile-money network.')
        ref, error = start_purchase(mac, ip, package_id, phone, network)
        if error:
            return err(error)
        self._redirect(self._portal_url('/buy/wait', ref=ref))

    def _buy_wait(self, ref, again, lang='en'):
        ip, mac = self._client()
        info = purchases.get(ref)
        if not info or info['mac'] != mac:
            return self._redirect(self._portal_url('/'))
        try:
            data = safenet_api('GET', f'/api/portal/purchase/{ref}', timeout=15)
        except ApiError as e:
            log.warning('purchase status %s: %s', ref, e)
            data = {'status': 'pending'}
        status = data.get('status')
        if status == 'paid' and data.get('code'):
            purchases.pop(ref, None)
            code = data['code']
            session, error = login(mac, ip, code, code)
            if error:
                return self._send(200, login_page('', f'Payment received. Your voucher code is {code}. {error}', lang))
            return self._send(200, status_page(session, '', new_code=code, lang=lang))
        if status in ('failed', 'review'):
            purchases.pop(ref, None)
            reason = data.get('message') or 'The payment was not completed.'
            return self._send(200, login_page('', f'Payment not completed: {reason}', lang, tab='buy'))
        timed_out = time.time() - info['created'] > PURCHASE_WAIT and not again
        self._send(200, waiting_page(ref, info, timed_out, lang))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        # Bind even if LAN_ADDR isn't on the interface yet (Wi-Fi still connecting)
        self.socket.setsockopt(socket.SOL_IP, getattr(socket, 'IP_FREEBIND', 15), 1)
        super().server_bind()


def main():
    logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'),
                        format='%(levelname)s %(message)s')
    if not API_MODE and (not RADIUS_SERVER or not RADIUS_SECRET):
        raise SystemExit('Set SAFENET_API_URL and SAFENET_API_KEY (or RADIUS_SERVER and RADIUS_SECRET)')
    refresh_branding()
    load_sessions()
    threading.Thread(target=accounting_loop, daemon=True).start()
    if API_MODE:
        threading.Thread(target=revocation_loop, daemon=True).start()
    server = Server((LAN_ADDR, PORTAL_PORT), PortalHandler)
    log.info('portal on http://%s:%d, %s', LAN_ADDR, PORTAL_PORT,
             f'SafeNet API {SAFENET_API_URL}' if API_MODE else f'RADIUS {RADIUS_SERVER}')
    server.serve_forever()


if __name__ == '__main__':
    main()
