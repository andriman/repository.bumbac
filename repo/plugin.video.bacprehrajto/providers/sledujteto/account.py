from typing import Optional

from common import addon
from model.AccountInfo import AccountInfo
from providers.sledujteto.auth import (
    parse_account_email_from_header,
    parse_login_state,
    parse_premium_from_header,
)
from providers.sledujteto.dashboard import get_dashboard_soup, parse_dashboard_counts
from providers.sledujteto.session import get_session


def _premium_is_active(premium_text: Optional[str]) -> bool:
    if not premium_text:
        return False
    normalized = premium_text.strip().lower()
    if 'neaktivní' in normalized or 'neaktivni' in normalized:
        return False
    return 'aktivní' in normalized or 'aktivni' in normalized


def fetch_account_status(addon_ref=None) -> AccountInfo:
    """Read Sledujteto account state from dashboard (cached per session)."""
    ref = addon_ref or addon
    email_setting = ref.getSetting('sledujteto_email') or ''

    session = get_session()
    if not session.cookies:
        return AccountInfo(is_logged_in=False, account_name=email_setting)

    try:
        soup = get_dashboard_soup()
    except Exception:
        return AccountInfo(is_logged_in=False, account_name=email_setting)

    logged_in = parse_login_state(soup)
    if not logged_in:
        return AccountInfo(is_logged_in=False, account_name=email_setting)

    premium_text = parse_premium_from_header(soup) or ''
    account_email = parse_account_email_from_header(soup) or email_setting
    counts = parse_dashboard_counts(soup)

    return AccountInfo(
        is_logged_in=True,
        account_name=account_email,
        expiration=premium_text,
        is_premium=_premium_is_active(premium_text),
        my_videos_count=counts.my_videos,
        watchlist_count=counts.watchlist,
    )
