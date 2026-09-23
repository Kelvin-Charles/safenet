"""Minimal ClickPesa collection client (USSD push). Standard library only.

Docs: https://docs.clickpesa.com (no sandbox - every call is live).
"""
import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request

from config import Config


class ClickPesaError(Exception):
    pass


_token = {'value': None, 'expires': 0.0}
_token_lock = threading.Lock()


def is_configured():
    return bool(Config.CLICKPESA_CLIENT_ID and Config.CLICKPESA_API_KEY)


def _request(method, path, body=None, headers=None, timeout=20):
    url = Config.CLICKPESA_BASE_URL.rstrip('/') + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Content-Type': 'application/json', 'Accept': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:300]
        try:
            detail = json.loads(detail).get('message', detail)
        except (ValueError, AttributeError):
            pass
        raise ClickPesaError(f'{e.code}: {detail}') from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ClickPesaError(f'ClickPesa unreachable: {e}') from None


def _auth_header():
    """Tokens last 1 hour and already include the 'Bearer ' prefix."""
    with _token_lock:
        if _token['value'] and time.time() < _token['expires']:
            return _token['value']
        data = _request('POST', '/third-parties/generate-token', headers={
            'client-id': Config.CLICKPESA_CLIENT_ID, 'api-key': Config.CLICKPESA_API_KEY})
        token = (data or {}).get('token')
        if not token:
            raise ClickPesaError('ClickPesa did not return a token')
        _token['value'] = token if token.startswith('Bearer ') else f'Bearer {token}'
        _token['expires'] = time.time() + 55 * 60
        return _token['value']


def _canonical(obj):
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_canonical(v) for v in obj]
    return obj


def checksum(payload):
    """HMAC-SHA256 over the key-sorted compact JSON (checksum fields excluded)."""
    body = {k: v for k, v in payload.items() if k not in ('checksum', 'checksumMethod')}
    text = json.dumps(_canonical(body), separators=(',', ':'))
    return hmac.new(Config.CLICKPESA_CHECKSUM_KEY.encode(), text.encode(), hashlib.sha256).hexdigest()


def _payment_payload(amount, phone, reference):
    payload = {
        'amount': str(int(amount)) if float(amount).is_integer() else str(amount),
        'currency': 'TZS',
        'orderReference': reference,
        'phoneNumber': phone,
    }
    if Config.CLICKPESA_CHECKSUM_KEY:
        payload['checksum'] = checksum(payload)
    return payload


def preview_ussd_push(amount, phone, reference):
    """Checks the number and which mobile-money methods are up, without charging.
    Returns the list of available method names (e.g. ['M-PESA'])."""
    data = _request('POST', '/third-parties/payments/preview-ussd-push-request',
                    _payment_payload(amount, phone, reference),
                    headers={'Authorization': _auth_header()}) or {}
    methods = data.get('activeMethods') or []
    return [m.get('name') for m in methods if (m.get('status') or '').upper() == 'AVAILABLE']


def initiate_ussd_push(amount, phone, reference):
    """Sends the PIN prompt to the customer's phone. Returns ClickPesa's transaction."""
    return _request('POST', '/third-parties/payments/initiate-ussd-push-request',
                    _payment_payload(amount, phone, reference),
                    headers={'Authorization': _auth_header()})


def query_payment(reference):
    """Latest ClickPesa record for an order reference, or None if unknown."""
    try:
        data = _request('GET', f'/third-parties/payments/{reference}',
                        headers={'Authorization': _auth_header()})
    except ClickPesaError as e:
        if str(e).startswith('404'):
            return None
        raise
    if isinstance(data, list):
        if not data:
            return None
        paid = [r for r in data if r.get('status') in ('SUCCESS', 'SETTLED')]
        return paid[0] if paid else max(data, key=lambda r: r.get('updatedAt') or '')
    return data
