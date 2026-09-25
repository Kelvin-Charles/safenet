"""TP-Link Omada Controller client for the External Portal Server flow.

How it works with SafeNet:
  1. The Omada Controller sends unauthenticated guests to SafeNet's login page
     (/omada/<site token>) with clientMac, apMac, ssidName, radioId, site, redirectUrl
     (or gatewayMac and vid when an Omada gateway runs the portal).
  2. The guest enters a voucher or pays with mobile money on SafeNet's page.
  3. SafeNet logs in to the controller as a hotspot operator and calls
     extPortal/auth, which lets the guest online for the paid time.

Written against the Omada SDN Controller v5 External Portal API:
  GET  /api/info                                -> result.omadacId
  POST /{omadacId}/api/v2/hotspot/login         {"name", "password"} -> result.token + session cookie
  POST /{omadacId}/api/v2/hotspot/extPortal/auth  (header Csrf-Token) -> errorCode 0
Controllers usually have a self-signed certificate, so TLS checking is optional.
"""
import http.cookiejar
import json
import ssl
import urllib.error
import urllib.request


class OmadaError(Exception):
    pass


AUTH_TYPE_EXTERNAL_PORTAL = '4'
MAX_SECONDS = 30 * 86400


class Controller:
    def __init__(self, url, username, password, verify_tls=False, timeout=10):
        self.base = (url or '').rstrip('/')
        self.username = username or ''
        self.password = password or ''
        self.timeout = timeout
        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                                  urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._cid = None
        self._token = None

    def _request(self, method, path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header('Accept', 'application/json')
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        if token:
            req.add_header('Csrf-Token', token)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise OmadaError(f'controller answered HTTP {e.code} for {path}') from e
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, 'reason', e)
            raise OmadaError(f"can't reach the controller at {self.base} ({reason})") from e
        try:
            reply = json.loads(raw or b'{}')
        except ValueError as e:
            raise OmadaError(f'controller sent something that is not JSON for {path}') from e
        if reply.get('errorCode', 0) != 0:
            raise OmadaError(f"controller refused {path}: {reply.get('msg') or reply.get('errorCode')}")
        return reply.get('result') or {}

    def controller_id(self):
        if self._cid is None:
            self._cid = str(self._request('GET', '/api/info').get('omadacId') or '')
        return self._cid

    def _prefix(self):
        cid = self.controller_id()
        return f'/{cid}' if cid else ''

    def login(self):
        result = self._request('POST', f'{self._prefix()}/api/v2/hotspot/login',
                               {'name': self.username, 'password': self.password})
        self._token = result.get('token')
        if not self._token:
            raise OmadaError('controller login gave no token: check the hotspot operator name and password')
        return self._token

    def authorize(self, client_mac, seconds, *, site, ap_mac=None, ssid=None, radio_id=None,
                  gateway_mac=None, vid=None):
        """Let a guest online for `seconds`. EAP portals send apMac/ssidName/radioId;
        gateway portals send gatewayMac/vid."""
        if not client_mac or not site:
            raise OmadaError('the login page was opened without the Omada details (clientMac/site)')
        seconds = max(60, min(int(seconds), MAX_SECONDS))
        body = {'clientMac': client_mac, 'site': site, 'time': str(seconds * 1_000_000),
                'authType': AUTH_TYPE_EXTERNAL_PORTAL}
        if ap_mac:
            body.update(apMac=ap_mac, ssidName=ssid or '', radioId=str(radio_id if radio_id is not None else '0'))
        else:
            body.update(gatewayMac=gateway_mac or '', vid=str(vid or ''))
        token = self._token or self.login()
        try:
            return self._request('POST', f'{self._prefix()}/api/v2/hotspot/extPortal/auth', body, token=token)
        except OmadaError:
            # The operator session may have expired: log in again once
            token = self.login()
            return self._request('POST', f'{self._prefix()}/api/v2/hotspot/extPortal/auth', body, token=token)

    def check(self):
        """Connect and log in; returns the controller id (empty for older controllers)."""
        cid = self.controller_id()
        self.login()
        return cid
