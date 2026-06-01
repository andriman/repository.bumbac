from typing import Optional
from urllib.parse import urlparse

import requests
from requests.cookies import RequestsCookieJar

from common import get_headers, get_prehrajto_base, get_user_agent, normalize_prehrajto_url
from model.StreamData import StreamData
from utils.utils import build_headers, dprint


def _has_cookies(cookies: Optional[RequestsCookieJar]) -> bool:
    if cookies is None:
        return False
    try:
        return len(cookies) > 0
    except TypeError:
        return bool(cookies)


def resolve_premium_download_url(
        page_url: str,
        cookies: Optional[RequestsCookieJar] = None,
        extra_headers: Optional[dict] = None,
) -> Optional[str]:
    """Resolve ?do=download redirect to final CDN URL (logged-in session required)."""
    if not _has_cookies(cookies):
        dprint('resolve_premium_download_url(): login cookies required')
        return None
    canonical = get_prehrajto_base() + urlparse(normalize_prehrajto_url(page_url)).path
    headers = get_headers()
    if extra_headers:
        headers.update(extra_headers)
    res_dl = requests.get(
        canonical + '?do=download',
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
    )
    loc = res_dl.headers.get('Location')
    if not loc:
        dprint('resolve_premium_download_url(): Location header missing for ' + canonical)
    return loc


def make_premium_stream(page_url: str) -> StreamData:
    canonical = get_prehrajto_base() + urlparse(normalize_prehrajto_url(page_url)).path
    download_link = canonical + '?do=download'
    return StreamData(
        label='Premium',
        label2='',
        path=download_link,
        headers=build_headers(get_user_agent(), canonical),
        is_premium=True,
        quality=9999,
    )


def ensure_premium_stream(streams, page_url: str, cookies) -> list:
    if any(s.is_premium for s in streams):
        return streams
    if not cookies:
        return streams
    premium = make_premium_stream(page_url)
    return [premium] + list(streams)
