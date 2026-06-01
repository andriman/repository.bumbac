import base64
import json
import os
from datetime import datetime, timezone
from typing import Optional, Tuple

import requests
import xbmcvfs

from common import addon

_session: Optional[requests.Session] = None

AUTH_COOKIE_NAMES = frozenset({'access_token', 'refresh_token', 'alreadyLoggedIn'})


def _session_file_path() -> str:
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.exists(profile):
        os.makedirs(profile)
    return os.path.join(profile, 'session.json')


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _load_session(_session)
    return _session


def save_session() -> None:
    session = get_session()
    cookies = []
    for cookie in session.cookies:
        entry = {
            'name': cookie.name,
            'value': cookie.value,
            'domain': cookie.domain,
            'path': cookie.path,
        }
        if cookie.expires is not None:
            entry['expires'] = cookie.expires
        cookies.append(entry)
    path = _session_file_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cookies, f)


def clear_session() -> None:
    global _session
    if _session is not None:
        _session.cookies.clear()
    path = _session_file_path()
    if os.path.exists(path):
        os.remove(path)
    _session = requests.Session()


def _load_session(session: requests.Session) -> None:
    path = _session_file_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding='utf-8') as f:
            cookies = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    for cookie in cookies:
        kwargs = {
            'domain': cookie.get('domain'),
            'path': cookie.get('path', '/'),
        }
        if cookie.get('expires') is not None:
            kwargs['expires'] = cookie['expires']
        session.cookies.set(cookie['name'], cookie['value'], **kwargs)


def has_auth_cookies(session: requests.Session) -> bool:
    names = {c.name for c in session.cookies}
    return bool(names & AUTH_COOKIE_NAMES)


def _jwt_expiry(token: str) -> Optional[int]:
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get('exp')
        return int(exp) if exp is not None else None
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        return None


def get_session_expiration() -> Tuple[str, str]:
    """Return (date/time string, countdown label) for auth session expiry."""
    session = get_session()
    exp_ts: Optional[int] = None

    for cookie in session.cookies:
        if cookie.name not in AUTH_COOKIE_NAMES:
            continue
        candidate = cookie.expires
        if cookie.name == 'access_token' and not candidate:
            candidate = _jwt_expiry(cookie.value)
        if candidate:
            exp_ts = candidate if exp_ts is None else min(exp_ts, candidate)

    if exp_ts is None:
        return '', ''

    exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    days = (exp_dt.date() - now.date()).days
    date_str = exp_dt.astimezone().strftime('%Y-%m-%d %H:%M')
    if days < 0:
        countdown = 'expired'
    elif days == 0:
        countdown = '0 days'
    elif days == 1:
        countdown = '1 day'
    else:
        countdown = f'{days} days'
    return date_str, countdown
