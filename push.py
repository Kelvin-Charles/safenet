"""Push notifications to the SafeNet app with Firebase Cloud Messaging (HTTP v1), for Android and iPhone.

Set up once on Platform: Notifications by uploading three files from the Firebase console:
  * the service account key (Project settings > Service accounts > Generate new private key): lets SafeNet send;
  * google-services.json (the Android app) and GoogleService-Info.plist (the iOS app): what the app needs to sign up
    for notifications. The app fetches these settings from /api/m/push/config, so no new app build is needed.
They are kept in the app files folder (a Docker volume, kept across deploys), readable only by SafeNet.
"""
import base64
import json
import logging
import os
import plistlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

log = logging.getLogger(__name__)

SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
ANDROID_PACKAGE = 'com.safezonetz.safenet_app'
IOS_BUNDLE = 'com.safezonetz.safenetApp'
FILES = {'service': 'firebase-service-account.json', 'android': 'firebase-google-services.json', 'ios': 'firebase-GoogleService-Info.plist'}

folder = None                 # set by the app (APP_FILES_DIR)
_token = {'value': None, 'exp': 0}
_lock = threading.Lock()


class PushError(Exception):
    pass


def _path(which):
    return os.path.join(folder or '.', FILES[which])


def _read(which):
    try:
        with open(_path(which), 'rb') as fh:
            return fh.read()
    except OSError:
        return None


# ---------------------------------------------------------------- the uploaded files
def parse_service(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('type') != 'service_account' or not all(data.get(k) for k in ('private_key', 'client_email', 'project_id')):
        raise PushError('This is not a Firebase service account key (Project settings > Service accounts > Generate new private key).')
    serialization.load_pem_private_key(data['private_key'].encode(), password=None)
    return data


def parse_android(raw):
    data = json.loads(raw)
    project = data.get('project_info') or {}
    for client in data.get('client') or []:
        info = (client.get('client_info') or {})
        if (info.get('android_client_info') or {}).get('package_name') == ANDROID_PACKAGE:
            key = next((k.get('current_key') for k in client.get('api_key') or [] if k.get('current_key')), None)
            if key and info.get('mobilesdk_app_id'):
                return {'api_key': key, 'app_id': info['mobilesdk_app_id'], 'sender_id': str(project.get('project_number') or ''),
                        'project_id': project.get('project_id') or ''}
    raise PushError(f'google-services.json has no Android app {ANDROID_PACKAGE}. Add an Android app with that package name in Firebase.')


def parse_ios(raw):
    data = plistlib.loads(raw)
    if not data.get('API_KEY') or not data.get('GOOGLE_APP_ID'):
        raise PushError('This is not a GoogleService-Info.plist file.')
    if data.get('BUNDLE_ID') != IOS_BUNDLE:
        raise PushError(f'GoogleService-Info.plist is for {data.get("BUNDLE_ID")}; the SafeNet iOS app is {IOS_BUNDLE}.')
    return {'api_key': data['API_KEY'], 'app_id': data['GOOGLE_APP_ID'], 'sender_id': str(data.get('GCM_SENDER_ID') or ''),
            'project_id': data.get('PROJECT_ID') or ''}


PARSERS = {'service': parse_service, 'android': parse_android, 'ios': parse_ios}


def save(which, raw):
    """Check an uploaded file and keep it (mode 600). Raises PushError if it isn't the right file."""
    try:
        parsed = PARSERS[which](raw)
    except PushError:
        raise
    except Exception:
        raise PushError('That file could not be read. Download it again from the Firebase console.') from None
    os.makedirs(folder, exist_ok=True)
    tmp = _path(which) + '.part'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(raw)
    os.replace(tmp, _path(which))
    if which == 'service':
        _token.update(value=None, exp=0)
    return parsed


def remove(which):
    try:
        os.remove(_path(which))
    except OSError:
        pass
    _token.update(value=None, exp=0)


def _load(which):
    raw = _read(which)
    if not raw:
        return None
    try:
        return PARSERS[which](raw)
    except Exception:
        log.warning('firebase %s file is not valid', which)
        return None


def status():
    """What is set up: {'service': project id or None, 'android': app id or None, 'ios': app id or None}."""
    service, android, ios = _load('service'), _load('android'), _load('ios')
    return {'service': service['project_id'] if service else None, 'service_email': service['client_email'] if service else None,
            'android': android['app_id'] if android else None, 'ios': ios['app_id'] if ios else None,
            'android_project': android['project_id'] if android else None, 'ios_project': ios['project_id'] if ios else None}


def can_send():
    return _read('service') is not None


def app_config():
    """What the app needs to start Firebase (public values from the app config files), or {'enabled': False}."""
    service, android, ios = _load('service'), _load('android'), _load('ios')
    if not service or not (android or ios):
        return {'enabled': False}
    return {'enabled': True, 'project_id': service['project_id'], 'android': android, 'ios': ios}


# ---------------------------------------------------------------- sending
def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _access_token(service):
    with _lock:
        if _token['value'] and _token['exp'] > time.time() + 60:
            return _token['value']
        now = int(time.time())
        uri = service.get('token_uri') or 'https://oauth2.googleapis.com/token'
        head = _b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
        claims = _b64(json.dumps({'iss': service['client_email'], 'scope': SCOPE, 'aud': uri, 'iat': now, 'exp': now + 3600}).encode())
        key = serialization.load_pem_private_key(service['private_key'].encode(), password=None)
        signature = _b64(key.sign(f'{head}.{claims}'.encode(), padding.PKCS1v15(), hashes.SHA256()))
        body = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                       'assertion': f'{head}.{claims}.{signature}'}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(uri, data=body), timeout=15) as resp:
                reply = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise PushError(f'Google refused the service account key ({e.code}): {e.read().decode("utf-8", "replace")[:200]}') from None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise PushError(f'Google unreachable: {e}') from None
        _token.update(value=reply['access_token'], exp=now + int(reply.get('expires_in', 3600)))
        return _token['value']


def send(token, title, body, data=None):
    """Send one notification. Returns 'ok', 'gone' (the app was removed or signed out: forget the token) or 'error'."""
    service = _load('service')
    if not service:
        return 'error'
    message = {
        'token': token,
        'notification': {'title': title[:140], 'body': body[:500]},
        'data': {k: str(v) for k, v in (data or {}).items() if v is not None},
        'android': {'priority': 'high', 'notification': {'channel_id': 'alerts', 'sound': 'default', 'icon': 'ic_stat_safenet',
                                                         'color': '#051D60'}},
        'apns': {'headers': {'apns-priority': '10'}, 'payload': {'aps': {'sound': 'default'}}},
    }
    req = urllib.request.Request(f'https://fcm.googleapis.com/v1/projects/{service["project_id"]}/messages:send',
                                 data=json.dumps({'message': message}).encode(), method='POST',
                                 headers={'Authorization': f'Bearer {_access_token(service)}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15):
            return 'ok'
    except urllib.error.HTTPError as e:
        text = e.read().decode('utf-8', 'replace')[:300]
        if e.code == 404 or 'UNREGISTERED' in text or (e.code == 400 and 'registration token' in text.lower()):
            return 'gone'
        if e.code == 401:
            _token.update(value=None, exp=0)
        log.warning('push failed (%s): %s', e.code, text)
        return 'error'
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning('push failed: %s', e)
        return 'error'
