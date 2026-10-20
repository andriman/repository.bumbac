from typing import List, Optional
from urllib.parse import urljoin

import xbmcgui
from bs4 import BeautifulSoup

from common import SLEDUJTETO_BASE, get_headers, icons_path
from providers.sledujteto.auth import MY_VIDEOS_URL, WATCHLIST_URL, parse_login_state
from providers.sledujteto.parse_search import (
    SEARCH_TIMEOUT,
    VIDEOS_API,
    _api_headers,
    _file_json_to_listitem,
    _parse_file_card,
    parse_search_html,
)
from providers.sledujteto.dashboard import get_dashboard_html
from providers.sledujteto.session import get_session
from utils.listitem_infotag import apply_video_info, apply_video_stream_info
from utils.utils import dprint, size_str_to_bytes


def _fetch_videos_from_api(params: dict) -> List[xbmcgui.ListItem]:
    session = get_session()
    items: List[xbmcgui.ListItem] = []
    page = 1
    page_count = 1

    while page <= page_count:
        req_params = dict(params)
        req_params['page'] = page
        req_params.setdefault('limit', 50)
        dprint(f'sledujteto account listing API: {req_params}')
        res = session.get(VIDEOS_API, params=req_params, headers=_api_headers(), timeout=SEARCH_TIMEOUT)
        res.raise_for_status()
        payload = res.json()
        if payload.get('error'):
            raise RuntimeError(payload.get('msg') or 'API error')

        data = payload.get('data') or {}
        files = data.get('files')
        if not isinstance(files, list):
            break

        page_count = int(data.get('pages') or 1)
        for file_item in files:
            list_item = _file_json_to_listitem(file_item)
            if list_item is not None:
                items.append(list_item)
        page += 1

    return items


def _parse_my_videos_table(html: bytes) -> List[xbmcgui.ListItem]:
    soup = BeautifulSoup(html, 'html.parser')
    items: List[xbmcgui.ListItem] = []

    for row in soup.select('#video-list tbody tr'):
        if 'video-list-item-form' in (row.get('class') or []):
            continue
        link = row.select_one('a[href^="/file/"]')
        if link is None:
            continue

        title = link.get('title') or link.get_text(strip=True)
        if not title:
            continue
        title = title.replace('Přehrát video: ', '').strip()

        page_url = urljoin(SLEDUJTETO_BASE, link.get('href', ''))
        cells = row.find_all('td')
        uploaded = ''
        file_size = ''
        if len(cells) >= 2:
            uploaded = cells[1].get_text(strip=True)
        if len(cells) >= 3:
            file_size = cells[2].get_text(strip=True)

        status_badges = []
        for badge in row.select('.badge'):
            text = badge.get_text(strip=True)
            if text and text not in (uploaded, file_size):
                status_badges.append(text)

        label2 = file_size or uploaded
        label = title
        if file_size:
            label = f'{title} | {file_size}'

        list_item = xbmcgui.ListItem(label=label, label2=label2, path=page_url, offscreen=True)
        stream_info = {'mediatype': 'video'}
        if file_size:
            try:
                stream_info['size'] = size_str_to_bytes(file_size)
            except (ValueError, TypeError):
                pass
        apply_video_stream_info(list_item, stream_info)

        plot_parts = []
        if uploaded:
            plot_parts.append(f'Nahráno: {uploaded}')
        if status_badges:
            plot_parts.append(' | '.join(status_badges))
        if plot_parts:
            apply_video_info(list_item, {
                'plot': ' | '.join(plot_parts),
                'mediatype': 'video',
                'title': title,
            })

        list_item.setArt({'icon': icons_path + 'sledujteto.jpg'})
        list_item.setProperty('IsPlayable', 'true')
        items.append(list_item)

    return items


def _fetch_page_html(url: str) -> bytes:
    from providers.browsing_context import remember_provider_page
    session = get_session()
    res = session.get(url, headers=get_headers(), timeout=SEARCH_TIMEOUT)
    res.raise_for_status()
    remember_provider_page(res.url)
    return res.content


def _ensure_logged_in_html(html: bytes, page_name: str) -> None:
    soup = BeautifulSoup(html, 'html.parser')
    if not parse_login_state(soup):
        raise RuntimeError(f'Pro {page_name} se musíte přihlásit')


def _ensure_dashboard_session() -> None:
    get_dashboard_html()


def fetch_my_videos() -> List[xbmcgui.ListItem]:
    _ensure_dashboard_session()
    try:
        items = _fetch_videos_from_api({'me': 1, 'sort': 'date', 'limit': 50})
        if items:
            dprint(f'sledujteto my videos: API returned {len(items)} items')
            return items
    except Exception as exc:
        dprint(f'sledujteto my videos: API failed: {exc}')

    html = _fetch_page_html(MY_VIDEOS_URL)
    _ensure_logged_in_html(html, 'Moje videa')
    items = _parse_my_videos_table(html)
    dprint(f'sledujteto my videos: HTML returned {len(items)} items')
    return items


def fetch_watchlist() -> List[xbmcgui.ListItem]:
    _ensure_dashboard_session()
    try:
        items = _fetch_videos_from_api({'collection': 'watchlist', 'sort': 'date', 'limit': 50, 'me': 0})
        if items:
            dprint(f'sledujteto watchlist: API returned {len(items)} items')
            return items
    except Exception as exc:
        dprint(f'sledujteto watchlist: API failed: {exc}')

    html = _fetch_page_html(WATCHLIST_URL)
    _ensure_logged_in_html(html, 'Přehrát později')
    soup = BeautifulSoup(html, 'html.parser')
    items: List[xbmcgui.ListItem] = []
    for card in soup.select('article.file-card'):
        item = _parse_file_card(card)
        if item is not None:
            items.append(item)
    if not items:
        items = parse_search_html(html)
    dprint(f'sledujteto watchlist: HTML returned {len(items)} items')
    return items
