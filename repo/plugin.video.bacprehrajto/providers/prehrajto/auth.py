from typing import Optional, Tuple

import xbmcgui
from bs4 import BeautifulSoup
from requests.cookies import RequestsCookieJar

from common import (
    _ADDON_NAME,
    get_headers,
    get_prehrajto_base,
    get_user_agent,
    g_is_prehrajto_enabled,
    is_prehrajto_auto_login_enabled,
    set_prehrajto_auto_login_enabled,
)
from providers.browsing_context import (
    clear_prehrajto_browsing_context,
    get_prehrajto_logout_referer,
    remember_provider_page,
)
from providers.prehrajto.session import (
    clear_session,
    get_session,
    has_auth_cookies,
    has_usable_auth_locally,
    save_session,
)
from utils.utils import build_headers, dprint

_premium_cached: Optional[bool] = None


def invalidate_auth_cache() -> None:
    global _premium_cached
    _premium_cached = None


def _login_url() -> str:
    return get_prehrajto_base() + '/?frm=loginDialog-login-loginForm'


def parse_header_login_state(soup: BeautifulSoup) -> bool:
    header = soup.find('ul', class_='header__links')
    if header is None:
        return False
    return header.find('a', href='/profil') is not None


def parse_premium_status_from_header(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    """Return (is_active_premium, status_text) from site header bar."""
    header = soup.find('ul', class_='header__links')
    if header is None:
        return False, None

    green = header.find('span', class_='color-green')
    if green is not None:
        return True, green.get_text(strip=True)

    for li in header.find_all('li'):
        strong = li.find('strong')
        if strong is None or 'Premium' not in strong.get_text():
            continue
        inactive = li.find('span', class_='color-primary')
        if inactive is not None:
            return False, inactive.get_text(strip=True)

    return False, None


def parse_premium_from_header(soup: BeautifulSoup) -> Optional[str]:
    is_active, status_text = parse_premium_status_from_header(soup)
    if is_active:
        return status_text
    return None


def refresh_premium_from_html(content: bytes) -> Optional[bool]:
    """Update cached premium flag from any Prehraj page HTML. None when header absent."""
    try:
        soup = BeautifulSoup(content, 'html.parser')
        if soup.find('ul', class_='header__links') is None:
            return None
        return _cache_premium_from_soup(soup)
    except Exception:
        return None


def _login_form_fields(email: str, password: str) -> dict:
    return {
        'email': (None, email),
        'password': (None, password),
        'remember_login': (None, 'on'),
        '_do': (None, 'loginDialog-login-loginForm-submit'),
        'login': (None, 'Přihlásit se'),
    }


def _cache_premium_from_soup(soup: BeautifulSoup) -> bool:
    global _premium_cached
    is_active, _status_text = parse_premium_status_from_header(soup)
    _premium_cached = is_active
    return _premium_cached


def _fetch_home_soup():
    session = get_session()
    res = session.get(get_prehrajto_base() + '/', headers=get_headers())
    remember_provider_page(res.url)
    return BeautifulSoup(res.content, 'html.parser')


def prehrajto_login(addon, notify: bool = True) -> Tuple[bool, Optional[RequestsCookieJar]]:
    """
    Log in using addon credentials on the configured Prehraj domain.
    Returns (is_premium, cookies). Uses persisted session on success.
    """
    email = addon.getSetting('email')
    if not email:
        return False, None

    password = addon.getSetting('password')
    session = get_session()
    base = get_prehrajto_base()

    home = base + '/'
    session.get(home, headers=get_headers())
    remember_provider_page(home)
    res = session.post(
        _login_url(),
        files=_login_form_fields(email, password),
        headers={**get_headers(), 'Referer': home, 'X-Requested-With': 'XMLHttpRequest'},
    )

    soup = BeautifulSoup(res.content, 'html.parser')
    logged_in = parse_header_login_state(soup) or has_auth_cookies(session)

    if not logged_in:
        invalidate_auth_cache()
        if notify:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Přihlášení se nezdařilo',
                xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        return False, None

    save_session()

    res = session.get(home, headers=get_headers())
    remember_provider_page(res.url)
    soup = BeautifulSoup(res.content, 'html.parser')
    is_premium = _cache_premium_from_soup(soup)

    if notify:
        premium_text = parse_premium_from_header(soup)
        if is_premium and premium_text:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Přihlášeno. Premium: ' + premium_text.strip(),
                xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
        else:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Přihlášeno',
                xbmcgui.NOTIFICATION_INFO, 4000, sound=False)

    return is_premium, session.cookies


def prehrajto_logout() -> bool:
    session = get_session()
    base = get_prehrajto_base()
    referer = get_prehrajto_logout_referer()
    logout_url = base + '/odhlasit-se'
    headers = build_headers(get_user_agent(), referer)
    headers.update(get_headers())
    try:
        res = session.get(
            logout_url,
            headers=headers,
            allow_redirects=True,
        )
        remember_provider_page(res.url)
        dprint(f'prehrajto_logout(): GET {logout_url} referer={referer}')
    except Exception as exc:
        dprint(f'prehrajto_logout(): {exc}')
    clear_session()
    clear_prehrajto_browsing_context()
    set_prehrajto_auto_login_enabled(False)
    return True


def is_session_valid() -> bool:
    """Online session check (homepage GET). Updates cached premium when valid."""
    session = get_session()
    if not session.cookies:
        invalidate_auth_cache()
        return False
    try:
        soup = _fetch_home_soup()
        valid = parse_header_login_state(soup)
        if valid:
            _cache_premium_from_soup(soup)
        else:
            invalidate_auth_cache()
        return valid
    except Exception:
        invalidate_auth_cache()
        return False


def ensure_session_for_search(addon) -> None:
    """Log in only when there are no usable local auth cookies (no premium recheck)."""
    if not g_is_prehrajto_enabled:
        return
    if has_usable_auth_locally():
        return
    if not is_prehrajto_auto_login_enabled():
        return
    email = addon.getSetting('email')
    if not email:
        return
    dprint('prehrajto: no local session, logging in before search')
    prehrajto_login(addon, notify=False)


def ensure_premium(addon, notify: bool = False) -> Tuple[bool, Optional[RequestsCookieJar]]:
    """Validate persisted session or log in when auto-login is enabled."""
    if not g_is_prehrajto_enabled:
        return False, None

    session = get_session()
    if has_usable_auth_locally():
        if _premium_cached is not None:
            return _premium_cached, session.cookies
        try:
            soup = _fetch_home_soup()
            if parse_header_login_state(soup):
                return _cache_premium_from_soup(soup), session.cookies
        except Exception:
            pass
        invalidate_auth_cache()

    if not is_prehrajto_auto_login_enabled():
        return False, None

    email = addon.getSetting('email')
    if not email:
        return False, None

    return prehrajto_login(addon, notify=notify)
