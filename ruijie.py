"""Minimal Ruijie Cloud Open API client, for Reyee access points (RG-RAP...) that only show Ruijie's own
login page: SafeNet sells the package, then creates the same code on Ruijie Cloud as a voucher, and the
guest types it on Ruijie's page. Standard library only.

Ruijie Cloud API Reference Manual V2.0.3 (apply for an App ID and secret through Ruijie support):
  POST /service/api/oauth20/client/access_token?token=<fixed>    body {appid, secret} -> accessToken
  GET  /service/api/group/single/tree?depth=BUILDING             projects (network groups) -> groupId
  GET  /service/api/intl/usergroup/list/{groupId}                 user groups = voucher packages (timePeriod in minutes)
  POST /service/api/open/auth/voucher/customerCreate/{groupId}/{code}   body {profile, userGroupId}
Every call carries ?access_token=...; an expired token answers code 4 or "Login timeout".
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import safetext

# Ruijie Cloud's regional servers
CLOUDS = {
    'https://cloud-as.ruijienetworks.com': 'Asia / Africa (cloud-as)',
    'https://cloud.ruijienetworks.com': 'Global (cloud)',
    'https://cloud-eu.ruijienetworks.com': 'Europe (cloud-eu)',
    'https://cloud-us.ruijienetworks.com': 'Americas (cloud-us)',
}
TOKEN_PARAM = 'd63dss0a81e4415a889ac5b78fsc904a'     # fixed value from Ruijie's manual
TOKEN_SECONDS = 20 * 60


class RuijieError(Exception):
    """Message is cleaned of keys and IDs before anyone can see it."""
    def __init__(self, message=''):
        super().__init__(safetext.clean(message))


def valid_cloud(url):
    """Only Ruijie's own HTTPS servers (the App secret is sent there)."""
    return bool(re.fullmatch(r'https://[a-z0-9-]+\.ruijienetworks\.com', (url or '').rstrip('/')))


def find_cloud(appid, secret, preferred=None):
    """The Ruijie Cloud server that accepts these keys (an account lives on one of them; the others answer
    "Login failed" too), trying `preferred` first. Raises RuijieError when none does."""
    order = [preferred] + [u for u in CLOUDS if u != preferred] if preferred in CLOUDS else list(CLOUDS)
    unreachable = 0
    for base in order:
        try:
            Cloud(base, appid, secret).token()
            return base
        except RuijieError as e:
            unreachable += 'could not be reached' in str(e)
    if unreachable == len(order):
        raise RuijieError('Ruijie Cloud could not be reached. Try again in a minute.')
    raise RuijieError('No Ruijie Cloud server accepted this App ID and secret. Copy both again from Ruijie\'s email '
                      '(no spaces), and check they were made for the account your access points are in.')


class Cloud:
    def __init__(self, base, appid, secret):
        if not valid_cloud(base):
            raise RuijieError('Choose a Ruijie Cloud server.')
        self.base, self.appid, self.secret = base.rstrip('/'), appid, secret
        self._token, self._token_at = None, 0.0

    def _http(self, method, url, body=None, timeout=20):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read() or b'null') or {}
        except urllib.error.HTTPError as e:
            raise RuijieError(f'Ruijie Cloud answered {e.code}: {e.read().decode("utf-8", "replace")[:200]}') from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise RuijieError(f'Ruijie Cloud could not be reached: {e}') from None

    def token(self, force=False):
        if self._token and not force and time.time() - self._token_at < TOKEN_SECONDS:
            return self._token
        reply = self._http('POST', f'{self.base}/service/api/oauth20/client/access_token?token={TOKEN_PARAM}',
                           {'appid': self.appid, 'secret': self.secret})
        if reply.get('code') != 0 or not reply.get('accessToken'):
            raise RuijieError(f'Ruijie Cloud refused the App ID or secret: {reply.get("msg") or reply.get("code")}')
        self._token, self._token_at = reply['accessToken'], time.time()
        return self._token

    def call(self, method, path, query=None, body=None, inner=None):
        """The reply's data; raises RuijieError when Ruijie says it failed."""
        for attempt in (0, 1):
            qs = urllib.parse.urlencode({**(query or {}), 'access_token': self.token(force=attempt == 1)})
            reply = self._http(method, f'{self.base}/service/api/{path}?{qs}', body if method == 'POST' else None)
            if (reply.get('code') == 4 or str(reply.get('msg', '')).lower() == 'login timeout') and attempt == 0:
                continue
            break
        if reply.get('code') != 0:
            raise RuijieError(f'Ruijie Cloud: {reply.get("msg") or reply.get("code")}')
        data = reply.get(inner) if inner else reply
        if isinstance(data, dict) and data.get('code') not in (None, 0):
            raise RuijieError(f'Ruijie Cloud: {data.get("msg") or data.get("code")}')
        return data if data is not None else {}

    def projects(self):
        """[(groupId, name)] of the account's projects (where the access points are)."""
        data = self.call('GET', 'group/single/tree', {'depth': 'BUILDING'})
        out = []

        def walk(node):
            if isinstance(node, list):
                for n in node:
                    walk(n)
            elif isinstance(node, dict):
                if node.get('groupId') is not None and str(node.get('type') or '').upper() == 'BUILDING':
                    out.append((str(node['groupId']), str(node.get('name') or node['groupId'])))
                walk(node.get('subGroups') or node.get('children') or [])
        walk(data.get('groups') or data.get('group') or data.get('data') or [])
        return out

    def packages(self, group_id):
        """Voucher packages (user groups) of a project: [{user_group, profile, name, minutes}]."""
        data = self.call('GET', f'intl/usergroup/list/{group_id}', {'pageIndex': 0, 'pageSize': 100})
        items = data.get('list') or data.get('userGroups') or data.get('data') or []
        out = []
        for p in items if isinstance(items, list) else []:
            user_group = p.get('userGroupId') if p.get('userGroupId') not in (None, '') else p.get('id')
            profile = next((p[k] for k in ('authprofileid', 'authProfileId', 'uuid', 'profileId', 'packageId', 'id')
                            if p.get(k) not in (None, '')), None)
            if user_group in (None, '') or profile is None:
                continue
            try:
                minutes = int(float(p.get('timePeriod') or 0))
            except (TypeError, ValueError):
                minutes = 0
            out.append({'user_group': str(user_group), 'profile': str(profile), 'minutes': minutes,
                        'name': str(p.get('packageName') or p.get('profileName') or p.get('userGroupName') or p.get('name') or user_group)})
        return out

    def account(self):
        """(email, tenantId) of the account the keys belong to."""
        info = self.call('GET', 'org/account/info')
        info = info.get('data') if isinstance(info.get('data'), dict) else info
        return (str(info.get('account') or info.get('email') or ''), str(info.get('tenantId') or info.get('defaultTenantId') or ''))

    def create_package(self, group_id, name, minutes, devices=1, price='', down_kbps=0, up_kbps=0):
        """Create a voucher package (user group) in the project. Not in Ruijie's published API: this is the call
        Ruijie Cloud's own pages make (profile, then user group); it may be refused for API keys."""
        email, tenant = self.account()
        if not email:
            raise RuijieError('Ruijie Cloud did not say which account these keys belong to.')
        fields = {
            'name': name, 'userGroupName': name, 'price': str(price or ''), 'quota': 0,
            'timePeriod': int(minutes), 'timePeriodDaily': 0, 'timePeriodDailyCustom': 0, 'timePeriodTotal': 0,
            'uploadRateLimit': int(up_kbps or 0), 'downloadRateLimit': int(down_kbps or 0),
            'noOfDevice': str(devices or 1), 'packageType': 'COMMON', 'bindSsid': '', 'isBindSsid': 0, 'bindMac': 0,
            'ip': '', 'bindIpList': [], 'kickOffType': 1, 'durationCtrlType': 0, 'limitedTimes': 0,
            'lowQuota': 0, 'lowUploadRateLimit': 0, 'lowDownloadRateLimit': 0, 'lowProfileStatus': 0, 'groupId': int(group_id),
        }
        who = urllib.parse.quote(email, safe='')
        query = {'lang': 'en', 'cloudType': 'smb', **({'tenantId': tenant} if tenant else {})}
        made = self.call('POST', f'intlSamProfile/create/{who}/{who}/{group_id}', query, fields)
        inner = made.get('data') if isinstance(made.get('data'), dict) else made.get('result') if isinstance(made.get('result'), dict) else {}
        profile = next((str(v) for v in (made.get('authProfileId'), made.get('profileId'), inner.get('authProfileId'),
                                         inner.get('profileId'), inner.get('id'), made.get('id')) if v not in (None, '')), '')
        if not profile:
            raise RuijieError('Ruijie Cloud made no package profile.')
        self.call('POST', f'intl/usergroup/group/{group_id}', {'lang': 'en', 'cloudType': 'smb'},
                  {'list': [{**fields, 'authProfileId': profile}]})


    def generate_voucher(self, group_id, package, digits=8):
        """A new voucher of `package` with a code Ruijie makes up (numeric). Returns the code."""
        data = self.call('POST', f'open/auth/voucher/create/{group_id}', body={
            'quantity': 1, 'profile': package['profile'], 'userGroupId': package['user_group'],
            'createCodeType': '3', 'codeSize': digits}, inner='voucherData')
        items = data.get('list') if isinstance(data, dict) else data
        code = next((str(v.get('voucherCode') or v.get('codeNo') or '') for v in items or [] if isinstance(v, dict)), '')
        if not code:
            raise RuijieError('Ruijie Cloud made no voucher.')
        return code

    def clients(self, group_id, pages=10):
        """Phones on the project's Wi-Fi now, as Ruijie Cloud's Clients page lists them. Traffic is in bytes
        (a phone online 3 hours reports about 1,264,989,184: 1.26 GB). Ruijie counts from the access point's side,
        so its wifiUp is what the phone downloaded."""
        out = []
        for page in range(pages):
            for attempt in (0, 1):      # an expired token: log in again once
                qs = urllib.parse.urlencode({'access_token': self.token(force=attempt == 1)})
                reply = self._http('POST', f'{self.base}/logbizagent/logbiz/api/sta/sta_users?{qs}',
                                   {'groupId': int(group_id), 'pageIndex': page, 'pageSize': 200, 'staType': 'currentUser'})
                if not (reply.get('code') == 4 or str(reply.get('msg', '')).lower() == 'login timeout'):
                    break
            if reply.get('code') != 0:
                raise RuijieError(f'Ruijie Cloud: {reply.get("msg") or reply.get("code")}')
            items = [c for c in reply.get('list') or [] if isinstance(c, dict)]
            out += [{'mac': str(c.get('mac') or ''), 'ip': str(c.get('userIp') or ''), 'ssid': str(c.get('ssid') or ''),
                     'ap': str(c.get('deviceAliasName') or c.get('sn') or ''), 'band': str(c.get('band') or ''),
                     'rssi': c.get('rssiInt') if c.get('rssiInt') is not None else c.get('rssi'),
                     'down': int(float(c.get('wifiUp') or 0)), 'up': int(float(c.get('wifiDown') or 0)),
                     'since': c.get('onlineTime'), 'online_ms': c.get('activeTime')} for c in items]
            if len(items) < 200 or len(out) >= int(reply.get('count') or 0):
                break
        return out

    def vouchers(self, group_id, pages=25):
        """Every voucher in the project, as Ruijie has them: voucherCode, loginTime and expiryTime (ms),
        usedTime (minutes), currentClients (phones online with it now), status."""
        out, start, size = [], 0, 200
        for _ in range(pages):
            data = self.call('GET', f'open/auth/voucher/getList/{group_id}', {'start': start, 'pageSize': size}, inner='voucherData')
            items = data.get('list') or []
            out += [v for v in items if isinstance(v, dict)]
            start += size
            if not items or start >= int(data.get('count') or 0):
                break
        return out

    def create_voucher(self, group_id, code, package):
        """Make `code` a voucher of `package` (one of packages()) in the project."""
        self.call('POST', f'open/auth/voucher/customerCreate/{group_id}/{urllib.parse.quote(code, safe="")}',
                  body={'profile': package['profile'], 'userGroupId': package['user_group']}, inner='voucherData')


def kbps(speed):
    """'10M' / '512k' / '1G' / '2048' (kbps) -> kbps; 0 = no limit."""
    m = re.fullmatch(r'\s*([\d.]+)\s*([kKmMgG]?)\s*(?:bps)?\s*', str(speed or ''))
    if not m:
        return 0
    return int(float(m.group(1)) * {'': 1, 'k': 1, 'm': 1024, 'g': 1024 * 1024}[m.group(2).lower()])
