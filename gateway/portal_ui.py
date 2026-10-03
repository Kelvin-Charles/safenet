"""Captive portal pages, shared by the SafeNet gateway (portal.py) and the
SafeNet web app (settings preview, MikroTik/Meraki external login page).

Pure functions returning HTML; standard library only. Everything is inline
(CSS from portal.css, SVG icons) because guests are not online yet.
"""
import html
import os
import re
from urllib.parse import urlencode, urlparse

_CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portal.css')
with open(_CSS_PATH, encoding='utf-8') as _f:
    CSS = _f.read()

DEFAULT_COLOR = '#051D60'
STYLES = ('gradient', 'solid', 'light')
LANGS = ('en', 'sw')

e = html.escape

# Mobile-money networks. Which ones are offered (and their minimum amount) is
# configured in SafeNet (PAYMENT_NETWORKS); logos live in static/img (the
# gateway serves its own copy under /img/).
NETWORKS = {
    'mpesa':    {'name': 'M-Pesa', 'operator': 'Vodacom', 'logo': 'mpesa.png', 'prefixes': ('74', '75', '76'),
                 'match': ('MPESA', 'M-PESA', 'VODA')},
    'mixx':     {'name': 'Mixx by Yas', 'operator': 'Yas', 'logo': 'yas-1024x724.jpg', 'prefixes': ('65', '67', '71', '77'),
                 'match': ('TIGO', 'MIXX', 'YAS')},
    'airtel':   {'name': 'Airtel Money', 'operator': 'Airtel', 'logo': 'airtel.png', 'prefixes': ('68', '69', '78'),
                 'match': ('AIRTEL',)},
    'halopesa': {'name': 'HaloPesa', 'operator': 'Halotel', 'logo': 'halopesa.png', 'prefixes': ('61', '62'),
                 'match': ('HALO',)},
}


def parse_networks(spec):
    """'mixx:1000,airtel,halopesa' -> [{'id', 'name', 'min_amount'}] in that order (unknown ids skipped)."""
    out = []
    for part in (spec or '').split(','):
        key, _, minimum = part.strip().partition(':')
        if key in NETWORKS and not any(n['id'] == key for n in out):
            out.append({'id': key, 'name': NETWORKS[key]['name'], 'min_amount': int(minimum) if minimum.isdigit() else 0})
    return out


LOGOS_VERSION = 2   # bump when a logo file changes (proxies may keep an old copy or a 404)


def normalize_phone(raw):
    """Any way a Tanzanian mobile number is typed -> 255XXXXXXXXX, else None.
    0712 345 678, 712345678, +255 712..., 255712..., +255 0712... (the 0 kept by habit), 00255712..."""
    d = re.sub(r'\D', '', raw or '')
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('2550') and len(d) == 13:
        d = '255' + d[4:]
    if len(d) == 10 and d.startswith('0'):
        d = '255' + d[1:]
    elif len(d) == 9:
        d = '255' + d
    return d if re.fullmatch(r'255[67]\d{8}', d) else None


def network_for_phone(phone):
    """Network id for a 255XXXXXXXXX / 0XXXXXXXXX number, or None if the prefix is unknown."""
    full = normalize_phone(phone)
    digits = re.sub(r'\D', '', phone or '')
    local = full[3:] if full else (digits[3:] if digits.startswith('255') else digits.lstrip('0'))
    for key, info in NETWORKS.items():
        if local[:2] in info['prefixes']:
            return key
    return None


def network_for_method(method):
    """Map a ClickPesa method name (e.g. 'TIGO-PESA') to a network id."""
    name = (method or '').upper().replace(' ', '')
    for key, info in NETWORKS.items():
        if any(m.replace(' ', '') in name for m in info['match']):
            return key
    return None

# ---------------------------------------------------------------------------
# Text (English / Kiswahili)
# ---------------------------------------------------------------------------
T = {
    'en': {
        'wifi': 'Guest Wi-Fi', 'switch': 'Kiswahili', 'welcome': 'Welcome to {name}',
        'welcome_msg': 'Connect in seconds with a voucher, or buy a package with mobile money.',
        'tab_voucher': 'Voucher', 'tab_buy': 'Buy package',
        'voucher_title': 'Enter your voucher', 'voucher_lead': 'Type the code printed on your voucher.',
        'code': 'Voucher code', 'code_ph': '12345678',
        'have_account': 'I have a username and password', 'username': 'Username', 'password': 'Password',
        'accept': 'I accept the', 'terms': 'terms of use', 'connect': 'Connect',
        'buy_title': 'Choose a package', 'buy_lead': 'Pick a package, then your mobile-money network.',
        'network': 'Your mobile-money network', 'min_from': 'From {amount}', 'choose_network': 'Choose your network first',
        'phone': 'Mobile money number', 'pay': 'Pay {price}', 'pay_hint': "You'll get a PIN prompt on your phone. Once paid, you're connected automatically and the code is sent to you by SMS.",
        'pay_hint_nosms': "You'll get a PIN prompt on your phone. Once paid, you're connected automatically and your code is shown here: write it down.",
        'no_packages': 'No packages are on sale right now. Ask at the counter for a voucher.',
        'check_phone': 'Check your phone', 'wait_lead': 'Enter your mobile-money PIN to pay {amount} for {package}.',
        'wait_step1': 'Unlock your phone and open the payment prompt', 'wait_step2': 'Enter your PIN to approve {amount}',
        'wait_step3': "Stay on this page: you'll be connected automatically",
        'sent_to': 'Sent to {phone}', 'auto_update': 'This page updates by itself.',
        'still_waiting': 'Still waiting for your payment', 'still_lead': "We haven't received confirmation for {amount} from {phone} yet.",
        'paid_check': "I've paid, check again", 'start_over': 'Start over',
        'online': "You're online", 'time_left': 'Time left', 'on': 'on {user}',
        'paid_ok': 'Payment received. Thank you!', 'your_code': 'Your voucher code', 'copy': 'Copy', 'copied': 'Copied',
        'keep_code': 'Keep it: use it to reconnect if you get disconnected.',
        'continue_to': 'Continue to {host}', 'browse': 'Start browsing', 'disconnect': 'Disconnect',
        'help': 'Need help?', 'call': 'Call {phone}', 'powered': 'Powered by Safezone Tech', 'close': 'Close',
        'perk_fast': 'Fast, reliable internet', 'perk_pay': 'Pay easily with mobile money', 'perk_safe': 'Your connection, your time',
        'how_title': 'How to connect', 'how_lead': 'Buy a voucher at the counter, then:',
        'how1': 'Join the Wi-Fi network {ssid}', 'how2': 'If asked for EAP method choose <code>PEAP</code>, phase 2 <code>MSCHAPV2</code>',
        'how3': 'CA certificate: <code>Don\'t validate</code> (Android) or tap <b>Trust</b> (iPhone)',
        'how4': 'Username and password: your voucher code. Leave <i>anonymous identity</i> empty.',
        'preview': 'Preview', 'left': 'left', 'total': 'total',
        'busy_pay': 'Sending payment request…', 'busy_connect': 'Connecting…', 'busy_pay_hint': 'Please wait, this takes a few seconds.',
        'gift': 'Buy for a friend: send the code to their phone', 'gift_phone': "Friend's phone number",
        'gift_hint': 'You pay with your number above. Your friend gets the code by SMS.',
        'wait_step3_gift': "Stay on this page: we'll send the code to {phone} by SMS",
        'gift_ok': 'Payment received. The code is on its way!', 'gift_lead': 'We sent the {package} code to {phone} by SMS.',
        'gift_code': "Your friend's code", 'gift_share': "If the SMS doesn't arrive, share this code with them yourself.",
        'gift_again': 'Back to packages',
        'app_cta': 'Get the Wi-Fi app', 'app_cta_lead': 'See your time and data, buy more, buy for a friend.',
    },
    'sw': {
        'wifi': 'Wi-Fi ya Wageni', 'switch': 'English', 'welcome': 'Karibu {name}',
        'welcome_msg': 'Unganishwa haraka kwa vocha, au nunua kifurushi kwa simu yako.',
        'tab_voucher': 'Vocha', 'tab_buy': 'Nunua kifurushi',
        'voucher_title': 'Weka vocha yako', 'voucher_lead': 'Andika namba iliyo kwenye vocha yako.',
        'code': 'Namba ya vocha', 'code_ph': '12345678',
        'have_account': 'Nina jina la mtumiaji na nenosiri', 'username': 'Jina la mtumiaji', 'password': 'Nenosiri',
        'accept': 'Nakubali', 'terms': 'masharti ya matumizi', 'connect': 'Unganisha',
        'buy_title': 'Chagua kifurushi', 'buy_lead': 'Chagua kifurushi, kisha mtandao wako wa malipo.',
        'network': 'Mtandao wako wa malipo', 'min_from': 'Kuanzia {amount}', 'choose_network': 'Chagua mtandao kwanza',
        'phone': 'Namba ya simu ya malipo', 'pay': 'Lipa {price}', 'pay_hint': 'Utapokea ujumbe wa kuweka PIN kwenye simu yako. Ukishalipa utaunganishwa moja kwa moja na namba ya vocha itatumwa kwa SMS.',
        'pay_hint_nosms': 'Utapokea ujumbe wa kuweka PIN kwenye simu yako. Ukishalipa utaunganishwa moja kwa moja na namba ya vocha itaonyeshwa hapa: iandike.',
        'no_packages': 'Hakuna vifurushi vinavyouzwa kwa sasa. Uliza vocha kaunta.',
        'check_phone': 'Angalia simu yako', 'wait_lead': 'Weka PIN yako kulipia {amount} kwa {package}.',
        'wait_step1': 'Fungua simu yako na ufungue ujumbe wa malipo', 'wait_step2': 'Weka PIN kuidhinisha {amount}',
        'wait_step3': 'Baki kwenye ukurasa huu: utaunganishwa moja kwa moja',
        'sent_to': 'Imetumwa kwa {phone}', 'auto_update': 'Ukurasa huu unajisasisha wenyewe.',
        'still_waiting': 'Bado tunasubiri malipo yako', 'still_lead': 'Bado hatujapokea uthibitisho wa {amount} kutoka {phone}.',
        'paid_check': 'Nimelipa, angalia tena', 'start_over': 'Anza upya',
        'online': 'Umeunganishwa', 'time_left': 'Muda uliobaki', 'on': 'kwenye {user}',
        'paid_ok': 'Malipo yamepokelewa. Asante!', 'your_code': 'Namba yako ya vocha', 'copy': 'Nakili', 'copied': 'Imenakiliwa',
        'keep_code': 'Ihifadhi: itumie kuunganisha tena ukikatika.',
        'continue_to': 'Endelea kwenda {host}', 'browse': 'Anza kutumia intaneti', 'disconnect': 'Tenganisha',
        'help': 'Unahitaji msaada?', 'call': 'Piga {phone}', 'powered': 'Inaendeshwa na Safezone Tech', 'close': 'Funga',
        'perk_fast': 'Intaneti ya kasi na ya uhakika', 'perk_pay': 'Lipa kwa urahisi kwa simu', 'perk_safe': 'Muunganisho wako, muda wako',
        'how_title': 'Jinsi ya kuunganishwa', 'how_lead': 'Nunua vocha kaunta, kisha:',
        'how1': 'Unganisha kwenye mtandao wa Wi-Fi {ssid}', 'how2': 'Ukiulizwa EAP method chagua <code>PEAP</code>, phase 2 <code>MSCHAPV2</code>',
        'how3': 'CA certificate: <code>Don\'t validate</code> (Android) au bonyeza <b>Trust</b> (iPhone)',
        'how4': 'Jina la mtumiaji na nenosiri: namba ya vocha yako. Acha <i>anonymous identity</i> wazi.',
        'preview': 'Onyesho', 'left': 'imebaki', 'total': 'jumla',
        'busy_pay': 'Inatuma ombi la malipo…', 'busy_connect': 'Inaunganisha…', 'busy_pay_hint': 'Tafadhali subiri, inachukua sekunde chache.',
        'gift': 'Nunulia rafiki: tuma vocha kwenye simu yake', 'gift_phone': 'Namba ya simu ya rafiki',
        'gift_hint': 'Unalipa kwa namba yako hapo juu. Rafiki yako atapokea namba ya vocha kwa SMS.',
        'wait_step3_gift': 'Baki kwenye ukurasa huu: tutatuma vocha kwa {phone} kwa SMS',
        'gift_ok': 'Malipo yamepokelewa. Vocha imetumwa!', 'gift_lead': 'Tumetuma vocha ya {package} kwa {phone} kwa SMS.',
        'gift_code': 'Namba ya vocha ya rafiki', 'gift_share': 'SMS isipofika, mtumie namba hii wewe mwenyewe.',
        'gift_again': 'Rudi kwenye vifurushi',
        'app_cta': 'Pata app ya Wi-Fi', 'app_cta_lead': 'Ona muda na data yako, nunua zaidi, nunulia rafiki.',
    },
}

# Messages that come from the gateway or SafeNet in English
MESSAGES_SW = {
    "That code isn't valid. Check it and try again.": 'Namba hiyo si sahihi. Iangalie na ujaribu tena.',
    'Please accept the terms of use to continue.': 'Tafadhali kubali masharti ya matumizi ili kuendelea.',
    'Enter your voucher code.': 'Weka namba ya vocha.',
    'Too many wrong attempts. Please wait a few minutes and try again.': 'Umejaribu mara nyingi. Subiri dakika chache kisha ujaribu tena.',
    "We can't reach the login server right now. Please try again in a minute.": 'Hatuwezi kufikia seva kwa sasa. Jaribu tena baada ya dakika moja.',
    "We couldn't identify your device. Turn Wi-Fi off and on, then try again.": 'Hatukuweza kutambua kifaa chako. Zima Wi-Fi na uwashe tena, kisha ujaribu.',
    'Something went wrong on our side. Please try again.': 'Kuna tatizo upande wetu. Tafadhali jaribu tena.',
    'Choose a package.': 'Chagua kifurushi.',
    'Too many payment requests. Please wait a few minutes.': 'Maombi mengi ya malipo. Subiri dakika chache.',
    "We can't reach the payment server right now. Please try again.": 'Hatuwezi kufikia huduma ya malipo kwa sasa. Jaribu tena.',
    'Voucher expired or disabled': 'Vocha imeisha muda au imezimwa',
    'This account is disabled': 'Akaunti hii imezimwa',
    'This account has expired': 'Akaunti hii imeisha muda',
    'Enter a valid mobile number, e.g. 0712 345 678.': 'Weka namba sahihi ya simu, mfano 0712 345 678.',
    'A payment request was just sent to this number. Check your phone, or wait a minute.': 'Ombi la malipo limetumwa sasa hivi kwa namba hii. Angalia simu yako au subiri dakika moja.',
    'Payment not completed: ': 'Malipo hayajakamilika: ',
    'Choose your mobile-money network.': 'Chagua mtandao wako wa malipo.',
    'This code is already being used on another device.': 'Namba hii tayari inatumika kwenye kifaa kingine.',
    'This phone has already had a free trial. Buy a package to keep browsing.':
        'Simu hii tayari imetumia jaribio la bure. Nunua kifurushi kuendelea kutumia intaneti.',
    'The payment was not completed.': 'Malipo hayakukamilika.',
    "Enter your friend's mobile number, e.g. 0712 345 678.": 'Weka namba sahihi ya simu ya rafiki yako, mfano 0712 345 678.',
}


def local_phone(phone):
    """255712345678 -> 0712 345 678 (other text unchanged)."""
    d = re.sub(r'\D', '', phone or '')
    if len(d) == 12 and d.startswith('255'):
        return f'0{d[3:6]} {d[6:9]} {d[9:]}'
    return phone or ''


def t(lang, key, **kw):
    text = T.get(lang, T['en']).get(key) or T['en'][key]
    return text.format(**kw) if kw else text


def tr(lang, message):
    """Translate a known English message (keeps unknown text as is)."""
    if lang != 'sw' or not message:
        return message
    for en, sw in MESSAGES_SW.items():
        if message == en:
            return sw
        if en.endswith(': ') and message.startswith(en):
            return sw + tr(lang, message[len(en):])
    return message


def duration(minutes, lang='en'):
    """1440 -> '1 day' / 'Siku 1'; 90 -> '1h 30m' / 'Saa 1 dk 30'."""
    minutes = max(0, int(minutes))
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    if lang == 'sw':
        if days:
            return f'Siku {days}' + (f' saa {hours}' if hours else '')
        if hours:
            return f'Saa {hours}' + (f' dk {mins}' if mins else '')
        return f'Dakika {mins}'
    if days:
        return f'{days} day{"s" if days != 1 else ""}' + (f' {hours}h' if hours else '')
    if hours and mins:
        return f'{hours}h {mins}m'
    if hours:
        return f'{hours} hour{"s" if hours != 1 else ""}'
    return f'{mins} min'


def money(currency, amount):
    try:
        value = float(amount)
        text = f'{value:,.0f}' if value == int(value) else f'{value:,.2f}'
    except (TypeError, ValueError):
        text = str(amount or '')
    return f'{currency} {text}'.strip()


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _luminance(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def theme(cfg=None):
    """Normalise tenant portal settings (from SafeNet) into what the pages need."""
    cfg = cfg or {}
    color = cfg.get('color') if re.fullmatch(r'#[0-9a-fA-F]{6}', str(cfg.get('color') or '')) else DEFAULT_COLOR
    rgb = _rgb(color)
    name = (cfg.get('name') or 'Guest Wi-Fi').strip()
    lang = cfg.get('language') if cfg.get('language') in LANGS else 'en'
    return {
        'name': name,
        'color': color,
        'dark': _hex(c * 0.62 for c in rgb),
        'on': '#ffffff' if _luminance(rgb) < 0.5 else '#0f172a',
        'ring': 'rgba(%d,%d,%d,.16)' % rgb,
        'shadow': 'rgba(%d,%d,%d,.26)' % rgb,
        'tint': _hex(255 - (255 - c) * 0.09 for c in rgb),
        'style': cfg.get('style') if cfg.get('style') in STYLES else 'gradient',
        'title': (cfg.get('title') or '').strip(),
        'message': (cfg.get('message') or '').strip(),
        'support': (cfg.get('support') or '').strip(),
        'terms': (cfg.get('terms') or '').strip(),
        'language': lang,
        'logo_url': cfg.get('logo_url') or '',
        'show_voucher': cfg.get('show_voucher', True) is not False,
        'show_packages': cfg.get('show_packages', True) is not False,
        'sms': cfg.get('sms', True) is not False,          # codes are sent by SMS (off: shown on screen only)
        'ssid': (cfg.get('ssid') or '').strip(),
    }


# ---------------------------------------------------------------------------
# Icons (inline SVG, stroke = currentColor)
# ---------------------------------------------------------------------------
_ICON = {
    'wifi': '<path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 16a5 5 0 0 1 7 0"/><path d="M2 9a15 15 0 0 1 20 0"/><circle cx="12" cy="19.5" r=".8" fill="currentColor"/>',
    'ticket': '<path d="M3 8a2 2 0 0 0 0 4v0a2 2 0 0 0 0 4v2a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-2a2 2 0 0 1 0-4 2 2 0 0 1 0-4V6a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1z"/><path d="M14 5v14" stroke-dasharray="2 2"/>',
    'phone': '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    'check': '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'bolt': '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    'shield': '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    'copy': '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    'x': '<path d="M6 6l12 12M18 6 6 18"/>',
    'alert': '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/>',
    'call': '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
    'globe': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18"/>',
    'arrow': '<path d="M5 12h14M13 6l6 6-6 6"/>',
    'logout': '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H4"/>',
}


def icon(name, size=20, stroke=2):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICON[name]}</svg>')


# ---------------------------------------------------------------------------
# Page shell
# ---------------------------------------------------------------------------
def _qs(base, **params):
    params = {k: v for k, v in params.items() if v not in (None, '')}
    if not params:
        return base
    return base + ('&' if '?' in base else '?') + urlencode(params)


def page(th, lang, body, *, head='', lang_url='/', hero_extra=True, preview=False):
    other = 'sw' if lang == 'en' else 'en'
    title = th['title'] or t(lang, 'welcome', name=th['name'])
    message = th['message'] or t(lang, 'welcome_msg')
    logo = (f'<img src="{e(th["logo_url"])}" alt="{e(th["name"])}">' if th['logo_url']
            else f'<span class="initial">{e(th["name"][:1].upper() or "W")}</span>')
    perks = ''
    if hero_extra:
        perks = ('<div class="perks">'
                 f'<div><span>{icon("bolt", 19)}</span>{t(lang, "perk_fast")}</div>'
                 f'<div><span>{icon("phone", 19)}</span>{t(lang, "perk_pay")}</div>'
                 f'<div><span>{icon("shield", 19)}</span>{t(lang, "perk_safe")}</div></div>')
    support = ''
    if th['support']:
        tel = re.sub(r'[^\d+]', '', th['support'])
        support = f'<span>{t(lang, "help")} <a href="tel:{e(tel)}">{e(th["support"])}</a></span>'
    terms_link = (f'<button type="button" class="linkbtn" style="color:inherit" onclick="openTerms()">{t(lang, "terms").capitalize()}</button>'
                  if th['terms'] else '')
    style_vars = (f'--brand:{th["color"]};--brand-dark:{th["dark"]};--on-brand:{th["on"]};--brand-ring:{th["ring"]};'
                  f'--brand-shadow:{th["shadow"]};--tint:{th["tint"]}')
    terms_dialog = ''
    if th['terms']:
        terms_dialog = (f'<dialog id="terms" aria-labelledby="terms-h"><div class="dh"><span id="terms-h">{t(lang, "terms").capitalize()}</span>'
                        f'<button type="button" onclick="this.closest(\'dialog\').close()" aria-label="{t(lang, "close")}">{icon("x", 18)}</button></div>'
                        f'<div class="db">{e(th["terms"])}</div></dialog>')
    return f"""<!DOCTYPE html>
<html lang="{lang}" style="{style_vars}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="{th['color']}">
<title>{e(th['name'])}</title>
{head}
<style>{CSS}</style>
</head>
<body class="style-{th['style']}{' preview' if preview else ''}">
<div class="portal">
  <header class="hero">
    <div class="rings"></div>
    <div class="top">
      <span class="chip">{icon('wifi', 15, 2.4)} {t(lang, 'wifi')}</span>
      <a class="lang" href="{e(_qs(lang_url, lang=other))}" hreflang="{other}">{t(lang, 'switch')}</a>
    </div>
    <div class="id">
      <div class="logo">{logo}</div>
      <h1>{e(title)}</h1>
      <p>{e(message)}</p>
      {perks}
    </div>
  </header>
  <main class="sheet">
    <div class="card">{body}</div>
    <div class="foot">
      <div class="row">{support}{terms_link}</div>
      <div class="pw">{t(lang, 'powered')}</div>
    </div>
  </main>
</div>
{terms_dialog}
{'<div class="preview-ribbon">' + t(lang, 'preview') + '</div>' if preview else ''}
<script>
function openTerms(){{var d=document.getElementById('terms');if(!d)return;if(d.showModal){{d.showModal();}}else{{d.setAttribute('open','');}}}}
document.querySelectorAll('.pkg input').forEach(function(r){{r.addEventListener('change',function(){{
  document.querySelectorAll('.pkg').forEach(function(p){{p.classList.toggle('on',p.contains(document.querySelector('.pkg input:checked')));}});
  var b=document.getElementById('paybtn');if(b&&r.dataset.label)b.textContent=r.dataset.label;}});}});
document.querySelectorAll('form[data-busy]').forEach(function(f){{f.addEventListener('submit',function(ev){{
  if(f.dataset.sent){{ev.preventDefault();return;}}
  f.dataset.sent='1';
  var b=f.querySelector('button[type=submit]');
  if(b){{b.classList.add('loading');b.setAttribute('aria-busy','true');b.innerHTML='<span class="spinner" aria-hidden="true"></span>'+f.dataset.busy;}}
  var h=f.querySelector('.hint');if(h&&f.dataset.busyHint)h.textContent=f.dataset.busyHint;
  f.querySelectorAll('input,select,button.linkbtn').forEach(function(x){{x.setAttribute('readonly','');}});
}});}});
window.addEventListener('pageshow',function(ev){{if(ev.persisted)location.reload();}});
(function(){{
  var nets=document.querySelectorAll('.net');if(!nets.length)return;
  function price(){{var p=document.querySelector('.pkg input:checked');return p?parseFloat(p.dataset.price)||0:0;}}
  function paint(){{nets.forEach(function(n){{var r=n.querySelector('input');n.classList.toggle('on',r.checked);}});}}
  function limits(){{var pr=price();nets.forEach(function(n){{var r=n.querySelector('input'),low=pr<(parseInt(n.dataset.min)||0);
    n.classList.toggle('off',low);r.disabled=low;if(low&&r.checked)r.checked=false;}});paint();}}
  nets.forEach(function(n){{n.querySelector('input').addEventListener('change',paint);}});
  document.querySelectorAll('.pkg input').forEach(function(r){{r.addEventListener('change',limits);}});
  var ph=document.getElementById('phone');
  if(ph)ph.addEventListener('input',function(){{var d=ph.value.replace(/\\D/g,'');d=d.replace(/^00/,'');if(d.indexOf('255')===0)d=d.slice(3);d=d.replace(/^0/,'');
    if(d.length<2)return;nets.forEach(function(n){{var r=n.querySelector('input');
      if(!r.disabled&&(' '+n.dataset.prefixes+' ').indexOf(' '+d.slice(0,2)+' ')>=0){{r.checked=true;}}}});paint();}});
  limits();
}})();
</script>
</body>
</html>"""


def _alert(message, lang, ok=False):
    if not message:
        return ''
    return f'<div class="alert{" ok" if ok else ""}" role="alert">{icon("check" if ok else "alert", 18)}<span>{e(tr(lang, message))}</span></div>'


def _terms_check(th, lang, field_id):
    link = (f'<button type="button" class="linkbtn" onclick="openTerms()">{t(lang, "terms")}</button>' if th['terms']
            else t(lang, 'terms'))
    # ticked already: guests can untick it, and the server still requires it
    return (f'<label class="check" for="{field_id}"><input type="checkbox" id="{field_id}" name="agree" value="1" required checked>'
            f'<span>{t(lang, "accept")} {link}</span></label>')


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def login_page(th, lang, *, packages=(), dst='', error='', tab=None, action='/login', buy_action='/buy',
               external=None, buy_enabled=True, preview=False, lang_url='/', networks=(), logo_base='/img/', simulate=False):
    """Voucher and/or buy-package tabs.

    external: {'action': url, 'next_field': name, 'next_value': value} to post the
    code as username/password to a MikroTik or Meraki login URL instead of /login.
    """
    show_buy = th['show_packages'] and buy_enabled and bool(packages)
    show_voucher = th['show_voucher'] or not show_buy
    if tab is None:                     # buying is the default; the voucher is one tap away
        tab = 'buy' if show_buy else 'voucher'
    if not show_voucher:
        tab = 'buy'
    elif not show_buy:
        tab = 'voucher'
    submit_type = 'button' if preview and not simulate else 'submit'   # simulate: the preview's forms work (nothing charged)

    # Voucher panel
    if external:
        hidden = (f'<input type="hidden" name="username" id="x-user"><input type="hidden" name="password" id="x-pass">'
                  f'<input type="hidden" name="{e(external["next_field"])}" value="{e(external["next_value"])}">')
        names = ('x-code', 'x-u', 'x-p')
        onsubmit = ("var c=this.querySelector('#code').value.replace(/\\s+/g,''),u=this.querySelector('#u').value.trim();"
                    "this.querySelector('#x-user').value=u||c;this.querySelector('#x-pass').value=u?this.querySelector('#p').value:c;")
        form_attrs = f'method="post" action="{e(external["action"])}" onsubmit="{onsubmit}"'
    else:
        hidden = f'<input type="hidden" name="dst" value="{e(dst)}">'
        names = ('code', 'username', 'password')
        form_attrs = f'method="post" action="{e(action)}"'
    voucher = f"""
      <h2>{t(lang, 'voucher_title')}</h2>
      <p class="lead">{t(lang, 'voucher_lead')}</p>
      {_alert(error, lang) if tab == 'voucher' else ''}
      <form {form_attrs} autocomplete="off" data-busy="{e(t(lang, 'busy_connect'))}">
        {hidden}
        <div class="field">
          <label for="code">{t(lang, 'code')}</label>
          <input class="input code" type="text" id="code" name="{names[0]}" inputmode="numeric" autocomplete="one-time-code"
                 autocapitalize="off" spellcheck="false" placeholder="{t(lang, 'code_ph')}" {'autofocus' if tab == 'voucher' and not preview else ''}>
        </div>
        <details class="more">
          <summary>{t(lang, 'have_account')}</summary>
          <div class="field"><label for="u">{t(lang, 'username')}</label>
            <input class="input" type="text" id="u" name="{names[1]}" autocapitalize="off" autocomplete="username" spellcheck="false"></div>
          <div class="field"><label for="p">{t(lang, 'password')}</label>
            <input class="input" type="password" id="p" name="{names[2]}" autocomplete="current-password"></div>
        </details>
        {_terms_check(th, lang, 'agree-v')}
        <button class="btn" type="{submit_type}">{icon('wifi', 20, 2.4)} {t(lang, 'connect')}</button>
      </form>"""

    # Buy panel
    buy = ''
    if show_buy:
        options = []
        for i, p in enumerate(packages):
            price = money(p.get('currency', 'TZS'), p.get('price'))
            valid = duration(p['validity_minutes'], lang) if p.get('validity_minutes') else e(p.get('validity', ''))
            desc = f' · {e(p["description"])}' if p.get('description') else ''
            options.append(
                f'<label class="pkg{" on" if i == 0 else ""}"><input type="radio" name="package_id" value="{int(p["id"])}" '
                f'data-label="{e(t(lang, "pay", price=price))}" data-price="{e(str(p.get("price", "0")))}" required{" checked" if i == 0 else ""}>'
                f'<span class="ic">{icon("clock", 21)}</span>'
                f'<span class="nm"><b>{e(p["name"])}</b><small>{valid}{desc}</small></span>'
                f'<span class="pr">{e(price)}</span><span class="tick">{icon("check", 14, 3)}</span></label>')
        first_price = money(packages[0].get('currency', 'TZS'), packages[0].get('price'))
        net_tiles = ''
        if networks:
            tiles = []
            for n in networks:
                info = NETWORKS.get(n['id'])
                if not info:
                    continue
                minimum = int(n.get('min_amount') or 0)
                note = (f'<small class="net-min">{e(t(lang, "min_from", amount=money(packages[0].get("currency", "TZS"), minimum)))}</small>'
                        if minimum else '')
                tiles.append(
                    f'<label class="net" data-min="{minimum}" data-prefixes="{" ".join(info["prefixes"])}">'
                    f'<input type="radio" name="network" value="{e(n["id"])}" required>'
                    f'<img src="{e(logo_base + info["logo"])}?v={LOGOS_VERSION}" alt="{e(info["name"])}" loading="lazy">'
                    f'<span>{e(info["name"])}</span>{note}<span class="tick">{icon("check", 13, 3)}</span></label>')
            net_tiles = (f'<div class="field"><label>{t(lang, "network")}</label>'
                         f'<div class="nets" style="--n:{min(len(tiles), 4)}">{"".join(tiles)}</div></div>')
        # buying for a friend needs SMS (the code goes to the friend's phone)
        gift = f'''
        <label class="check" for="gift" style="margin:4px 0 10px"><input type="checkbox" id="gift" name="gift" value="1"
          onchange="var b=document.getElementById('gift-box'),i=document.getElementById('gift_phone');b.hidden=!this.checked;i.required=this.checked;if(this.checked)i.focus();">
          <span>{t(lang, 'gift')}</span></label>
        <div class="field" id="gift-box" hidden>
          <label for="gift_phone">{t(lang, 'gift_phone')}</label>
          <input class="input" type="tel" id="gift_phone" name="gift_phone" inputmode="tel" autocomplete="off" placeholder="07XX XXX XXX">
          <p class="hint" style="margin-top:6px">{t(lang, 'gift_hint')}</p>
        </div>''' if th['sms'] else ''
        buy = f"""
      <h2>{t(lang, 'buy_title')}</h2>
      <p class="lead">{t(lang, 'buy_lead')}</p>
      {_alert(error, lang) if tab == 'buy' else ''}
      <form method="post" action="{e(buy_action)}" data-busy="{e(t(lang, 'busy_pay'))}" data-busy-hint="{e(t(lang, 'busy_pay_hint'))}">
        <input type="hidden" name="dst" value="{e(dst)}">
        <div class="pkgs">{''.join(options)}</div>
        {net_tiles}
        <div class="field">
          <label for="phone">{t(lang, 'phone')}</label>
          <input class="input" type="tel" id="phone" name="phone" inputmode="tel" autocomplete="tel" placeholder="07XX XXX XXX" required>
        </div>
        {gift}
        {_terms_check(th, lang, 'agree-b')}
        <button class="btn" type="{submit_type}" id="paybtn">{e(t(lang, 'pay', price=first_price))}</button>
        <p class="hint">{t(lang, 'pay_hint' if th['sms'] else 'pay_hint_nosms')}</p>
      </form>"""

    if show_voucher and show_buy:
        body = f"""
      <input class="tab" type="radio" name="tab" id="tab-buy"{' checked' if tab == 'buy' else ''}>
      <input class="tab" type="radio" name="tab" id="tab-voucher"{' checked' if tab != 'buy' else ''}>
      <div class="tabs" role="tablist">
        <label for="tab-buy">{icon('phone', 17)} {t(lang, 'tab_buy')}</label>
        <label for="tab-voucher">{icon('ticket', 17)} {t(lang, 'tab_voucher')}</label>
      </div>
      <div class="panel panel-buy">{buy}</div>
      <div class="panel panel-voucher">{voucher}</div>"""
    elif show_buy:
        body = f'<div class="panel only">{buy}</div>'
    else:
        body = f'<div class="panel only">{voucher}</div>'
    return page(th, lang, body, lang_url=_qs(lang_url, dst=dst), preview=preview)


def status_page(th, lang, *, user, remaining, total=None, dst='', new_code=None, preview=False, base='', logout=True,
                lang_url='/', app_url=None):
    remaining = max(0, int(remaining))
    bar = ''
    if total and total > 0:
        left_pct = max(0, min(100, round(100 * remaining / total)))
        bar = (f'<div class="bar"><i style="width:{left_pct}%"></i></div>'
               f'<div class="meta"><span>{left_pct}% {t(lang, "left")}</span><span>{duration(total // 60, lang)} {t(lang, "total")}</span></div>')
    bought = ''
    if new_code:
        bought = (f'{_alert(t(lang, "paid_ok"), lang, ok=True)}'
                  f'<div class="codebox"><div><small>{t(lang, "your_code")}</small><b id="vcode">{e(new_code)}</b></div>'
                  f'<button type="button" class="copy" onclick="copyCode(this)">{icon("copy", 15)} <span>{t(lang, "copy")}</span></button></div>'
                  f'<p class="hint" style="margin-top:6px">{t(lang, "keep_code")}</p>')
    host = urlparse(dst).hostname if dst.startswith(('http://', 'https://')) else None
    go = (f'<a class="btn" href="{e(dst)}">{t(lang, "continue_to", host=e(host))} {icon("arrow", 18)}</a>' if host
          else f'<a class="btn" href="http://neverssl.com/">{t(lang, "browse")} {icon("arrow", 18)}</a>')
    body = f"""
      <div class="center">
        <div class="state-ic ok">{icon('check', 36, 2.6)}</div>
        <h2>{t(lang, 'online')}</h2>
        <p class="lead" style="margin-bottom:8px">{t(lang, 'time_left')} {t(lang, 'on', user=e(user))}</p>
        <div class="time">{duration(remaining // 60, lang)}</div>
      </div>
      {bar}
      {bought}
      <div style="margin-top:18px">{go}</div>
      {_app_card(lang, app_url)}
      {f'<form method="post" action="{e(base)}/logout"><button class="btn ghost" type="{"button" if preview else "submit"}">{icon("logout", 18)} {t(lang, "disconnect")}</button></form>' if logout else ''}
      <script>
      function copyCode(b){{var c=document.getElementById('vcode').textContent,s=b.querySelector('span');
        function done(){{s.textContent='{t(lang, "copied")}';}}
        if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(c).then(done);return;}}
        var i=document.createElement('input');i.value=c;document.body.appendChild(i);i.select();try{{document.execCommand('copy');done();}}catch(x){{}}i.remove();}}
      </script>"""
    return page(th, lang, body, hero_extra=False, preview=preview, lang_url=lang_url)


def _app_card(lang, app_url):
    """'Get the Wi-Fi app' on the connected screen (opens in the phone's browser, where it can be installed)."""
    if not app_url:
        return ''
    return (f'<a class="appcard" href="{e(app_url)}" target="_blank" rel="noopener">'
            f'<span class="ic">{icon("phone", 22)}</span><span><b>{t(lang, "app_cta")}</b>'
            f'<small>{t(lang, "app_cta_lead")}</small></span>{icon("arrow", 18)}</a>')


def gift_page(th, lang, *, code, friend, package='', base='', lang_url='/', preview=False):
    """Paid for a friend: the code went to their phone by SMS; this device stays offline."""
    body = f"""
      <div class="center">
        <div class="state-ic ok">{icon('check', 36, 2.6)}</div>
        <h2>{t(lang, 'gift_ok')}</h2>
        <p class="lead">{e(t(lang, 'gift_lead', package=package or 'WiFi', phone=local_phone(friend)))}</p>
      </div>
      <div class="codebox"><div><small>{t(lang, 'gift_code')}</small><b id="vcode">{e(code)}</b></div>
        <button type="button" class="copy" onclick="copyCode(this)">{icon("copy", 15)} <span>{t(lang, "copy")}</span></button></div>
      <p class="hint" style="margin-top:6px">{t(lang, 'gift_share')}</p>
      <div style="margin-top:18px"><a class="btn" href="{e(base or '/')}">{t(lang, 'gift_again')}</a></div>
      <script>
      function copyCode(b){{var c=document.getElementById('vcode').textContent,s=b.querySelector('span');
        function done(){{s.textContent='{t(lang, "copied")}';}}
        if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(c).then(done);return;}}
        var i=document.createElement('input');i.value=c;document.body.appendChild(i);i.select();try{{document.execCommand('copy');done();}}catch(x){{}}i.remove();}}
      </script>"""
    return page(th, lang, body, hero_extra=False, preview=preview, lang_url=lang_url)


def waiting_page(th, lang, *, ref, info, timed_out=False, base='', lang_url='/', next_url=None, preview=False):
    amount = money(info.get('currency', 'TZS'), info.get('amount'))
    phone = info.get('phone', '')
    if timed_out:
        body = f"""
      <div class="center">
        <div class="state-ic wait">{icon('clock', 34)}</div>
        <h2>{t(lang, 'still_waiting')}</h2>
        <p class="lead">{e(t(lang, 'still_lead', amount=amount, phone=phone))}</p>
      </div>
      <a class="btn" href="{e(_qs(base + '/buy/wait', ref=ref, again='1'))}">{t(lang, 'paid_check')}</a>
      <a class="btn ghost" href="{e(base or '/')}">{t(lang, 'start_over')}</a>"""
        return page(th, lang, body, hero_extra=False, lang_url=lang_url)
    body = f"""
      <div class="center">
        <div class="state-ic wait">{icon('phone', 34)}</div>
        <h2>{t(lang, 'check_phone')}</h2>
        <p class="lead">{e(t(lang, 'wait_lead', amount=amount, package=info.get('package') or 'internet'))}</p>
      </div>
      <ol class="steps">
        <li><b>1</b><span>{t(lang, 'wait_step1')}</span></li>
        <li><b>2</b><span>{e(t(lang, 'wait_step2', amount=amount))}</span></li>
        <li><b>3</b><span>{e(t(lang, 'wait_step3_gift', phone=local_phone(info['gift_phone']))) if info.get('gift_phone') else t(lang, 'wait_step3')}</span></li>
      </ol>
      <p class="hint">{e(t(lang, 'sent_to', phone=phone))} · {t(lang, 'auto_update')}</p>"""
    return page(th, lang, body, hero_extra=False, lang_url=lang_url, preview=preview,
                head=f'<meta http-equiv="refresh" content="3;url={e(next_url or _qs(base + "/buy/wait", ref=ref))}">')


def instructions_page(th, lang, *, preview=False, lang_url='/'):
    """No gateway in front (e.g. WPA2-Enterprise on the access point): how to connect."""
    ssid = f'<b>{e(th["ssid"])}</b>' if th['ssid'] else ''
    body = f"""
      <h2>{t(lang, 'how_title')}</h2>
      <p class="lead">{t(lang, 'how_lead')}</p>
      <ol class="steps">
        <li><b>1</b><span>{t(lang, 'how1', ssid=ssid)}</span></li>
        <li><b>2</b><span>{t(lang, 'how2')}</span></li>
        <li><b>3</b><span>{t(lang, 'how3')}</span></li>
        <li><b>4</b><span>{t(lang, 'how4')}</span></li>
      </ol>"""
    return page(th, lang, body, preview=preview, lang_url=lang_url)


# ---------------------------------------------------------------------------
# "My Wi-Fi" guest app (served by the SafeNet cloud at /app/<business>)
# ---------------------------------------------------------------------------
APP_T = {
    'en': {
        'title': 'My Wi-Fi', 'add_code': 'Add your voucher code', 'add_lead': 'Type the code you used to connect. Your phone keeps it, so next time the app opens straight away.',
        'add': 'Add', 'adding': 'Adding…', 'online': 'Online now', 'offline': 'Not connected', 'left': 'Time left',
        'not_started': 'Starts when you first connect', 'expired': 'Time is up', 'used': 'Data used', 'down': 'down', 'up': 'up',
        'package': 'Package', 'code': 'Code', 'buy_more': 'Buy more', 'buy_friend': 'Buy for a friend', 'history': 'My packages',
        'help': 'Help', 'call': 'Call', 'install': 'Add to home screen', 'install_ios': 'On iPhone: tap Share, then "Add to Home Screen".',
        'choose': 'Choose a package', 'network': 'Mobile-money network', 'your_phone': 'Your mobile money number', 'friend_phone': "Friend's phone number",
        'pay': 'Pay {price}', 'check_phone': 'Check your phone and enter your PIN to pay {amount}.', 'waiting': 'Waiting for your payment…',
        'paid_me': 'Paid! Your new package {code} is ready: your phone connects with it by itself when the current time ends.',
        'paid_friend': 'Paid! We sent code {code} to {phone} by SMS.', 'failed': 'Payment not completed: {reason}',
        'no_buy': 'Buying in the app is not available here. Ask at the counter.', 'another': 'Add another code', 'refresh': 'Refresh',
        'updated': 'Updated {time}', 'offline_note': 'No internet: showing the last figures.', 'devices': 'devices', 'cancel': 'Cancel',
        'active': 'Active', 'unused': 'Not started', 'expired_s': 'Finished', 'disabled': 'Disabled', 'none': 'No packages yet.',
    },
    'sw': {
        'title': 'Wi-Fi Yangu', 'add_code': 'Weka namba ya vocha yako', 'add_lead': 'Andika namba uliyotumia kuunganishwa. Simu yako inaihifadhi, hivyo app itafunguka moja kwa moja wakati ujao.',
        'add': 'Weka', 'adding': 'Inaweka…', 'online': 'Uko mtandaoni', 'offline': 'Hujaunganishwa', 'left': 'Muda uliobaki',
        'not_started': 'Inaanza ukiunganishwa mara ya kwanza', 'expired': 'Muda umeisha', 'used': 'Data uliyotumia', 'down': 'kupakua', 'up': 'kupakia',
        'package': 'Kifurushi', 'code': 'Namba', 'buy_more': 'Nunua zaidi', 'buy_friend': 'Nunulia rafiki', 'history': 'Vifurushi vyangu',
        'help': 'Msaada', 'call': 'Piga', 'install': 'Weka kwenye skrini ya simu', 'install_ios': 'Kwenye iPhone: bonyeza Share, kisha "Add to Home Screen".',
        'choose': 'Chagua kifurushi', 'network': 'Mtandao wa malipo', 'your_phone': 'Namba yako ya malipo', 'friend_phone': 'Namba ya simu ya rafiki',
        'pay': 'Lipa {price}', 'check_phone': 'Angalia simu yako na weka PIN kulipia {amount}.', 'waiting': 'Tunasubiri malipo yako…',
        'paid_me': 'Umelipa! Kifurushi kipya {code} kiko tayari: simu yako itaunganishwa nacho yenyewe muda wa sasa ukiisha.',
        'paid_friend': 'Umelipa! Tumetuma namba {code} kwa {phone} kwa SMS.', 'failed': 'Malipo hayajakamilika: {reason}',
        'no_buy': 'Kununua kwenye app hakupatikani hapa. Uliza kaunta.', 'another': 'Weka namba nyingine', 'refresh': 'Sasisha',
        'updated': 'Imesasishwa {time}', 'offline_note': 'Hakuna intaneti: tunaonyesha takwimu za mwisho.', 'devices': 'vifaa', 'cancel': 'Ghairi',
        'active': 'Inatumika', 'unused': 'Haijaanza', 'expired_s': 'Imeisha', 'disabled': 'Imezimwa', 'none': 'Bado hakuna vifurushi.',
    },
}

APP_CSS = """
#app .big{font-size:40px;font-weight:800;letter-spacing:-1px;margin:4px 0}
#app .row{display:flex;justify-content:space-between;gap:10px;padding:9px 0;border-bottom:1px solid var(--line);font-size:14px}
#app .row:last-child{border-bottom:0}#app .row span{color:var(--ink-2)}
#app .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:#94a3b8}#app .dot.on{background:#16a34a}
#app .acts{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}#app .acts .btn{margin:0;font-size:14px;padding:12px 8px}
#app .sec{margin-top:18px}#app .muted{color:var(--ink-2);font-size:13px}#app .hidden{display:none}
#app a{color:var(--brand);font-weight:600;text-decoration:none}
#app .pill{font-size:11px;padding:2px 8px;border-radius:99px;background:var(--tint);color:var(--brand-dark,var(--brand))}
"""

APP_JS = r"""
(function(){
var T=window.APP_T, base=window.APP_BASE, KEY='snapp:'+base, box=document.getElementById('app');
function tt(k,v){var s=T[k]||k;if(v)for(var n in v)s=s.split('{'+n+'}').join(v[n]);return s;}
function el(tag,cls,text){var x=document.createElement(tag);if(cls)x.className=cls;if(text!=null)x.textContent=text;return x;}
function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}}
function save(s){try{localStorage.setItem(KEY,JSON.stringify(s))}catch(e){}}
var st=load(); st.tokens=st.tokens||[];
function api(path,body){return fetch(base+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},
  body:body===undefined?undefined:JSON.stringify(body)}).then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||r.status);return j;});});}
function money(c,a){return c+' '+Number(a).toLocaleString('en-US');}
function dur(s){s=Math.max(0,s|0);var d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
  return d?d+'d '+h+'h':h?h+'h '+m+'m':m+'m';}
function bytes(n){return n>=1e9?(n/1e9).toFixed(2)+' GB':n>=1e6?(n/1e6).toFixed(0)+' MB':Math.round(n/1e3)+' KB';}
// a code in the link (#code=...) from the connected screen
var m=location.hash.match(/code=([0-9A-Za-z]+)/);
if(m){history.replaceState(null,'',location.pathname+location.search);link(m[1]);}
else if(st.tokens.length){refresh();}else{showAdd();}
function link(code,err){box.replaceChildren(el('p','muted',tt('adding')));
  api('/api/link',{code:code}).then(function(j){if(st.tokens.indexOf(j.token)<0)st.tokens.push(j.token);save(st);refresh();})
  .catch(function(e){showAdd(e.message);});}
function showAdd(err){var f=el('form');f.append(el('h2',null,tt('add_code')),el('p','lead',tt('add_lead')));
  if(err){var a=el('div','alert');a.textContent=err;f.append(a);}
  var i=el('input','input code');i.inputMode='numeric';i.placeholder='12345678';i.required=true;i.autocomplete='one-time-code';
  var b=el('button','btn',tt('add'));b.type='submit';f.append(i,b);
  if(st.tokens.length){var c=el('button','btn ghost',tt('cancel'));c.type='button';c.onclick=refresh;f.append(c);}
  f.onsubmit=function(ev){ev.preventDefault();link(i.value.replace(/\s+/g,''));};box.replaceChildren(f);i.focus();}
function refresh(){api('/api/me',{tokens:st.tokens}).then(function(d){st.tokens=d.tokens.length?d.tokens:st.tokens;st.last=d;st.at=Date.now();save(st);show(d);})
  .catch(function(){if(st.last)show(st.last,true);else showAdd();});}
function show(d,stale){var v=d.vouchers[0];box.replaceChildren();
  if(stale)box.append(el('div','alert',tt('offline_note')));
  if(!v){showAdd();return;}
  var top=el('div','center');var on=el('p','lead');var dot=el('span','dot'+(v.online?' on':''));on.append(dot,v.online?tt('online'):tt('offline'));
  var left=v.state==='active'?dur(v.seconds_left):v.state==='unused'?'—':'0m';
  top.append(on,el('div','big',left),el('p','muted',v.state==='unused'?tt('not_started'):v.state==='active'?tt('left'):tt('expired')));box.append(top);
  var rows=el('div','sec');
  function row(a,b){var r=el('div','row');r.append(el('span',null,a),el('b',null,b));rows.append(r);}
  row(tt('used'),bytes(v.down+v.up)+' ('+bytes(v.down)+' '+tt('down')+' · '+bytes(v.up)+' '+tt('up')+')');
  if(v.package)row(tt('package'),v.package);row(tt('code'),v.code);box.append(rows);
  var acts=el('div','acts');
  function act(label,fn,ghost){var b=el('button','btn'+(ghost?' ghost':''),label);b.type='button';b.onclick=fn;acts.append(b);}
  if(d.can_buy)act(tt('buy_more'),function(){buy(d,false);});
  if(d.can_buy&&d.can_gift)act(tt('buy_friend'),function(){buy(d,true);},true);
  act(tt('history'),function(){hist(d);},true);act(tt('refresh'),refresh,true);box.append(acts);
  if(!d.can_buy)box.append(el('p','muted sec',tt('no_buy')));
  var more=el('div','sec');var add=el('a',null,tt('another'));add.href='#';add.onclick=function(e){e.preventDefault();showAdd();};more.append(add);
  if(d.support){more.append(document.createTextNode(' · '));var c=el('a',null,tt('call')+' '+d.support);c.href='tel:'+d.support.replace(/\s+/g,'');more.append(c);}
  box.append(more);installHint();}
function hist(d){box.replaceChildren(el('h2',null,tt('history')));
  if(!d.vouchers.length)box.append(el('p','muted',tt('none')));
  d.vouchers.forEach(function(v){var r=el('div','row');var a=el('span');a.append(el('b',null,v.package||v.code),el('br'),
    document.createTextNode(v.code+(v.bought?' · '+v.bought.slice(0,10):'')));
    r.append(a,el('span','pill',tt({active:'active',unused:'unused',expired:'expired_s',disabled:'disabled'}[v.state]||v.state)));box.append(r);});
  var b=el('button','btn ghost sec',tt('cancel'));b.type='button';b.onclick=function(){show(d);};box.append(b);}
function buy(d,gift){var f=el('form');f.append(el('h2',null,gift?tt('buy_friend'):tt('buy_more')),el('p','lead',tt('choose')));
  var err=el('div','alert hidden');f.append(err);var pk=el('div','pkgs');
  d.packages.forEach(function(p,i){var l=el('label','pkg'+(i?'':' on'));var r=el('input');r.type='radio';r.name='package_id';r.value=p.id;r.checked=!i;
    r.onchange=function(){pk.querySelectorAll('.pkg').forEach(function(x){x.classList.toggle('on',x.contains(r));});pay.textContent=tt('pay',{price:money(p.currency,p.price)});};
    var nm=el('span','nm');nm.append(el('b',null,p.name),el('small',null,dur(p.validity_minutes*60)));
    l.append(r,nm,el('span','pr',money(p.currency,p.price)));pk.append(l);});f.append(pk);
  var net=null;if(d.networks.length){net=el('select','input');d.networks.forEach(function(n){var o=el('option',null,n.name);o.value=n.id;net.append(o);});
    var nf=el('div','field');nf.append(el('label',null,tt('network')),net);f.append(nf);}
  var ph=el('input','input');ph.type='tel';ph.inputMode='tel';ph.placeholder='07XX XXX XXX';ph.required=true;
  var pf=el('div','field');pf.append(el('label',null,tt('your_phone')),ph);f.append(pf);
  var gp=null;if(gift){gp=el('input','input');gp.type='tel';gp.inputMode='tel';gp.placeholder='07XX XXX XXX';gp.required=true;
    var gf=el('div','field');gf.append(el('label',null,tt('friend_phone')),gp);f.append(gf);}
  var p0=d.packages[0];var pay=el('button','btn',p0?tt('pay',{price:money(p0.currency,p0.price)}):'');pay.type='submit';
  var cancel=el('button','btn ghost',tt('cancel'));cancel.type='button';cancel.onclick=function(){show(d);};f.append(pay,cancel);
  f.onsubmit=function(ev){ev.preventDefault();pay.disabled=true;err.classList.add('hidden');
    var sel=f.querySelector('input[name=package_id]:checked');
    api('/api/buy',{tokens:st.tokens,package_id:sel&&sel.value,phone:ph.value,network:net&&net.value,gift:!!gift,gift_phone:gp&&gp.value})
    .then(function(j){wait(j);}).catch(function(e){err.textContent=e.message;err.classList.remove('hidden');pay.disabled=false;});};
  box.replaceChildren(f);}
function wait(j){box.replaceChildren(el('h2',null,tt('waiting')),el('p','lead',tt('check_phone',{amount:money(j.currency,j.amount)})));
  var n=0,timer=setInterval(function(){n++;api('/api/pay/'+j.reference).then(function(p){
    if(p.status==='paid'){clearInterval(timer);if(p.token&&st.tokens.indexOf(p.token)<0){st.tokens.push(p.token);save(st);}
      var a=el('div','alert ok');a.textContent=p.gift_phone?tt('paid_friend',{code:p.code,phone:p.gift_phone}):tt('paid_me',{code:p.code});
      box.replaceChildren(a);setTimeout(refresh,4000);}
    else if(p.status==='failed'||p.status==='review'){clearInterval(timer);var a2=el('div','alert');a2.textContent=tt('failed',{reason:p.message||''});
      box.replaceChildren(a2);var b=el('button','btn ghost',tt('cancel'));b.onclick=refresh;box.append(b);}
    }).catch(function(){});if(n>60)clearInterval(timer);},3000);}
var promptEvt=null;window.addEventListener('beforeinstallprompt',function(e){e.preventDefault();promptEvt=e;installHint();});
function installHint(){var old=document.getElementById('install');if(old)old.remove();
  if(window.matchMedia('(display-mode: standalone)').matches||navigator.standalone)return;
  var s=el('div','sec');s.id='install';
  if(promptEvt){var b=el('button','btn ghost',tt('install'));b.type='button';b.onclick=function(){promptEvt.prompt();};s.append(b);}
  else if(/iphone|ipad/i.test(navigator.userAgent))s.append(el('p','muted',tt('install_ios')));
  if(s.childNodes.length)box.append(s);}
if('serviceWorker' in navigator)navigator.serviceWorker.register(window.APP_WORKER,{scope:'/app/'}).catch(function(){});
setInterval(function(){if(document.visibilityState==='visible'&&st.tokens.length&&!box.querySelector('form'))refresh();},30000);
})();
"""

APP_WORKER_JS = """
// SafeNet guest app: keep the app's page so it opens without internet; the app keeps its last figures itself.
var CACHE='snapp-v1';
self.addEventListener('install',function(e){self.skipWaiting();});
self.addEventListener('activate',function(e){e.waitUntil(self.clients.claim());});
self.addEventListener('fetch',function(e){
  var r=e.request;if(r.method!=='GET'||r.url.indexOf('/api/')>=0)return;
  e.respondWith(fetch(r).then(function(res){var copy=res.clone();caches.open(CACHE).then(function(c){c.put(r,copy);});return res;})
    .catch(function(){return caches.match(r);}));
});
"""


def app_page(th, lang, *, base, manifest, worker, logo_base='/img/'):
    """The guest app's page: everything else is drawn by APP_JS from the cloud's JSON."""
    import json
    strings = APP_T.get(lang, APP_T['en'])
    head = (f'<link rel="manifest" href="{e(manifest)}"><meta name="theme-color" content="{e(th["color"])}">'
            f'<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">'
            f'<meta name="apple-mobile-web-app-title" content="{e(th["name"])}">'
            f'<link rel="apple-touch-icon" href="{e(logo_base)}app-192.png"><style>{APP_CSS}</style>')
    body = (f'<div id="app"><p class="muted">…</p></div>'
            f'<script>window.APP_T={json.dumps(strings)};window.APP_BASE={json.dumps(base)};window.APP_WORKER={json.dumps(worker)};</script>'
            f'<script>{APP_JS}</script>')
    return page(th, lang, body, head=head, hero_extra=False, lang_url=base)
