"""UniFi Network controller client (UniFi Network Application, Cloud Key, UDM / UniFi OS).

How it works with SafeNet:
  1. The UniFi guest portal is set to "External portal server" = SafeNet. The controller sends a guest who isn't
     let in yet to  http://<portal host>/guest/s/<controller site name>/?ap=<ap mac>&id=<client mac>&t=..&url=..&ssid=..
  2. The guest pays or types a voucher on SafeNet's page.
  3. SafeNet calls the controller:  POST /api/s/<site>/cmd/stamgr {"cmd": "authorize-guest", "mac", "minutes", ...}
  4. While the guest is online SafeNet reads /api/s/<site>/stat/sta (data used) and, when the time is up,
     sends "unauthorize-guest".

Classic controllers log in at /api/login. UniFi OS consoles (UDM, Cloud Key Gen2+, UniFi OS Server) log in at
/api/auth/login, put the Network API under /proxy/network and want the X-CSRF-Token header they hand out.
"""
import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.request

from omada import public_address_problem, _NoRedirect

MAX_MINUTES = 30 * 24 * 60


class UnifiError(Exception):
    pass


def mac(value):
    """aa:bb:cc:dd:ee:ff (the form the controller uses), or '' when it isn't a MAC address."""
    raw = re.sub(r'[^0-9A-Fa-f]', '', value or '').lower()
    return ':'.join(raw[i:i + 2] for i in range(0, 12, 2)) if len(raw) == 12 else ''


class Controller:
    def __init__(self, url, username, password, verify_tls=False, timeout=12, public_only=False):
        """public_only: a business's own controller (must be on the internet); SafeNet's hosted one is internal."""
        self.base = (url or '').rstrip('/')
        self.username, self.password = username or '', password or ''
        self.timeout, self.public_only = timeout, public_only
        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        handlers = [urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
        if public_only:
            handlers.append(_NoRedirect())
        self.opener = urllib.request.build_opener(*handlers)
        self.unifi_os = None          # found at login
        self.csrf = None
        self.logged_in = False

    # -- transport ---------------------------------------------------------------------------------------------
    def _raw(self, method, path, body=None):
        if self.public_only:
            problem = public_address_problem(self.base)      # checked every time (DNS can change)
            if problem:
                raise UnifiError(problem)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header('Accept', 'application/json')
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        if self.csrf:
            req.add_header('X-CSRF-Token', self.csrf)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                token = resp.headers.get('X-CSRF-Token') or resp.headers.get('X-Updated-CSRF-Token')
                if token:
                    self.csrf = token
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read() if hasattr(e, 'read') else b''
        except (urllib.error.URLError, OSError) as e:
            raise UnifiError(f"can't reach the UniFi controller at {self.base} ({getattr(e, 'reason', e)})") from e

    def login(self):
        creds = {'username': self.username, 'password': self.password, 'remember': True}
        status, _ = self._raw('POST', '/api/auth/login', creds)            # UniFi OS
        if status == 200:
            self.unifi_os = True
        else:
            status, raw = self._raw('POST', '/api/login', creds)           # classic controller
            if status != 200:
                if status in (400, 401, 403):
                    raise UnifiError('the UniFi controller refused the login: check the username and password')
                raise UnifiError(f'the UniFi controller answered HTTP {status} to the login')
            self.unifi_os = False
        self.logged_in = True

    def _call(self, method, path, body=None, *, again=True):
        """A Network API call (path like /api/s/default/stat/sta). Returns the reply's data list."""
        if not self.logged_in:
            self.login()
        status, raw = self._raw(method, ('/proxy/network' if self.unifi_os else '') + path, body)
        if status == 401 and again:                    # the session ran out: log in again once
            self.logged_in = False
            return self._call(method, path, body, again=False)
        if status != 200:
            message = ''
            try:
                message = (json.loads(raw or b'{}').get('meta') or {}).get('msg', '')
            except ValueError:
                pass
            raise UnifiError(f'the UniFi controller answered HTTP {status} for {path}' + (f' ({message})' if message else ''))
        try:
            reply = json.loads(raw or b'{}')
        except ValueError as e:
            raise UnifiError(f'the UniFi controller sent something that is not JSON for {path}') from e
        meta = reply.get('meta') or {}
        if meta.get('rc') not in (None, 'ok'):
            raise UnifiError(f"the UniFi controller refused {path}: {meta.get('msg') or meta.get('rc')}")
        return reply.get('data') or []

    # -- sites ---------------------------------------------------------------------------------------------------
    def sites(self):
        """[{'name': internal id used in URLs, 'desc': what people see, ...}]"""
        return self._call('GET', '/api/self/sites')

    def find_site(self, value):
        value = (value or '').strip()
        for s in self.sites():
            if value and value in (s.get('name'), s.get('desc')):
                return s.get('name')
        return None

    def create_site(self, desc):
        """Create a site; returns its internal name (what the guest portal URL carries)."""
        found = self.find_site(desc)
        if found:
            return found
        data = self._call('POST', '/api/s/default/cmd/sitemgr', {'cmd': 'add-site', 'desc': desc})
        name = (data[0] if data else {}).get('name') or self.find_site(desc)
        if not name:
            raise UnifiError('the UniFi controller did not say which site it made')
        return name

    def check(self, site):
        """Log in and make sure the site exists; returns its description."""
        for s in self.sites():
            if s.get('name') == site:
                return s.get('desc') or site
        raise UnifiError(f'the UniFi controller has no site "{site}" (use the short name from the address bar, often "default")')

    # -- access points ------------------------------------------------------------------------------------------
    def devices(self, site):
        return self._call('GET', f'/api/s/{site}/stat/device')

    def adopt(self, site, device_mac):
        """Adopt an access point that has contacted the controller (set-inform) into this site."""
        m = mac(device_mac)
        if not m:
            raise UnifiError(f'"{device_mac}" is not a MAC address')
        return self._call('POST', f'/api/s/{site}/cmd/devmgr', {'cmd': 'adopt', 'mac': m})

    # -- guests ---------------------------------------------------------------------------------------------------
    def clients(self, site):
        """Connected clients: mac, is_guest, authorized, tx_bytes (to the phone), rx_bytes (from it), ip, ap_mac."""
        return self._call('GET', f'/api/s/{site}/stat/sta')

    def authorize(self, site, client_mac, minutes, *, up_kbps=None, down_kbps=None, ap_mac=None):
        m = mac(client_mac)
        if not m:
            raise UnifiError('the login page was opened without the phone\'s address (id)')
        body = {'cmd': 'authorize-guest', 'mac': m, 'minutes': max(1, min(int(minutes), MAX_MINUTES))}
        if up_kbps:
            body['up'] = int(up_kbps)
        if down_kbps:
            body['down'] = int(down_kbps)
        if mac(ap_mac):
            body['ap_mac'] = mac(ap_mac)
        return self._call('POST', f'/api/s/{site}/cmd/stamgr', body)

    def unauthorize(self, site, client_mac):
        return self._call('POST', f'/api/s/{site}/cmd/stamgr', {'cmd': 'unauthorize-guest', 'mac': mac(client_mac)})

    # -- guest portal and Wi-Fi (SafeNet's hosted controller) -------------------------------------------------------
    def settings(self, site):
        return {s.get('key'): s for s in self._call('GET', f'/api/s/{site}/get/setting')}

    def ensure_portal(self, site, portal_ip, allowed):
        """Guest portal on, sending guests to SafeNet (external portal server), SafeNet reachable before login.
        The controller only takes an IP address for the external portal server (checked on 9.5)."""
        guest = self.settings(site).get('guest_access') or {}
        body = {'portal_enabled': True, 'auth': 'custom', 'custom_ip': portal_ip, 'redirect_enabled': False}
        for i, host in enumerate(allowed[:8], start=1):
            body[f'allowed_subnet_{i}'] = host if '/' in host else f'{host}/32'
        if guest.get('_id'):
            return self._call('PUT', f"/api/s/{site}/rest/setting/guest_access/{guest['_id']}", body)
        body['key'] = 'guest_access'
        return self._call('POST', f'/api/s/{site}/set/setting/guest_access', body)

    def ensure_wlan(self, site, name):
        """An open guest Wi-Fi (the guest portal applies to it) on every access point. Returns its id.
        Fields as the 9.5 controller accepts them: the site's network and its "All APs" group."""
        for w in self._call('GET', f'/api/s/{site}/rest/wlanconf'):
            if w.get('name') == name:
                if not w.get('is_guest') or w.get('security') != 'open' or not w.get('enabled'):
                    self._call('PUT', f"/api/s/{site}/rest/wlanconf/{w['_id']}", {'is_guest': True, 'security': 'open',
                                                                                   'enabled': True})
                return w['_id']
        body = {'name': name, 'enabled': True, 'security': 'open', 'is_guest': True}
        networks = self._call('GET', f'/api/s/{site}/rest/networkconf')
        lan = next((n for n in networks if n.get('purpose') == 'corporate'), networks[0] if networks else None)
        if lan:
            body['networkconf_id'] = lan['_id']
        try:
            groups = self._raw_v2('GET', f'/v2/api/site/{site}/apgroups')
            if groups:
                body['ap_group_ids'] = [g['_id'] for g in groups if g.get('attr_no_delete')] or [groups[0]['_id']]
        except UnifiError:
            pass                       # older controllers have no AP groups
        data = self._call('POST', f'/api/s/{site}/rest/wlanconf', body)
        return (data[0] if data else {}).get('_id')

    def _raw_v2(self, method, path):
        if not self.logged_in:
            self.login()
        status, raw = self._raw(method, ('/proxy/network' if self.unifi_os else '') + path)
        if status != 200:
            raise UnifiError(f'the UniFi controller answered HTTP {status} for {path}')
        try:
            reply = json.loads(raw or b'[]')
        except ValueError as e:
            raise UnifiError('not JSON') from e
        return reply if isinstance(reply, list) else reply.get('data') or []
