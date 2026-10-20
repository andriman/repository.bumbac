"""Remember last browsed site pages for Referer-aware logout and similar flows."""
from typing import Optional
from urllib.parse import urlparse

from common import SLEDUJTETO_BASE, get_hellspy_base, get_prehrajto_base, normalize_prehrajto_url

_last_prehrajto_page: Optional[str] = None
_last_sledujteto_page: Optional[str] = None
_last_hellspy_page: Optional[str] = None

_MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.webm', '.m3u8', '.mpd', '.ism', '.avi', '.flv')
_MEDIA_HOST_HINTS = ('premiumcdn', 'cloudfront', 'akamaized', 'googlevideo')


def _is_direct_stream_url(url: str) -> bool:
    lower = url.lower()
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in _MEDIA_EXTENSIONS):
        return True
    if any(hint in lower for hint in _MEDIA_HOST_HINTS):
        return True
    return False


def is_prehrajto_site_page(url: str) -> bool:
    if not url or _is_direct_stream_url(url):
        return False
    host = urlparse(url).netloc.lower()
    return 'prehrajto.cz' in host or 'prehraj.to' in host


def is_sledujteto_site_page(url: str) -> bool:
    if not url or _is_direct_stream_url(url):
        return False
    host = urlparse(url).netloc.lower()
    return 'sledujteto.cz' in host


def is_hellspy_site_page(url: str) -> bool:
    if not url or _is_direct_stream_url(url):
        return False
    host = urlparse(url).netloc.lower()
    return 'hellspy.' in host and not host.startswith('api.')


def remember_provider_page(url: str) -> None:
    global _last_prehrajto_page, _last_sledujteto_page, _last_hellspy_page
    if not url:
        return
    if is_hellspy_site_page(url):
        _last_hellspy_page = url
        return
    if is_sledujteto_site_page(url):
        _last_sledujteto_page = url
        return
    if is_prehrajto_site_page(url):
        _last_prehrajto_page = normalize_prehrajto_url(url)


def get_prehrajto_logout_referer() -> str:
    if _last_prehrajto_page:
        return _last_prehrajto_page
    return get_prehrajto_base() + '/'


def get_sledujteto_logout_referer() -> str:
    if _last_sledujteto_page:
        return _last_sledujteto_page
    return SLEDUJTETO_BASE + '/'


def clear_prehrajto_browsing_context() -> None:
    global _last_prehrajto_page
    _last_prehrajto_page = None


def clear_sledujteto_browsing_context() -> None:
    global _last_sledujteto_page
    _last_sledujteto_page = None


def get_hellspy_referer() -> str:
    if _last_hellspy_page:
        return _last_hellspy_page
    return get_hellspy_base() + '/'


def clear_hellspy_browsing_context() -> None:
    global _last_hellspy_page
    _last_hellspy_page = None


def clear_all_browsing_context() -> None:
    clear_prehrajto_browsing_context()
    clear_sledujteto_browsing_context()
    clear_hellspy_browsing_context()
