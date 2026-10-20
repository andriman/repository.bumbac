from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import get_headers, get_prehrajto_base, normalize_prehrajto_url
from providers.prehrajto.auth import refresh_premium_from_html
from providers.browsing_context import remember_provider_page
from providers.prehrajto.session import get_session
from utils.StrUtils import crop_time
from utils.utils import dprint

LISTING_PLAYED = 'played'
LISTING_LIKED = 'liked'
LISTING_UPLOADED = 'uploaded'
LISTING_FAVORITES = 'favorites'

LISTING_LABELS = {
    LISTING_PLAYED: 'Přehraná videa',
    LISTING_LIKED: 'Videa, co se mi líbila',
    LISTING_UPLOADED: 'Nahraná videa',
    LISTING_FAVORITES: 'Oblíbená videa',
}

_LISTING_START_PATHS = {
    LISTING_PLAYED: '/profil/prehrana-videa',
    LISTING_LIKED: '/videa-co-se-mi-libila',
    LISTING_UPLOADED: '/profil/nahrana-videa',
    LISTING_FAVORITES: '/oblibena-videa',
}

REQUEST_TIMEOUT = 30


@dataclass
class AccountListingPage:
    items: List[dict]
    next_page_url: Optional[str]


def _site_base() -> str:
    return get_prehrajto_base().rstrip('/')


def _resolve_url(path_or_url: str, base: Optional[str] = None) -> str:
    base = (base or _site_base()).rstrip('/')
    path_or_url = (path_or_url or '').strip()
    if not path_or_url:
        return base
    if path_or_url.startswith('http://') or path_or_url.startswith('https://'):
        return path_or_url
    if not path_or_url.startswith('/'):
        path_or_url = '/' + path_or_url
    return base + path_or_url


def _fetch_html(url: str, allow_redirects: bool = True) -> bytes:
    session = get_session()
    res = session.get(
        url,
        headers=get_headers(),
        timeout=REQUEST_TIMEOUT,
        allow_redirects=allow_redirects,
    )
    res.raise_for_status()
    remember_provider_page(res.url)
    refresh_premium_from_html(res.content)
    return res.content


def _parse_video_grid(soup: BeautifulSoup, site_base: str) -> List[dict]:
    items: List[dict] = []
    listing = soup.select_one('#snippet-videoViewedListing-videoListingWrapper') or soup.select_one('.video-listing')
    if listing is None:
        wrappers = soup.select('.video-wrapper')
    else:
        wrappers = listing.select('.video-wrapper')

    for wrapper in wrappers:
        link_tag = wrapper.select_one('a.video.video--link')
        if link_tag is None:
            continue
        href = (link_tag.get('href') or '').strip()
        if not href:
            continue
        title = (link_tag.get('title') or '').strip()
        if not title:
            title_el = wrapper.select_one('h3.video__title')
            if title_el is not None:
                title = title_el.get_text(strip=True)
        if not title:
            continue

        duration = ''
        time_tag = wrapper.select_one('.video__tag--time')
        if time_tag is not None:
            duration = crop_time(time_tag.get_text(strip=True))

        size = ''
        size_tag = wrapper.select_one('.video__tag--size') or wrapper.select_one('.video__tag--size-alone')
        if size_tag is not None:
            size = size_tag.get_text(strip=True)

        thumb = ''
        thumb_img = wrapper.select_one('img.thumb1') or wrapper.select_one('.video-item-thumb img[src]')
        if thumb_img is not None:
            thumb = (thumb_img.get('src') or thumb_img.get('data-src') or '').strip()
            if thumb and not thumb.startswith('http'):
                thumb = urljoin(site_base + '/', thumb.lstrip('/'))

        page_url = normalize_prehrajto_url(site_base + href, base=site_base)
        items.append({
            'link': page_url,
            'title': title,
            'duration': duration,
            'size': size,
            'thumb': thumb,
        })
    return items


def _parse_uploaded_videos(soup: BeautifulSoup, site_base: str) -> List[dict]:
    items: List[dict] = []
    for block in soup.select('[id^="snippet-uploadedVideoListing-video-"]'):
        block_id = block.get('id') or ''
        if not block_id.startswith('snippet-uploadedVideoListing-video-'):
            continue

        title = ''
        name_el = block.select_one('h3.title') or block.select_one('[id^="snippet-uploadedVideoListing-videoName-"]')
        if name_el is not None:
            title = name_el.get_text(strip=True)
        if not title:
            continue

        detail_link = None
        for info_ul in block.select('ul.file__info'):
            for a in info_ul.select('a[href]'):
                if 'Detail souboru' in (a.get_text() or ''):
                    detail_link = a
                    break
            if detail_link is not None:
                break
        if detail_link is None:
            continue
        href = (detail_link.get('href') or '').strip()
        if not href:
            continue

        size = ''
        size_el = block.select_one('.size strong')
        if size_el is not None:
            size = size_el.get_text(strip=True)
        if not size:
            for p in block.select('p.text-medium'):
                text = p.get_text(strip=True)
                if text and ('GB' in text or 'MB' in text or 'KB' in text):
                    size = text
                    break

        thumb = ''
        thumb_img = block.select_one('div.file__thumb img[src]')
        if thumb_img is not None:
            thumb = (thumb_img.get('src') or '').strip()
            if thumb and not thumb.startswith('http'):
                thumb = urljoin(site_base + '/', thumb.lstrip('/'))

        page_url = normalize_prehrajto_url(site_base + href, base=site_base)
        items.append({
            'link': page_url,
            'title': title,
            'duration': '',
            'size': size,
            'thumb': thumb,
        })
    return items


def _find_next_page_url(soup: BeautifulSoup, current_url: str, site_base: str) -> Optional[str]:
    paginator = soup.select_one('#snippet-videoViewedListing-paginatorWrapper')
    if paginator is None:
        paginator = soup
    next_a = paginator.select_one('a[rel="next"][href]')
    if next_a is None:
        for a in paginator.select('a.pagination-item[href]'):
            if 'page=' in (a.get('href') or ''):
                next_a = a
                break
    if next_a is None:
        return None
    href = (next_a.get('href') or '').strip()
    if not href:
        return None
    next_url = _resolve_url(href, site_base)
    if next_url == current_url:
        return None
    return next_url


def _resolve_start_url(kind: str) -> str:
    if kind == LISTING_FAVORITES:
        return _resolve_favorites_url()
    return _LISTING_START_PATHS[kind]


def _fetch_grid_page(url: str, progress=None, listing_label: str = '') -> AccountListingPage:
    site_base = _site_base()
    url = _resolve_url(url, site_base)
    if progress is not None:
        try:
            progress.update(50, listing_label or 'Načítání', '', '')
        except TypeError:
            progress.update(50, listing_label or 'Načítání')

    dprint(f'prehrajto account listing: GET {url}')
    html = _fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')
    items = _parse_video_grid(soup, site_base)
    next_url = _find_next_page_url(soup, url, site_base)
    return AccountListingPage(items=items, next_page_url=next_url)


def _fetch_uploaded_page(start_url: str, progress=None) -> AccountListingPage:
    site_base = _site_base()
    url = _resolve_url(start_url, site_base)
    if progress is not None:
        try:
            progress.update(50, LISTING_UPLOADED, 'Načítání', '')
        except TypeError:
            progress.update(50, 'Načítání nahraných videí')
    dprint(f'prehrajto account uploaded: GET {url}')
    html = _fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')
    items = _parse_uploaded_videos(soup, site_base)
    return AccountListingPage(items=items, next_page_url=None)


def _resolve_favorites_url() -> str:
    site_base = _site_base()
    start = site_base + _LISTING_START_PATHS[LISTING_FAVORITES]
    session = get_session()
    res = session.get(
        start,
        headers=get_headers(),
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    )
    res.raise_for_status()
    remember_provider_page(res.url)
    return res.url


def fetch_listing_page(
        kind: str,
        page_url: Optional[str] = None,
        progress=None,
) -> AccountListingPage:
    if kind not in _LISTING_START_PATHS:
        raise ValueError(f'Unknown listing kind: {kind}')

    label = LISTING_LABELS.get(kind, 'Načítání')

    if kind == LISTING_UPLOADED:
        url = page_url or _LISTING_START_PATHS[kind]
        return _fetch_uploaded_page(url, progress=progress)

    url = page_url or _resolve_start_url(kind)
    return _fetch_grid_page(url, progress=progress, listing_label=label)
