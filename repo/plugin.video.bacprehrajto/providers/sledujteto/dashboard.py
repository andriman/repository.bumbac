import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from common import SLEDUJTETO_BASE, get_headers
from providers.browsing_context import remember_provider_page
from providers.sledujteto.session import get_session
from utils.utils import dprint

DASHBOARD_URL = SLEDUJTETO_BASE + '/account/dashboard/'
DASHBOARD_TIMEOUT = 30

_dashboard_html_cache: Optional[bytes] = None


def clear_dashboard_cache() -> None:
    global _dashboard_html_cache
    _dashboard_html_cache = None


def get_dashboard_html(force_refresh: bool = False) -> bytes:
    """Fetch account dashboard once per addon session; reuse cached HTML afterwards."""
    global _dashboard_html_cache
    if _dashboard_html_cache is not None and not force_refresh:
        return _dashboard_html_cache

    session = get_session()
    dprint(f'sledujteto dashboard: GET {DASHBOARD_URL}')
    res = session.get(DASHBOARD_URL, headers=get_headers(), timeout=DASHBOARD_TIMEOUT)
    res.raise_for_status()
    remember_provider_page(res.url)
    _dashboard_html_cache = res.content
    return _dashboard_html_cache


def get_dashboard_soup(force_refresh: bool = False) -> BeautifulSoup:
    return BeautifulSoup(get_dashboard_html(force_refresh=force_refresh), 'html.parser')


@dataclass
class DashboardCounts:
    my_videos: Optional[int] = None
    watchlist: Optional[int] = None


def _parse_int(text: str) -> Optional[int]:
    text = (text or '').strip()
    return int(text) if text.isdigit() else None


def _nav_link_badge_count(soup: BeautifulSoup, href_part: str) -> Optional[int]:
    for link in soup.find_all('a', class_=re.compile(r'nav-link'), href=True):
        href = link.get('href', '')
        if href_part not in href:
            continue
        badge = link.find('span', class_=re.compile(r'badge'))
        if badge is not None:
            count = _parse_int(badge.get_text(strip=True))
            if count is not None:
                return count
    return None


def _uploaded_videos_card_count(soup: BeautifulSoup) -> Optional[int]:
    for body in soup.select('.card-body'):
        heading = body.find('h3')
        if heading is None or 'Nahraných videí' not in heading.get_text(strip=True):
            continue
        count_node = body.find('div', class_=re.compile(r'fs-3'))
        if count_node is not None:
            count = _parse_int(count_node.get_text(strip=True))
            if count is not None:
                return count
    return None


def parse_dashboard_counts(soup: BeautifulSoup) -> DashboardCounts:
    my_videos = _nav_link_badge_count(soup, '/account/videos')
    if my_videos is None:
        my_videos = _uploaded_videos_card_count(soup)

    watchlist = _nav_link_badge_count(soup, '/account/watchlist')

    return DashboardCounts(my_videos=my_videos, watchlist=watchlist)


def fetch_dashboard_counts(force_refresh: bool = False) -> DashboardCounts:
    soup = get_dashboard_soup(force_refresh=force_refresh)
    return parse_dashboard_counts(soup)
