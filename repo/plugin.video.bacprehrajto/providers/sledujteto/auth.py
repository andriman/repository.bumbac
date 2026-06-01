from typing import Optional, Tuple

import re

import xbmcgui
from bs4 import BeautifulSoup
from requests.cookies import RequestsCookieJar

from common import (
    SLEDUJTETO_BASE,
    _ADDON_NAME,
    get_headers,
    get_user_agent,
    g_is_sledujteto_enabled,
    is_sledujteto_auto_login_enabled,
    set_sledujteto_auto_login_enabled,
)
from providers.browsing_context import (
    clear_sledujteto_browsing_context,
    get_sledujteto_logout_referer,
    remember_provider_page,
)
from providers.sledujteto.session import clear_session, get_session, save_session
from providers.sledujteto.dashboard import clear_dashboard_cache, get_dashboard_html
from utils.utils import build_headers, dprint

LOGIN_URL = SLEDUJTETO_BASE + '/account/login/'
LOGOUT_URL = SLEDUJTETO_BASE + '/account/logout/'
MY_VIDEOS_URL = SLEDUJTETO_BASE + '/account/videos/'
WATCHLIST_URL = SLEDUJTETO_BASE + '/account/watchlist/'


def parse_login_state(soup: BeautifulSoup) -> bool:
    """Return True when the page shows a logged-in user."""
    if soup.find('a', href=re.compile(r'/account/logout')):
        return True
    if soup.find('a', href=re.compile(r'/account/dashboard')):
        return True
    for link in soup.find_all('a', href=True):
        text = link.get_text(strip=True)
        if text in ('Odhlásit se', 'Odhlásit'):
            return True

    page_text = soup.get_text(' ', strip=True)
    if 'Pro pokračování se prosím přihlaste' in page_text:
        return False

    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True)
        if href.startswith('/account/login') and 'Přihlásit se' in text:
            return False

    return False


def parse_premium_from_header(soup: BeautifulSoup) -> Optional[str]:
    for link in soup.select('a[href*="credits/buy"]'):
        span = link.find('span', class_=re.compile(r'text-primary'))
        if span:
            text = span.get_text(strip=True)
            if text:
                return text
        text = link.get_text(' ', strip=True)
        match = re.search(r'Premium:\s*(.+)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def parse_account_email_from_header(soup: BeautifulSoup) -> Optional[str]:
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if '/account/dashboard' not in href:
            continue
        for span in link.find_all('span'):
            text = span.get_text(strip=True)
            if '@' in text:
                return text
    return None


def _parse_login_error(soup: BeautifulSoup) -> Optional[str]:
    for node in soup.select('.callout.alert-danger, .alert-danger'):
        text = node.get_text(' ', strip=True)
        if text:
            return text
    return None


def _login_form_data(email: str, password: str, last_uri: str = '') -> dict:
    return {
        'email': email,
        'password': password,
        'remember': '1',
        'last_uri': last_uri,
        'form_id': 'Form_Login',
        'model_id': '0',
        'login': 'Přihlásit',
    }


def sledujteto_login(
        addon,
        email: Optional[str] = None,
        password: Optional[str] = None,
        notify: bool = True,
) -> Tuple[bool, Optional[RequestsCookieJar]]:
    """
    Log in to sledujteto.cz. Reads sledujteto_email / sledujteto_password settings
    when arguments are omitted (settings may be added later).
    """
    email = email or addon.getSetting('sledujteto_email')
    password = password or addon.getSetting('sledujteto_password')
    if not email or not password:
        return False, None

    session = get_session()
    home = SLEDUJTETO_BASE + '/'
    session.get(home, headers=get_headers())
    remember_provider_page(home)
    res = session.post(
        LOGIN_URL,
        data=_login_form_data(email, password),
        headers={**get_headers(), 'Referer': LOGIN_URL},
        allow_redirects=True,
    )
    remember_provider_page(res.url)

    soup = BeautifulSoup(res.content, 'html.parser')
    error_text = _parse_login_error(soup)
    if error_text:
        if notify:
            xbmcgui.Dialog().ok(_ADDON_NAME, error_text)
        return False, None

    if not parse_login_state(soup):
        check = session.get(SLEDUJTETO_BASE + '/', headers=get_headers())
        soup = BeautifulSoup(check.content, 'html.parser')
        if not parse_login_state(soup):
            if notify:
                xbmcgui.Dialog().notification(
                    _ADDON_NAME, 'Přihlášení se nezdařilo',
                    xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
            return False, None

    save_session()
    clear_dashboard_cache()
    get_dashboard_html(force_refresh=True)
    if notify:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Přihlášeno na Sledujteto.cz',
            xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
    return True, session.cookies


def sledujteto_logout() -> bool:
    session = get_session()
    referer = get_sledujteto_logout_referer()
    headers = build_headers(get_user_agent(), referer)
    headers.update(get_headers())
    try:
        res = session.get(
            LOGOUT_URL,
            headers=headers,
            allow_redirects=True,
        )
        remember_provider_page(res.url)
        dprint(f'sledujteto_logout(): GET {LOGOUT_URL} referer={referer}')
    except Exception as exc:
        dprint(f'sledujteto_logout(): {exc}')
    clear_session()
    clear_dashboard_cache()
    clear_sledujteto_browsing_context()
    set_sledujteto_auto_login_enabled(False)
    return True


def is_session_valid() -> bool:
    session = get_session()
    if not session.cookies:
        return False
    try:
        res = session.get(SLEDUJTETO_BASE + '/', headers=get_headers())
        remember_provider_page(res.url)
        soup = BeautifulSoup(res.content, 'html.parser')
        return parse_login_state(soup)
    except Exception:
        return False


def ensure_login(addon, notify: bool = False) -> Tuple[bool, Optional[RequestsCookieJar]]:
    """Validate persisted session or log in when auto-login is enabled."""
    if not g_is_sledujteto_enabled:
        return False, None

    if is_session_valid():
        return True, get_session().cookies

    if not is_sledujteto_auto_login_enabled():
        return False, None

    email = addon.getSetting('sledujteto_email')
    if not email:
        return False, None

    return sledujteto_login(addon, notify=notify)
