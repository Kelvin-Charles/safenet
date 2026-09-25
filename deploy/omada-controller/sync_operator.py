"""Create/refresh the SafeNet hotspot operator and give it every site on this controller.

SafeNet logs in as this operator to let paying guests online (Omada External Portal API).
Run again after adding sites in the controller:  python3 sync_operator.py
"""
import http.cookiejar
import json
import os
import re
import secrets
import ssl
import string
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = 'https://127.0.0.1:8043'
NAME = 'safenet-portal'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                     urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
token = None


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/json')
    if token:
        req.add_header('Csrf-Token', token)
    reply = json.loads(opener.open(req, timeout=30).read())
    if reply.get('errorCode') != 0:
        sys.exit(f"{method} {path}: {reply.get('errorCode')} {reply.get('msg')}")
    return reply.get('result')


def strong_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = ''.join(secrets.choice(alphabet) for _ in range(18)) + '#' + secrets.choice('23456789') + 'Aa'
        if not any(pw[i] == pw[i + 1] for i in range(len(pw) - 1)):
            return pw


creds_file = os.path.join(HERE, 'ADMIN_CREDENTIALS')
creds = open(creds_file).read()
admin_user = re.search(r'username: (\S+)', creds).group(1)
admin_pw = re.search(r'password: (\S+)', creds).group(1)

cid = call('GET', '/api/info')['omadacId']
token = call('POST', f'/{cid}/api/v2/login', {'username': admin_user, 'password': admin_pw})['token']
sites = [s['key'] for s in call('GET', f'/{cid}/api/v2/users/current')['privilege']['sites']]
hs = sites[0]                      # operators are managed through any site the admin can see
listing = call('GET', f'/{cid}/api/v2/hotspot/sites/{hs}/operators?currentPage=1&currentPageSize=100') or {}
existing = [o for o in listing.get('data', []) if o.get('name') == NAME]

if existing:
    saved = creds.split('Hotspot operator used by SafeNet')[1]
    op_pw = re.search(r'password: (\S+)', saved).group(1)
    call('PATCH', f"/{cid}/api/v2/hotspot/sites/{hs}/operators/{existing[0]['id']}",
         {'name': NAME, 'password': op_pw, 'selectedSites': sites, 'operatorRoleType': 0})
    print(f'operator {NAME}: now has {len(sites)} site(s)')
else:
    pw = strong_password()
    call('POST', f'/{cid}/api/v2/hotspot/sites/{hs}/operators',
         {'name': NAME, 'password': pw, 'note': 'Used by SafeNet to let paying guests online',
          'selectedSites': sites, 'operatorRoleType': 0})
    old = os.umask(0o077)
    with open(creds_file, 'a') as f:
        f.write(f'\nHotspot operator used by SafeNet\nusername: {NAME}\npassword: {pw}\n')
    os.umask(old)
    print(f'operator {NAME}: created with {len(sites)} site(s)')
