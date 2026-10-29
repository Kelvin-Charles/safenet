"""Mobile-money collection through ClickPesa or Snippe, behind one interface.

An Account says which provider, whose keys, and whose money it is:
  owner 'platform' = SafeNet Pay (the platform's account, the platform fee applies)
  owner 'own'      = the tenant's own ClickPesa or Snippe account
"""
from collections import namedtuple
from decimal import Decimal

import clickpesa
import snippe
from config import Config
from gateway import portal_ui

PROVIDERS = {'clickpesa': 'ClickPesa', 'snippe': 'Snippe'}

Account = namedtuple('Account', 'provider creds owner')


class PaymentError(Exception):
    """`str(e)` is safe to show a guest; `detail` is for the payment record. `unsure`: the provider couldn't be reached
    or didn't answer in time, so the request may have gone through (the payment stays pending and is checked again)."""
    def __init__(self, message, detail=None, unsure=False):
        super().__init__(message)
        self.detail = (detail or message)[:255]
        self.unsure = unsure


def platform_account(provider, creds=None):
    """SafeNet Pay's account at a provider. `creds` overrides the .env keys (keys saved in Platform settings)."""
    creds = creds or (snippe.platform_credentials() if provider == 'snippe' else clickpesa.platform_credentials())
    return Account(provider if provider in PROVIDERS else 'clickpesa', creds, 'platform')


def is_ready(account):
    if account is None:
        return False
    return snippe.is_configured(account.creds) if account.provider == 'snippe' else clickpesa.is_configured(account.creds)


def name(account):
    return PROVIDERS.get(account.provider, account.provider) if account else ''


def networks(account):
    """Mobile-money networks guests can pay with, and their minimum amounts."""
    if account is not None and account.provider == 'snippe':
        return portal_ui.parse_networks(Config.SNIPPE_NETWORKS)
    return portal_ui.parse_networks(Config.PAYMENT_NETWORKS)


def test(account):
    """Raises PaymentError if the provider rejects the keys."""
    try:
        if account.provider == 'snippe':
            snippe.test_credentials(account.creds)
        else:
            clickpesa.test_credentials(account.creds)
    except (snippe.SnippeError, clickpesa.ClickPesaError) as e:
        raise PaymentError(str(e)) from None


def start(account, amount, phone, reference, network=None, webhook_url=None, payer=None):
    """Send the PIN prompt. Returns {'provider_id', 'status' ('pending'), 'channel'}; raises PaymentError."""
    if account.provider == 'snippe':
        if amount < snippe.MIN_AMOUNT:
            raise PaymentError(f'Mobile-money payments start from TZS {snippe.MIN_AMOUNT:,}.')
        try:
            data = snippe.create_payment(amount, phone, reference, account.creds, webhook_url=webhook_url,
                                         customer=snippe.customer(*payer) if payer else None)
        except snippe.SnippeError as e:
            raise PaymentError("We couldn't send the payment request. Check the number and try again.", str(e),
                               unsure='unreachable' in str(e)) from None
        if not data.get('reference'):
            raise PaymentError("We couldn't send the payment request. Please try again.", 'Snippe returned no reference')
        status = (data.get('status') or 'pending').lower()
        if status in ('failed', 'voided', 'expired'):
            raise PaymentError("We couldn't send the payment request. Check the number and try again.", f'Snippe: {status}')
        return {'provider_id': data['reference'], 'status': 'pending', 'channel': None, 'provider_status': status.upper()}

    # ClickPesa: check the number and which methods are up, then push
    try:
        available = clickpesa.preview_ussd_push(amount, phone, reference, account.creds)
        offered = {portal_ui.network_for_method(m) for m in available}
        if available and network and network not in offered:
            label = portal_ui.NETWORKS.get(network, {}).get('name', 'That network')
            raise PaymentError(f"{label} isn't available for this number right now. Try another network.",
                               f'{network} not offered by ClickPesa for this number ({", ".join(available)})')
        if not available:
            raise PaymentError("Mobile money for this number isn't available right now. Try another number or a voucher.",
                               'No mobile-money method available for this number')
        tx = clickpesa.initiate_ussd_push(amount, phone, reference, account.creds) or {}
    except clickpesa.ClickPesaError as e:
        raise PaymentError("We couldn't send the payment request. Check the number and try again.", str(e),
                           unsure='unreachable' in str(e)) from None
    status = (tx.get('status') or '').upper() or None
    if status == 'FAILED':
        raise PaymentError("We couldn't send the payment request. Check the number and try again.", 'ClickPesa: FAILED')
    return {'provider_id': tx.get('id'), 'status': 'pending', 'channel': tx.get('channel'), 'provider_status': status}


SNIPPE_ENDED = {'expired': 'The payment request expired: the PIN was not entered in time.',
                'voided': 'The payment was cancelled.'}


def failure_reason(record):
    """Why a Snippe payment didn't go through, as Snippe says it (e.g. "Insufficient balance on customer's account.")."""
    status = (record.get('status') or '').lower()
    reason = str(record.get('failure_reason') or '').strip()
    if reason and reason.lower() not in ('payment failed', 'payment failed.'):
        return reason[:200]
    return SNIPPE_ENDED.get(status) or reason[:200] or 'The payment was not completed.'


def check(account, reference, provider_id=None):
    """Where a payment stands: {'state': 'paid'|'failed'|'pending'|None, 'amount', 'channel', 'provider_status', 'message'}.
    state None = the provider doesn't know it (yet). Raises PaymentError if the provider can't be reached."""
    try:
        if account.provider == 'snippe':
            # no Snippe id yet (its answer to the request was lost): find it by our reference
            record = snippe.get_payment(provider_id, account.creds) if provider_id else snippe.find_payment(reference, account.creds)
            if not record:
                return {'state': None}
            status = (record.get('status') or '').lower()
            amount = (record.get('amount') or {}).get('value') if isinstance(record.get('amount'), dict) else record.get('amount')
            channel = record.get('channel') or {}
            return {'state': {'completed': 'paid', 'failed': 'failed', 'voided': 'failed', 'expired': 'failed'}.get(status, 'pending'),
                    'amount': Decimal(str(amount)) if amount is not None else None,
                    'channel': (channel.get('provider') if isinstance(channel, dict) else channel) or None,
                    'provider_status': status.upper() or None,
                    'message': failure_reason(record) if status in ('failed', 'voided', 'expired') else None,
                    'provider_id': record.get('reference')}
        record = clickpesa.query_payment(reference, account.creds)
    except (snippe.SnippeError, clickpesa.ClickPesaError) as e:
        raise PaymentError(str(e)) from None
    if not record:
        return {'state': None}
    status = (record.get('status') or '').upper()
    collected = record.get('collectedAmount')
    return {'state': 'paid' if status in ('SUCCESS', 'SETTLED') else 'failed' if status == 'FAILED' else 'pending',
            'amount': Decimal(str(collected)) if collected is not None else None,
            'channel': record.get('channel'), 'provider_status': status or None, 'message': record.get('message')}
