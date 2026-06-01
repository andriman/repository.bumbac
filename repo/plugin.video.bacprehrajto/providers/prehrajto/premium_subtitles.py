from typing import List, Optional
from urllib.parse import urlparse

import requests
from requests.cookies import RequestsCookieJar

from common import get_headers, get_prehrajto_base, normalize_prehrajto_url
from model.SubData import SubData
from providers.prehrajto.download import _has_cookies
from providers.prehrajto.get_stream_data import merge_subtitle_lists, parse_all_subtitles_from_html
from providers.prehrajto.session import get_session
from utils.utils import dprint


def _is_html_response(res: requests.Response, body: bytes) -> bool:
    content_type = (res.headers.get('Content-Type') or '').lower()
    if 'text/html' in content_type:
        return True
    return b'var tracks' in body


def fetch_subtitles_from_premium_link(
        page_url: str,
        cookies: Optional[RequestsCookieJar] = None,
        page_content: Optional[bytes] = None,
) -> List[SubData]:
    """
    Collect all caption tracks: authenticated watch page (fresh GET), optional
    ?do=download HTML, then the page HTML already fetched for playback.
    """
    if not _has_cookies(cookies):
        return []

    canonical = get_prehrajto_base() + urlparse(normalize_prehrajto_url(page_url)).path
    collected: List[List[SubData]] = []
    session = get_session()

    try:
        res = session.get(
            canonical,
            cookies=cookies,
            headers=get_headers(),
            allow_redirects=True,
            timeout=20,
        )
        res.raise_for_status()
        subs = parse_all_subtitles_from_html(res.content)
        if subs:
            dprint(f'fetch_subtitles_from_premium_link(): {len(subs)} track(s) from fresh watch page')
            collected.append(subs)
    except requests.RequestException as exc:
        dprint(f'fetch_subtitles_from_premium_link(): watch page GET failed: {exc}')

    try:
        res = session.get(
            canonical + '?do=download',
            cookies=cookies,
            headers=get_headers(),
            allow_redirects=False,
            timeout=20,
        )
        body = res.content or b''
        if _is_html_response(res, body):
            subs = parse_all_subtitles_from_html(body)
            if subs:
                dprint(f'fetch_subtitles_from_premium_link(): {len(subs)} track(s) from download HTML')
                collected.append(subs)
    except requests.RequestException as exc:
        dprint(f'fetch_subtitles_from_premium_link(): download GET failed: {exc}')

    if page_content:
        subs = parse_all_subtitles_from_html(page_content)
        if subs:
            collected.append(subs)

    merged = merge_subtitle_lists(*collected)
    if not merged:
        dprint('fetch_subtitles_from_premium_link(): no tracks found')
    return merged
