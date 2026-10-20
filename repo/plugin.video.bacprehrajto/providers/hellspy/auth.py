"""HellSpy bearer-token login. The page header is drawn by JavaScript and is not a login signal."""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import xbmcgui
import xbmcvfs

from common import (
    _ADDON_NAME,
    addon,
    get_headers,
    get_hellspy_api_base,
    get_hellspy_base,
    is_hellspy_auto_login_enabled,
    set_hellspy_auto_login_enabled,
)
from providers.hellspy.session import get_session, save_session
from utils.utils import dprint

_REFRESH_BEFORE = timedelta(hours=6)
_TIMEOUT = 30
_token: Optional[dict] = None


def _token_path() -> str:
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.exists(profile):
        os.makedirs(profile)
    return os.path.join(profile, 'hellspy_token.json')


def _site_headers(extra: Optional[dict] = None) -> dict:
    base = get_hellspy_base().rstrip('/')
    headers = get_headers({
        'Accept': 'application/json',
        'Origin': base,
        'Referer': base + '/',
    })
    if extra:
        headers.update(extra)
    return headers


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_current(token: Optional[dict]) -> bool:
    if not token or not token.get('accessToken'):
        return False
    if token.get('valid') is False or token.get('active') is False:
        return False
    expires = _parse_time(token.get('expires'))
    if expires is None:
        return True
    return expires > datetime.now(timezone.utc)


def _needs_refresh(token: dict) -> bool:
    expires = _parse_time(token.get('expires'))
    if expires is None:
        return False
    return expires - _REFRESH_BEFORE <= datetime.now(timezone.utc)


def _load_token() -> Optional[dict]:
    global _token
    if _token is not None:
        return _token
    path = _token_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get('accessToken'):
        return None
    _token = data
    return _token


def _save_token(token: dict) -> None:
    global _token
    kept = {
        'accessToken': token.get('accessToken'),
        'expires': token.get('expires'),
        'user': token.get('user'),
        'active': token.get('active'),
        'valid': token.get('valid'),
        'id': token.get('id'),
    }
    _token = kept
    path = _token_path()
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(kept, handle)


def clear_token() -> None:
    global _token
    _token = None
    path = _token_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        dprint(f'hellspy clear_token(): {exc}')


def has_saved_session() -> bool:
    token = _load_token()
    return bool(token and _is_current(token))


def uses_account_session() -> bool:
    """True when search should be cached separately because requests will carry the token."""
    token = _load_token()
    if token and _is_current(token):
        return True
    if not is_hellspy_auto_login_enabled():
        return False
    email = (addon.getSetting('hellspy_email') or '').strip()
    password = addon.getSetting('hellspy_password') or ''
    return bool(email and password)


def _bearer(token: dict) -> dict:
    return {'Authorization': 'Bearer ' + str(token.get('accessToken') or '')}


def _refresh(token: dict) -> Optional[dict]:
    try:
        response = get_session().post(
            get_hellspy_api_base() + '/refresh_token',
            headers=_site_headers(_bearer(token)),
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        dprint(f'hellspy refresh_token(): {exc}')
        return token if _is_current(token) else None
    if not response.ok:
        dprint(f'hellspy refresh_token(): HTTP {response.status_code}')
        clear_token()
        return None
    try:
        refreshed = response.json()
    except ValueError:
        clear_token()
        return None
    if not isinstance(refreshed, dict) or not refreshed.get('accessToken'):
        clear_token()
        return None
    _save_token(refreshed)
    save_session()
    return refreshed


def ensure_access_token() -> Optional[str]:
    """Return a usable access token, refreshing or auto-logging in when needed."""
    token = _load_token()
    if token and _needs_refresh(token):
        token = _refresh(token)
    if token and _is_current(token):
        return str(token['accessToken'])
    if not is_hellspy_auto_login_enabled():
        return None
    if hellspy_login(addon, notify=False):
        token = _load_token()
        if token and token.get('accessToken'):
            return str(token['accessToken'])
    return None


def request_headers(extra: Optional[dict] = None) -> dict:
    """Plugin headers plus the bearer token when an account session is available."""
    headers = get_headers(extra)
    try:
        access_token = ensure_access_token()
    except Exception as exc:
        dprint(f'hellspy request_headers(): {exc}')
        access_token = None
    if access_token:
        headers['Authorization'] = 'Bearer ' + access_token
    return headers


def hellspy_login(addon_ref=None, notify: bool = True) -> bool:
    ref = addon_ref or addon
    email = (ref.getSetting('hellspy_email') or '').strip()
    password = ref.getSetting('hellspy_password') or ''
    if not email or not password:
        if notify:
            xbmcgui.Dialog().ok(
                _ADDON_NAME,
                'Vyplňte přihlašovací údaje v nastavení doplňku (Accounts).',
            )
        return False

    try:
        response = get_session().post(
            get_hellspy_api_base() + '/login',
            json={'email': email, 'password': password},
            headers=_site_headers(),
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        dprint(f'hellspy login(): {exc}')
        if notify:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Přihlášení se nezdařilo',
                xbmcgui.NOTIFICATION_ERROR, 4000, sound=False,
            )
        return False

    if not response.ok:
        dprint(f'hellspy login(): HTTP {response.status_code}')
        if notify:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Email nebo heslo je špatně.',
                xbmcgui.NOTIFICATION_ERROR, 4000, sound=False,
            )
        return False

    try:
        token = response.json()
    except ValueError:
        token = None
    if not isinstance(token, dict) or not token.get('accessToken') or not _is_current(token):
        if notify:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Přihlášení se nezdařilo',
                xbmcgui.NOTIFICATION_ERROR, 4000, sound=False,
            )
        return False

    _save_token(token)
    save_session()
    if notify:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Přihlášeno na HellSpy',
            xbmcgui.NOTIFICATION_INFO, 4000, sound=False,
        )
    return True


def hellspy_logout() -> bool:
    clear_token()
    set_hellspy_auto_login_enabled(False)
    return True


def fetch_identity() -> Optional[dict]:
    """GET /identify. Returns the Identity object, or None when logged out."""
    access_token = ensure_access_token()
    if not access_token:
        return None
    token = _load_token() or {'accessToken': access_token}
    try:
        response = get_session().get(
            get_hellspy_api_base() + '/identify',
            headers=_site_headers(_bearer(token)),
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        dprint(f'hellspy identify(): {exc}')
        return None
    if response.status_code in (401, 403):
        dprint(f'hellspy identify(): HTTP {response.status_code}')
        clear_token()
        return None
    if not response.ok:
        dprint(f'hellspy identify(): HTTP {response.status_code}')
        return None
    try:
        identity = response.json()
    except ValueError:
        return None
    if not isinstance(identity, dict):
        return None
    nested = identity.get('token')
    if isinstance(nested, dict) and nested.get('accessToken'):
        _save_token(nested)
        save_session()
    return identity


def account_nickname(identity: Optional[dict]) -> str:
    if not isinstance(identity, dict):
        return ''
    client = identity.get('client') if isinstance(identity.get('client'), dict) else {}
    user = identity.get('user') if isinstance(identity.get('user'), dict) else {}
    nickname = (client.get('nickname') or '').strip()
    if nickname:
        return nickname
    return (user.get('email') or '').strip()
