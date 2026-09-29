"""Minimal Snippe collection client (mobile-money USSD push). Standard library only.

Docs: https://docs.snippe.sh/docs/2026-01-25 (API version 2026-01-25).
  POST /v1/payments            create a payment (payment_type=mobile) and send the PIN prompt
  GET  /v1/payments/{ref}      payment status: pending, completed, failed, voided, expired
  GET  /v1/payments/balance    used to test keys
Webhooks: X-Webhook-Signature = hex HMAC-SHA256(signing key, "{X-Webhook-Timestamp}.{raw body}").
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from collections import namedtuple

from config import Config

# Whose Snippe account: the platform's (.env) or a tenant's own
Credentials = namedtuple('Credentials', 'api_key webhook_key')

MIN_AMOUNT = 500              # TZS, set by Snippe
WEBHOOK_TOLERANCE = 300       # seconds: reject older (replayed) webhooks


def platform_credentials():
    return Credentials(Config.SNIPPE_API_KEY, Config.SNIPPE_WEBHOOK_KEY)


class SnippeError(Exception):
    pass


def is_configured(creds=None):
    creds = creds or platform_credentials()
    return bool(creds.api_key)


def _request(method, path, creds, body=None, idempotency_key=None, timeout=20):
    url = Config.SNIPPE_BASE_URL.rstrip('/') + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Authorization': f'Bearer {creds.api_key}', 'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key[:30]      # Snippe rejects longer keys
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reply = json.loads(resp.read() or b'null') or {}
    except urllib.error.HTTPError as e:
        text = e.read().decode('utf-8', 'replace')[:400]
        try:
            text = json.loads(text).get('message') or text
        except (ValueError, AttributeError):
            pass
        raise SnippeError(f'{e.code}: {text}') from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SnippeError(f'Snippe unreachable: {e}') from None
    if reply.get('status') == 'error':
        raise SnippeError(f"{reply.get('code')}: {reply.get('message') or reply.get('error_code')}")
    return reply.get('data') if isinstance(reply, dict) and 'data' in reply else reply


def test_credentials(creds):
    """Raises SnippeError if Snippe rejects the key."""
    _request('GET', '/v1/payments/balance', creds)


def create_payment(amount, phone, reference, creds, webhook_url=None, customer=None):
    """Create a mobile-money payment; Snippe sends the PIN prompt to `phone` (255XXXXXXXXX).
    `reference` (ours, <=30 chars) is the idempotency key and is kept in metadata.
    Returns Snippe's payment: {'reference': <Snippe id>, 'status': 'pending', ...}."""
    body = {
        'payment_type': 'mobile',
        'details': {'amount': int(amount), 'currency': 'TZS'},
        'phone_number': phone,
        'customer': customer or {'firstname': 'WiFi', 'lastname': 'Guest', 'email': Config.SNIPPE_CUSTOMER_EMAIL},
        'metadata': {'order_reference': reference},
    }
    if webhook_url:
        body['webhook_url'] = webhook_url[:500]
    return _request('POST', '/v1/payments', creds, body, idempotency_key=reference) or {}


def get_payment(snippe_reference, creds):
    """Latest state of a Snippe payment, or None if Snippe doesn't know it."""
    try:
        return _request('GET', f'/v1/payments/{snippe_reference}', creds) or None
    except SnippeError as e:
        if str(e).startswith('404'):
            return None
        raise


def verify_webhook(raw_body, timestamp, signature, signing_key, now=None):
    """True if the webhook really comes from Snippe (and is recent)."""
    if not (raw_body is not None and timestamp and signature and signing_key):
        return False
    try:
        if abs((now or time.time()) - int(timestamp)) > WEBHOOK_TOLERANCE:
            return False
    except (TypeError, ValueError):
        return False
    body = raw_body.decode('utf-8') if isinstance(raw_body, bytes) else raw_body
    expected = hmac.new(signing_key.encode(), f'{timestamp}.{body}'.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())
