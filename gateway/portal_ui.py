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


def network_for_phone(phone):
    """Network id for a 255XXXXXXXXX / 0XXXXXXXXX number, or None if the prefix is unknown."""
    digits = re.sub(r'\D', '', phone or '')
    local = digits[3:] if digits.startswith('255') else digits.lstrip('0')
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
        'help': 'Need help?', 'call': 'Call {phone}', 'powered': 'Powered by SafeNet', 'close': 'Close',
        'perk_fast': 'Fast, reliable internet', 'perk_pay': 'Pay easily with mobile money', 'perk_safe': 'Your connection, your time',
        'how_title': 'How to connect', 'how_lead': 'Buy a voucher at the counter, then:',
        'how1': 'Join the Wi-Fi network {ssid}', 'how2': 'If asked for EAP method choose <code>PEAP</code>, phase 2 <code>MSCHAPV2</code>',
        'how3': 'CA certificate: <code>Don\'t validate</code> (Android) or tap <b>Trust</b> (iPhone)',
        'how4': 'Username and password: your voucher code. Leave <i>anonymous identity</i> empty.',
        'preview': 'Preview', 'left': 'left', 'total': 'total',
        'busy_pay': 'Sending payment request…', 'busy_connect': 'Connecting…', 'busy_pay_hint': 'Please wait, this takes a few seconds.',
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
        'help': 'Unahitaji msaada?', 'call': 'Piga {phone}', 'powered': 'Inaendeshwa na SafeNet', 'close': 'Funga',
        'perk_fast': 'Intaneti ya kasi na ya uhakika', 'perk_pay': 'Lipa kwa urahisi kwa simu', 'perk_safe': 'Muunganisho wako, muda wako',
        'how_title': 'Jinsi ya kuunganishwa', 'how_lead': 'Nunua vocha kaunta, kisha:',
        'how1': 'Unganisha kwenye mtandao wa Wi-Fi {ssid}', 'how2': 'Ukiulizwa EAP method chagua <code>PEAP</code>, phase 2 <code>MSCHAPV2</code>',
        'how3': 'CA certificate: <code>Don\'t validate</code> (Android) au bonyeza <b>Trust</b> (iPhone)',
        'how4': 'Jina la mtumiaji na nenosiri: namba ya vocha yako. Acha <i>anonymous identity</i> wazi.',
        'preview': 'Onyesho', 'left': 'imebaki', 'total': 'jumla',
        'busy_pay': 'Inatuma ombi la malipo…', 'busy_connect': 'Inaunganisha…', 'busy_pay_hint': 'Tafadhali subiri, inachukua sekunde chache.',
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
    'The payment was not completed.': 'Malipo hayakukamilika.',
}


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
  if(ph)ph.addEventListener('input',function(){{var d=ph.value.replace(/\\D/g,'');if(d.indexOf('255')===0)d=d.slice(3);d=d.replace(/^0/,'');
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
    return (f'<label class="check" for="{field_id}"><input type="checkbox" id="{field_id}" name="agree" value="1" required>'
            f'<span>{t(lang, "accept")} {link}</span></label>')


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def login_page(th, lang, *, packages=(), dst='', error='', tab=None, action='/login', buy_action='/buy',
               external=None, buy_enabled=True, preview=False, lang_url='/', networks=(), logo_base='/img/'):
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
    submit_type = 'button' if preview else 'submit'

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
                    f'<img src="{e(logo_base + info["logo"])}" alt="{e(info["name"])}" loading="lazy">'
                    f'<span>{e(info["name"])}</span>{note}<span class="tick">{icon("check", 13, 3)}</span></label>')
            net_tiles = (f'<div class="field"><label>{t(lang, "network")}</label>'
                         f'<div class="nets" style="--n:{min(len(tiles), 4)}">{"".join(tiles)}</div></div>')
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
          <div class="phone"><span>+255</span><input class="input" type="tel" id="phone" name="phone" inputmode="tel" autocomplete="tel"
            placeholder="7XX XXX XXX" required></div>
        </div>
        {_terms_check(th, lang, 'agree-b')}
        <button class="btn" type="{submit_type}" id="paybtn">{e(t(lang, 'pay', price=first_price))}</button>
        <p class="hint">{t(lang, 'pay_hint')}</p>
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


def status_page(th, lang, *, user, remaining, total=None, dst='', new_code=None, preview=False):
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
      <form method="post" action="/logout"><button class="btn ghost" type="{'button' if preview else 'submit'}">{icon('logout', 18)} {t(lang, 'disconnect')}</button></form>
      <script>
      function copyCode(b){{var c=document.getElementById('vcode').textContent,s=b.querySelector('span');
        function done(){{s.textContent='{t(lang, "copied")}';}}
        if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(c).then(done);return;}}
        var i=document.createElement('input');i.value=c;document.body.appendChild(i);i.select();try{{document.execCommand('copy');done();}}catch(x){{}}i.remove();}}
      </script>"""
    return page(th, lang, body, hero_extra=False, preview=preview)


def waiting_page(th, lang, *, ref, info, timed_out=False):
    amount = money(info.get('currency', 'TZS'), info.get('amount'))
    phone = info.get('phone', '')
    if timed_out:
        body = f"""
      <div class="center">
        <div class="state-ic wait">{icon('clock', 34)}</div>
        <h2>{t(lang, 'still_waiting')}</h2>
        <p class="lead">{e(t(lang, 'still_lead', amount=amount, phone=phone))}</p>
      </div>
      <a class="btn" href="{e(_qs('/buy/wait', ref=ref, again='1'))}">{t(lang, 'paid_check')}</a>
      <a class="btn ghost" href="/">{t(lang, 'start_over')}</a>"""
        return page(th, lang, body, hero_extra=False)
    body = f"""
      <div class="center">
        <div class="state-ic wait">{icon('phone', 34)}</div>
        <h2>{t(lang, 'check_phone')}</h2>
        <p class="lead">{e(t(lang, 'wait_lead', amount=amount, package=info.get('package') or 'internet'))}</p>
      </div>
      <ol class="steps">
        <li><b>1</b><span>{t(lang, 'wait_step1')}</span></li>
        <li><b>2</b><span>{e(t(lang, 'wait_step2', amount=amount))}</span></li>
        <li><b>3</b><span>{t(lang, 'wait_step3')}</span></li>
      </ol>
      <p class="hint">{e(t(lang, 'sent_to', phone=phone))} · {t(lang, 'auto_update')}</p>"""
    return page(th, lang, body, hero_extra=False,
                head=f'<meta http-equiv="refresh" content="3;url={e(_qs("/buy/wait", ref=ref))}">')


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
