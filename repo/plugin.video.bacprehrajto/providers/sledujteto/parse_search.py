import re
from typing import List, Optional, Tuple
from urllib.parse import quote, urljoin

import xbmcgui
from bs4 import BeautifulSoup

from common import SLEDUJTETO_BASE, g_max_searched_vids, get_headers, icons_path
from model.SearchMeta import SearchMeta
from providers.sledujteto.session import get_session
from providers.sledujteto.utils import date_str_to_iso, duration_to_seconds
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

    label = f'[{resolution}] | {title} | {file_size or duration}'
    list_item = xbmcgui.ListItem(
        label=label,
        label2=file_size or duration,
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

    list_item.addStreamInfo('video', stream_info)
    if item.get('movie_audiocodec'):
        list_item.addStreamInfo('audio', {
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
        list_item.setInfo('video', {'plot': ' | '.join(plot_parts)})

    art = {'icon': icons_path + 'sledujteto.jpg'}
    if thumb:
        art['poster'] = thumb
        art['thumb'] = thumb
    list_item.setArt(art)
    list_item.setProperty('IsPlayable', 'true')
    return list_item


def _fetch_search_api(query: str, skip_nsfw: bool) -> Tuple[List[xbmcgui.ListItem], int]:
    session = get_session()
    items: List[xbmcgui.ListItem] = []
    page = 1
    page_count = 1
    max_items = int(g_max_searched_vids)

    while page <= page_count and len(items) < max_items:
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
        for file_item in files:
            if skip_nsfw and file_item.get('is_nsfw'):
                continue
            list_item = _file_json_to_listitem(file_item)
            if list_item is not None:
                items.append(list_item)
            if len(items) >= max_items:
                break
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
    duration = _badge_text(card, 'bi-clock')
    resolution = _badge_text(card, 'bi-display')

    label_parts = []
    if resolution:
        label_parts.append(f'[{resolution}]')
    label_parts.append(title)
    if duration:
        label_parts.append(duration)

    list_item = xbmcgui.ListItem(
        label=' | '.join(label_parts),
        label2=duration or resolution,
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

    list_item.addStreamInfo('video', stream_info)
    thumb = _extract_thumbnail(card)
    art = {'icon': icons_path + 'sledujteto.jpg'}
    if thumb:
        art['poster'] = thumb
        art['thumb'] = thumb
    list_item.setArt(art)
    list_item.setProperty('IsPlayable', 'true')
    return list_item


def parse_search_html(html: bytes) -> List[xbmcgui.ListItem]:
    soup = BeautifulSoup(html, 'html.parser')
    items: List[xbmcgui.ListItem] = []
    for card in soup.select('article.file-card'):
        item = _parse_file_card(card)
        if item is not None:
            items.append(item)
    return items


def _fetch_search_html(query: str) -> List[xbmcgui.ListItem]:
    session = get_session()
    url = f'{SLEDUJTETO_BASE}/vyhledat/?search={quote(query)}'
    dprint(f'sledujteto search(): HTML fallback GET {url}')
    res = session.get(url, headers=get_headers(), timeout=SEARCH_TIMEOUT)
    res.raise_for_status()
    from providers.browsing_context import remember_provider_page
    remember_provider_page(res.url)
    return parse_search_html(res.content)


def fetch_search(query: str, skip_nsfw: bool = False) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
    try:
        items, pages_loaded = _fetch_search_api(query, skip_nsfw)
        if items:
            dprint(f'sledujteto search(): API found {len(items)} items')
            return items, SearchMeta(pages_scraped=pages_loaded, cancelled=False, is_complete=True)
    except Exception as exc:
        dprint(f'sledujteto search(): API failed, trying HTML: {exc}')

    items = _fetch_search_html(query)
    dprint(f'sledujteto search(): HTML found {len(items)} items')
    max_items = int(g_max_searched_vids)
    if len(items) > max_items:
        items = items[:max_items]
    return items, SearchMeta(pages_scraped=1, cancelled=False, is_complete=True)
