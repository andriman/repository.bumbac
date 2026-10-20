import time
from typing import Any, List, Optional, Tuple
from urllib.parse import quote, urljoin

import xbmcgui
from bs4 import BeautifulSoup

from common import (
    _ADDON_NAME,
    g_hellspy_max_searched_vids,
    g_hellspy_search_max_pages,
    g_max_duplicities,
    g_search_page_delay_seconds,
    g_truncate_titles,
    get_hellspy_api_base,
    get_hellspy_base,
    is_possible_nsfw,
)
from model.SearchMeta import SearchMeta
from providers.browsing_context import remember_provider_page
from providers.hellspy.payload import (
    extract_initial_data,
    has_next_offset,
    same_offset,
    search_page,
)
from providers.hellspy.auth import request_headers
from providers.hellspy.session import get_session, save_session
from providers.prehrajto.duration_to_seconds import duration_to_seconds
from utils.StrUtils import convert_size, truncate_middle
from utils.listitem_infotag import attach_listing_stream_info_property
from utils.search_browse_log import get_search_browse_logger
from utils.stream_fake_hint import LISTING_THUMB_PROP
from utils.utils import dprint, size_str_to_bytes

SEARCH_TIMEOUT = 30
PAGE_LIMIT = 64


def _clock_label(duration: Optional[int]) -> str:
    if duration is None or duration < 0:
        return ''
    hours, remainder = divmod(int(duration), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def _size_label(size: object) -> str:
    try:
        return convert_size(int(size), 2)
    except (TypeError, ValueError):
        return ''


def _update_dialog(dialog: xbmcgui.DialogProgress, items: list, page: int, line3: str) -> None:
    step = max(1, int(100 / max(1, g_hellspy_max_searched_vids)))
    pct = max(0, min(100, int(len(items) * step)))
    line1 = f'Strana: {page}'
    line2 = f'Video souborů: {len(items)}'
    try:
        dialog.update(pct, line1, line2, line3 or ' ')
    except TypeError:
        dialog.update(pct, '\n'.join([line1, line2, line3 or ' ']))


def _wait_for_next_page(dialog: xbmcgui.DialogProgress, items: list, page: int, next_page: int) -> bool:
    delay_seconds = int(g_search_page_delay_seconds)
    if delay_seconds <= 0:
        return dialog.iscanceled()
    for remaining in range(delay_seconds, 0, -1):
        if dialog.iscanceled():
            return True
        _update_dialog(dialog, items, page, f'Načtení strany {next_page} za: {remaining} s')
        end = time.time() + 1.0
        while time.time() < end:
            if dialog.iscanceled():
                return True
            time.sleep(0.1)
    return dialog.iscanceled()


def _first_thumb(raw: object) -> str:
    if not isinstance(raw, list):
        return ''
    for candidate in raw:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ''


def _hit_from_api(item: dict, base: str) -> Optional[dict]:
    title = str(item.get('title') or '').strip()
    file_hash = str(item.get('fileHash') or '').strip()
    video_id = item.get('id')
    if not title or not file_hash or video_id is None:
        return None
    duration = item.get('duration') if isinstance(item.get('duration'), int) else None
    return {
        'title': title,
        'path': f'{base}/video/{file_hash}/{video_id}',
        'size_label': _size_label(item.get('size')),
        'duration_label': _clock_label(duration),
        'duration_seconds': duration,
        'size_bytes': item.get('size') if isinstance(item.get('size'), int) else None,
        'thumb': _first_thumb(item.get('thumbs')),
        'nsfw': bool(item.get('is_nsfw') or item.get('nsfw') or item.get('adult')),
    }


def _hits_from_html(html: str, base: str) -> List[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    hits = []
    for card in soup.select('a.result-video'):
        href = (card.get('href') or '').strip()
        title = (card.get('title') or '').strip()
        if not title:
            heading = card.find('h3')
            title = heading.get_text(strip=True) if heading else ''
        if not href or not title:
            continue
        info = card.select('.thumbnail-info p')
        size_label = info[0].get_text(strip=True) if len(info) > 0 else ''
        duration_label = info[1].get_text(strip=True) if len(info) > 1 else ''
        image = card.find('img')
        thumb = (image.get('src') or '').strip() if image else ''
        duration_seconds = None
        if duration_label:
            try:
                duration_seconds = duration_to_seconds(duration_label)
            except ValueError:
                duration_seconds = None
        size_bytes = None
        if size_label:
            try:
                size_bytes = size_str_to_bytes(size_label)
            except (ValueError, TypeError):
                size_bytes = None
        classes = ' '.join(card.get('class') or []).lower()
        hits.append({
            'title': title,
            'path': urljoin(base + '/', href.lstrip('/')),
            'size_label': size_label,
            'duration_label': duration_label,
            'duration_seconds': duration_seconds,
            'size_bytes': size_bytes,
            'thumb': thumb,
            'nsfw': 'nsfw' in classes,
        })
    return hits


def _list_item(hit: dict) -> xbmcgui.ListItem:
    title = hit['title']
    if g_truncate_titles:
        title = truncate_middle(title)
    size_label = (hit.get('size_label') or '').strip()
    if size_label:
        title = f'{title} | {size_label}'
    label2 = (hit.get('duration_label') or '').strip()
    list_item = xbmcgui.ListItem(label=title, label2=label2, path=hit['path'], offscreen=True)
    stream_info = {'mediatype': 'video'}
    if hit.get('duration_seconds'):
        stream_info['duration'] = hit['duration_seconds']
    if hit.get('size_bytes'):
        stream_info['size'] = hit['size_bytes']
    attach_listing_stream_info_property(list_item, stream_info)
    if hit.get('thumb'):
        list_item.setProperty(LISTING_THUMB_PROP, hit['thumb'])
    list_item.setProperty('IsPlayable', 'true')
    return list_item


def _load_page(session, query: str, page: int, next_offset: Any) -> Tuple[List[dict], Optional[Any]]:
    base = get_hellspy_base()
    if page == 1:
        search_url = f'{base}/?query={quote(query)}'
        dprint(f'hellspy search(): GET {search_url}')
        response = session.get(search_url, headers=request_headers(), timeout=SEARCH_TIMEOUT)
        response.raise_for_status()
        save_session()
        remember_provider_page(response.url)
        html = response.text
        initial = extract_initial_data(html)
        if initial is not None:
            videos, cursor = search_page(initial)
            hits = [hit for hit in (_hit_from_api(item, base) for item in videos) if hit]
            if hits:
                return hits, cursor
        return _hits_from_html(html, base), None

    api_url = get_hellspy_api_base() + '/gw/search'
    headers = request_headers({
        'Accept': 'application/json',
        'Referer': f'{base}/?query={quote(query)}',
        'Origin': base,
    })
    dprint(f'hellspy search(): GET {api_url} offset={next_offset}')
    response = session.get(
        api_url,
        params={'query': query, 'offset': next_offset, 'limit': PAGE_LIMIT},
        headers=headers,
        timeout=SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    save_session()
    videos, cursor = search_page(response.json())
    hits = [hit for hit in (_hit_from_api(item, base) for item in videos) if hit]
    return hits, cursor


def fetch_search(query: str, skip_nsfw: bool = False) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
    max_items = int(g_hellspy_max_searched_vids)
    max_pages = int(g_hellspy_search_max_pages)
    items: List[xbmcgui.ListItem] = []
    duplicities = {}
    pages_loaded = 0
    next_offset = None
    stop_searching = False
    cancelled = False

    dialog = xbmcgui.DialogProgress()
    dialog.create(_ADDON_NAME, 'Hledám na HellSpy...')
    _update_dialog(dialog, items, 1, ' ')
    session = get_session()

    try:
        page = 1
        while page <= max_pages and len(items) < max_items and not stop_searching:
            if dialog.iscanceled():
                cancelled = True
                break
            if page > 1:
                if not has_next_offset(next_offset):
                    stop_searching = True
                    break
                if _wait_for_next_page(dialog, items, pages_loaded, page):
                    cancelled = True
                    break

            _update_dialog(dialog, items, page, 'Načítám stránku...')
            requested_offset = next_offset
            hits, cursor = _load_page(session, query, page, next_offset)
            items_before = len(items)
            for hit in hits:
                if len(items) >= max_items:
                    break
                if skip_nsfw and (hit.get('nsfw') or is_possible_nsfw(hit['title'])):
                    continue
                dup_key = f"{hit['title']} ({hit.get('size_label') or ''} - {hit.get('duration_label') or ''})"
                seen = duplicities.get(dup_key, 0)
                if seen >= g_max_duplicities:
                    continue
                duplicities[dup_key] = seen + 1
                items.append(_list_item(hit))

            pages_loaded = page
            added = len(items) - items_before
            dprint(f'hellspy search(): page {page}: +{added} items, total={len(items)} next={cursor}')
            browse_log = get_search_browse_logger()
            if browse_log is not None:
                browse_log.log_hellspy_page(page=page, video_count=len(items), added_on_page=added)

            _update_dialog(dialog, items, page, ' ')
            page_added_nothing = added == 0
            cursor_stalled = page > 1 and same_offset(cursor, requested_offset)
            stop_searching = (
                page_added_nothing
                or not has_next_offset(cursor)
                or cursor_stalled
                or len(items) >= max_items
                or page >= max_pages
            )
            next_offset = cursor
            page += 1
    finally:
        dialog.close()

    is_complete = stop_searching and not cancelled
    return items, SearchMeta(
        pages_scraped=pages_loaded,
        cancelled=cancelled,
        is_complete=is_complete,
    )
