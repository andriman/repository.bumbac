import json
import os
from typing import Optional

import requests
import xbmcvfs

from common import addon

_session: Optional[requests.Session] = None


def _session_file_path() -> str:
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.exists(profile):
        os.makedirs(profile)
    return os.path.join(profile, 'sledujteto_session.json')


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
    for cookie in session.cookies:
        if cookie.name.lower() in ('session', 'sessionid', 'PHPSESSID', 'remember'):
            return True
    return len(session.cookies) > 0
