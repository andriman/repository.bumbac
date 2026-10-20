import re
from typing import List, Optional, Tuple
from urllib.parse import quote, urljoin

import xbmcgui
from bs4 import BeautifulSoup

from common import (
    SLEDUJTETO_BASE,
    g_sledujteto_max_searched_vids,
    g_sledujteto_search_max_pages,
    get_headers,
    icons_path,
    is_possible_nsfw,
)
from model.SearchMeta import SearchMeta
from providers.sledujteto.session import get_session
from providers.sledujteto.utils import (
    date_str_to_iso,
    duration_to_seconds,
    format_duration_hms,
    parameter_table_value,
)
from utils.search_browse_log import get_search_browse_logger
from utils.listitem_infotag import apply_art, apply_audio_stream_info, apply_video_info, apply_video_stream_info
from utils.utils import dprint, size_str_to_bytes

SEARCH_TIMEOUT = 30
VIDEOS_API = SLEDUJTETO_BASE + '/api/web/videos'
_BG_IMAGE_RE = re.compile(r'background-image:\s*url\(["\']?([^"\')]+)')


def _api_headers() -> dict:
    return {
        **get_headers(),
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
    }


def _clock_label(duration) -> str:
    if duration is None or str(duration).strip() == '':
        return ''
    try:
        return format_duration_hms(duration)
    except ValueError:
        return str(duration).strip()


def _file_json_to_listitem(item: dict) -> Optional[xbmcgui.ListItem]:
    title = item.get('filename') or item.get('name') or ''
    if not title:
        return None

    is_nsfw = item.get('is_nsfw')
    resolution = item.get('resolution') or item.get('movie_resolution') or ''
    duration = item.get('duration') or item.get('movie_duration') or ''
    file_size = item.get('filesize') or ''
    page_url = item.get('full_url') or item.get('link') or urljoin(
        SLEDUJTETO_BASE, item.get('url', ''),
    )
    thumb = item.get('preview') or ''

    size_text = str(file_size or '').strip()
    label = f'[{resolution}] | {title}'
    if size_text:
        label = f'{label} | {size_text}'
    list_item = xbmcgui.ListItem(
        label=label,
        label2=_clock_label(duration),
        path=page_url,
        offscreen=True,
    )

    stream_info = {'mediatype': 'video'}
    if duration:
        try:
            stream_info['duration'] = duration_to_seconds(duration)
        except ValueError:
            pass
    if file_size:
        try:
            stream_info['size'] = size_str_to_bytes(file_size)
        except (ValueError, TypeError):
            pass
    if resolution and '*' in resolution:
        width, height = resolution.split('*', 1)
        stream_info['width'] = width.strip()
        stream_info['height'] = height.strip()
        try:
            stream_info['aspect'] = int(width) / int(height)
        except (ValueError, ZeroDivisionError):
            pass
    if item.get('movie_codec'):
        stream_info['codec'] = item['movie_codec']

    apply_video_stream_info(list_item, stream_info)
    if item.get('movie_audiocodec'):
        apply_audio_stream_info(list_item, {
            'codec': item['movie_audiocodec'],
            'channels': item.get('movie_audiochannels'),
        })

    date_added = item.get('uploaded')
    plot_parts = []
    if date_added:
        try:
            plot_parts.append('Uploaded: ' + date_str_to_iso(date_added))
        except ValueError:
            plot_parts.append('Uploaded: ' + date_added)
    if item.get('likes') is not None:
        plot_parts.append('Likes: ' + str(item['likes']))
    if is_nsfw:
        plot_parts.append('NSFW')
    if plot_parts:
        apply_video_info(list_item, {'plot': ' | '.join(plot_parts), 'mediatype': 'video', 'title': title})

    art = {'icon': icons_path + 'sledujteto.jpg'}
    if thumb:
        art['poster'] = thumb
        art['thumb'] = thumb
    apply_art(list_item, art)
    list_item.setProperty('IsPlayable', 'true')
    return list_item


def _fetch_search_api(query: str, skip_nsfw: bool) -> Tuple[List[xbmcgui.ListItem], int]:
    session = get_session()
    items: List[xbmcgui.ListItem] = []
    page = 1
    page_count = 1
    max_items = int(g_sledujteto_max_searched_vids)
    max_pages = int(g_sledujteto_search_max_pages)

    while page <= page_count and len(items) < max_items and page <= max_pages:
        params = {
            'query': query,
            'limit': min(50, max_items - len(items)),
            'page': page,
            'sort': 'relevance',
            'me': 0,
        }
        dprint(f'sledujteto search(): API page {page} query={query}')
        res = session.get(VIDEOS_API, params=params, headers=_api_headers(), timeout=SEARCH_TIMEOUT)
        res.raise_for_status()
        payload = res.json()

        if payload.get('error'):
            msg = payload.get('msg') or 'Neznámá chyba API'
            raise RuntimeError(msg)

        data = payload.get('data') or {}
        files = data.get('files')
        if not isinstance(files, list):
            raise RuntimeError('Neočekávaná odpověď API (chybí seznam souborů)')

        page_count = int(data.get('pages') or 1)
        items_before = len(items)
        for file_item in files:
            title = file_item.get('filename') or file_item.get('name') or ''
            if skip_nsfw and (file_item.get('is_nsfw') or is_possible_nsfw(title)):
                continue
            list_item = _file_json_to_listitem(file_item)
            if list_item is not None:
                items.append(list_item)
            if len(items) >= max_items:
                break

        browse_log = get_search_browse_logger()
        if browse_log is not None:
            browse_log.log_sledujteto_page(
                page=page,
                video_count=len(items),
                added_on_page=len(items) - items_before,
                total_api_pages=page_count,
            )
        page += 1

    return items, page_count


def _badge_text(card: BeautifulSoup, icon_class: str) -> str:
    for badge in card.select('.video-stats .badge'):
        icon = badge.find('i')
        if icon is None:
            continue
        classes = icon.get('class') or []
        if icon_class not in classes:
            continue
        span = badge.find('span')
        if span:
            return span.get_text(strip=True)
    return ''


def _extract_thumbnail(card: BeautifulSoup) -> str:
    for node in card.select('figure [style*="background-image"]'):
        match = _BG_IMAGE_RE.search(node.get('style', ''))
        if match:
            return match.group(1).strip()
    return ''


def _parse_file_card(card: BeautifulSoup) -> Optional[xbmcgui.ListItem]:
    link = card.select_one('h2 a[href^="/file/"]') or card.select_one('a[href^="/file/"]')
    if link is None:
        return None

    title = link.get('title') or link.get_text(strip=True)
    if not title:
        return None

    page_url = urljoin(SLEDUJTETO_BASE, link.get('href', ''))
    duration = _badge_text(card, 'bi-clock') or parameter_table_value(card, 'Trvání')
    resolution = _badge_text(card, 'bi-display') or parameter_table_value(card, 'Rozli')
    file_size = parameter_table_value(card, 'Velikost').strip()

    label_parts = []
    if resolution:
        label_parts.append(f'[{resolution}]')
    label_parts.append(title)
    if file_size:
        label_parts.append(file_size)

    list_item = xbmcgui.ListItem(
        label=' | '.join(label_parts),
        label2=_clock_label(duration),
        path=page_url,
        offscreen=True,
    )

    stream_info = {'mediatype': 'video'}
    if duration:
        try:
            stream_info['duration'] = duration_to_seconds(duration)
        except ValueError:
            pass
    if resolution and '*' in resolution:
        width, height = resolution.split('*', 1)
        try:
            stream_info['aspect'] = int(width) / int(height)
        except (ValueError, ZeroDivisionError):
            pass

    apply_video_stream_info(list_item, stream_info)
    apply_video_info(list_item, {'mediatype': 'video', 'title': title})
    thumb = _extract_thumbnail(card)
    art = {'icon': icons_path + 'sledujteto.jpg'}
    if thumb:
        art['poster'] = thumb
        art['thumb'] = thumb
    apply_art(list_item, art)
    list_item.setProperty('IsPlayable', 'true')
    return list_item


def _card_marked_nsfw(card: BeautifulSoup) -> bool:
    classes = ' '.join(card.get('class') or []).lower()
    if 'nsfw' in classes:
        return True
    for node in card.select('[class*="nsfw"], [data-nsfw]'):
        return True
    return False


def parse_search_html(html: bytes, skip_nsfw: bool = False) -> List[xbmcgui.ListItem]:
    soup = BeautifulSoup(html, 'html.parser')
    items: List[xbmcgui.ListItem] = []
    for card in soup.select('article.file-card'):
        if skip_nsfw and _card_marked_nsfw(card):
            continue
        item = _parse_file_card(card)
        if item is None:
            continue
        if skip_nsfw and is_possible_nsfw(item.getLabel() or ''):
            continue
        items.append(item)
    return items


def _fetch_search_html(query: str, skip_nsfw: bool = False) -> List[xbmcgui.ListItem]:
    session = get_session()
    url = f'{SLEDUJTETO_BASE}/vyhledat/?search={quote(query)}'
    dprint(f'sledujteto search(): HTML fallback GET {url}')
    res = session.get(url, headers=get_headers(), timeout=SEARCH_TIMEOUT)
    res.raise_for_status()
    from providers.browsing_context import remember_provider_page
    remember_provider_page(res.url)
    return parse_search_html(res.content, skip_nsfw=skip_nsfw)


def fetch_search(query: str, skip_nsfw: bool = False) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
    try:
        items, pages_loaded = _fetch_search_api(query, skip_nsfw)
        if items:
            dprint(f'sledujteto search(): API found {len(items)} items')
            return items, SearchMeta(pages_scraped=pages_loaded, cancelled=False, is_complete=True)
    except Exception as exc:
        dprint(f'sledujteto search(): API failed, trying HTML: {exc}')

    items = _fetch_search_html(query, skip_nsfw=skip_nsfw)
    dprint(f'sledujteto search(): HTML found {len(items)} items')
    browse_log = get_search_browse_logger()
    if browse_log is not None:
        browse_log.log_sledujteto_page(
            page=1,
            video_count=len(items),
            added_on_page=len(items),
            total_api_pages=1,
        )
    max_items = int(g_sledujteto_max_searched_vids)
    if len(items) > max_items:
        items = items[:max_items]
    return items, SearchMeta(pages_scraped=1, cancelled=False, is_complete=True)
