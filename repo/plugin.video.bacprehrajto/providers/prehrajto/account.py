import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from common import get_headers, get_prehrajto_base
from providers.browsing_context import remember_provider_page
from model.AccountInfo import AccountInfo
from providers.prehrajto.auth import (
    _cache_premium_from_soup,
    is_session_valid,
    parse_header_login_state,
    parse_premium_status_from_header,
)
from providers.prehrajto.session import get_session, get_session_expiration


def _find_account_section(soup: BeautifulSoup):
    for heading in soup.find_all(['h2', 'strong', 'span']):
        text = heading.get_text(strip=True)
        if 'Informace o účtu' in text:
            section = heading.find_parent('div', class_=re.compile(r'section__content'))
            if section:
                return section
    return None


def _parse_grid_value(section: BeautifulSoup, label_pattern: str) -> str:
    for row in section.find_all('div', class_='grid-x'):
        left = row.find('div', class_=re.compile(r'cell'))
        if left is None:
            continue
        strong = left.find('strong')
        if strong is None:
            continue
        label = strong.get_text(strip=True).upper()
        if label_pattern.upper() not in label:
            continue
        right_cells = row.find_all('div', class_=re.compile(r'cell'))
        if len(right_cells) < 2:
            continue
        value_cell = right_cells[-1]
        bold = value_cell.find('b') or value_cell.find('strong')
        if bold:
            return bold.get_text(strip=True)
        text = value_cell.get_text(' ', strip=True)
        text = re.sub(r'^Vyprší za\s*', '', text, flags=re.IGNORECASE).strip()
        return text
    return ''


def _parse_expiration(section: BeautifulSoup) -> str:
    for row in section.find_all('div', class_='grid-x'):
        cells = row.find_all('div', class_=re.compile(r'cell'))
        if len(cells) < 2:
            continue
        right_cell = cells[-1]
        right_text = right_cell.get_text(' ', strip=True)
        if 'Vyprší' not in right_text:
            continue
        strong = right_cell.find('strong')
        if strong:
            value = strong.get_text(strip=True)
            if value and 'Vyprší' not in value:
                return value
        match = re.search(r'Vyprší za\s*(.+)', right_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ''


def _parse_membership_status(section: BeautifulSoup) -> str:
    return _parse_grid_value(section, 'PREMIUM')


_INACTIVE_MEMBERSHIP_VALUES = frozenset({
    'neobjednáno',
    'neaktivní',
})


def _profile_membership_is_premium(value: str) -> bool:
    if not value:
        return False
    return value.strip().lower() not in _INACTIVE_MEMBERSHIP_VALUES


def _parse_premium_expiration_display(expiration: str) -> tuple:
    """Return (date YYYY-MM-DD, countdown label) from strings like '29 dní'."""
    if not expiration:
        return '', ''
    match = re.search(r'(\d+)', expiration)
    if not match:
        return '', expiration
    days = int(match.group(1))
    exp_date = date.today() + timedelta(days=days)
    unit = 'day' if days == 1 else 'days'
    return exp_date.strftime('%Y-%m-%d'), f'{days} {unit}'


def _parse_profile(soup: BeautifulSoup) -> dict:
    section = _find_account_section(soup)
    if section is None:
        return {}
    return {
        'membership_status': _parse_membership_status(section),
        'expiration': _parse_expiration(section),
        'recurring_payment': _parse_grid_value(section, 'OPAKOVAN'),
        'next_payment': _parse_grid_value(section, 'DALŠÍ PLATBA'),
    }


def fetch_account_status(addon, fetch_profile: bool = True) -> AccountInfo:
    """Read account state from persisted session only — never triggers login."""
    email = addon.getSetting('email') or ''
    session_expires_date, session_expires_days = get_session_expiration()

    if not is_session_valid():
        return AccountInfo(
            is_logged_in=False,
            account_name=email,
            session_expires_date=session_expires_date,
            session_expires_days=session_expires_days,
        )

    session = get_session()
    res = session.get(get_prehrajto_base() + '/', headers=get_headers())
    remember_provider_page(res.url)
    home_soup = BeautifulSoup(res.content, 'html.parser')
    logged_in = parse_header_login_state(home_soup)
    if not logged_in:
        return AccountInfo(
            is_logged_in=False,
            account_name=email,
            session_expires_date=session_expires_date,
            session_expires_days=session_expires_days,
        )

    _cache_premium_from_soup(home_soup)
    is_premium, premium_text = parse_premium_status_from_header(home_soup)
    expiration = premium_text or '' if is_premium else ''
    membership_status = ''
    recurring_payment = ''
    next_payment = ''

    if fetch_profile:
        prof_res = session.get(get_prehrajto_base() + '/profil', headers=get_headers())
        remember_provider_page(prof_res.url)
        profile = _parse_profile(BeautifulSoup(prof_res.content, 'html.parser'))
        membership_status = profile.get('membership_status', '')
        expiration = profile.get('expiration') or (premium_text if is_premium else '') or ''
        recurring_payment = profile.get('recurring_payment', '')
        next_payment = profile.get('next_payment', '')
        if membership_status:
            is_premium = _profile_membership_is_premium(membership_status)
            if is_premium and not expiration:
                expiration = membership_status

    if not expiration and not is_premium:
        expiration = ''

    expiration_date, expiration_days = _parse_premium_expiration_display(expiration)
    session_expires_date, session_expires_days = get_session_expiration()

    return AccountInfo(
        is_logged_in=True,
        account_name=email,
        membership_status=membership_status,
        expiration=expiration,
        expiration_date=expiration_date,
        expiration_days=expiration_days,
        recurring_payment=recurring_payment,
        next_payment=next_payment,
        is_premium=is_premium,
        session_expires_date=session_expires_date,
        session_expires_days=session_expires_days,
    )
