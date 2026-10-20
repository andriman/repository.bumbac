import os
import re
from typing import List, Tuple
from urllib.parse import urlparse

import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc
import xbmcvfs

from model.QS import QS
from utils.user_agent_presets import DEFAULT_USER_AGENT, resolve_user_agent

_ADDON_ID = 'plugin.video.bacprehrajto'
addon = xbmcaddon.Addon(id=_ADDON_ID)
_ADDON_NAME = 'Přehraj.to'
SLEDUJTETO_BASE = 'https://www.sledujteto.cz'

_PREHRAJTO_DOMAIN_LABELS = ('prehrajto.cz', 'prehraj.to')
_PREHRAJTO_DOMAIN_DEFAULT = 'prehrajto.cz'
_prehrajto_base_cache: str = ''
_prehrajto_domain_setting_cache: str = ''


def _resolve_prehrajto_domain_host(raw: str) -> str:
    if str(raw).strip().isdigit():
        idx = int(str(raw).strip())
        if 0 <= idx < len(_PREHRAJTO_DOMAIN_LABELS):
            return _PREHRAJTO_DOMAIN_LABELS[idx]
    host = str(raw).strip()
    if host in _PREHRAJTO_DOMAIN_LABELS:
        return host
    return _PREHRAJTO_DOMAIN_DEFAULT


def refresh_prehrajto_base_cache() -> None:
    """Clear cached base URL so the next get_prehrajto_base() reads settings again."""
    global _prehrajto_base_cache, _prehrajto_domain_setting_cache
    _prehrajto_base_cache = ''
    _prehrajto_domain_setting_cache = ''


def get_prehrajto_base() -> str:
    global _prehrajto_base_cache, _prehrajto_domain_setting_cache
    raw = addon.getSetting('prehrajto_domain') or ''
    if _prehrajto_base_cache and raw == _prehrajto_domain_setting_cache:
        return _prehrajto_base_cache
    _prehrajto_domain_setting_cache = raw
    _prehrajto_base_cache = 'https://' + _resolve_prehrajto_domain_host(raw)
    return _prehrajto_base_cache


def normalize_prehrajto_url(url: str, base: str = None) -> str:
    """Map any Prehraj host to the domain selected in settings."""
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.netloc or '').lower()
    if 'prehrajto.cz' not in host and 'prehraj.to' not in host:
        if url.startswith('/'):
            base_url = base if base is not None else get_prehrajto_base()
            return base_url + url
        return url
    base_url = base if base is not None else get_prehrajto_base()
    path = parsed.path or '/'
    query = ('?' + parsed.query) if parsed.query else ''
    fragment = ('#' + parsed.fragment) if parsed.fragment else ''
    return base_url + path + query + fragment


# Deprecated alias — use get_prehrajto_base() for runtime domain from settings.
PREHRAJTO_BASE = get_prehrajto_base()

_HELLSPY_DOMAIN_DEFAULT = 'www.hellspy.to'
_hellspy_base_cache = ''
_hellspy_domain_setting_cache = ''


def normalize_hellspy_host(raw: str) -> str:
    text = str(raw or '').strip()
    if not text:
        return _HELLSPY_DOMAIN_DEFAULT
    if '://' not in text:
        text = 'https://' + text
    host = (urlparse(text).netloc or '').strip().lower()
    if host.startswith('[') and ']' in host:
        host = host[:host.find(']') + 1]
    if not host or '.' not in host:
        return _HELLSPY_DOMAIN_DEFAULT
    return host


def hellspy_api_host(page_host: str) -> str:
    host = normalize_hellspy_host(page_host)
    apex = host[4:] if host.startswith('www.') else host
    if apex.startswith('api.'):
        return apex
    return 'api.' + apex


def get_hellspy_base() -> str:
    global _hellspy_base_cache, _hellspy_domain_setting_cache
    raw = addon.getSetting('hellspy_domain') or ''
    if _hellspy_base_cache and raw == _hellspy_domain_setting_cache:
        return _hellspy_base_cache
    _hellspy_domain_setting_cache = raw
    _hellspy_base_cache = 'https://' + normalize_hellspy_host(raw)
    return _hellspy_base_cache


def get_hellspy_api_base() -> str:
    return 'https://' + hellspy_api_host(urlparse(get_hellspy_base()).netloc)

DEFAULT_UA = DEFAULT_USER_AGENT


def _int_setting(key: str, default: int) -> int:
    raw = addon.getSetting(key)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _setting_nonempty(key: str) -> bool:
    raw = addon.getSetting(key)
    return raw is not None and str(raw).strip() != ''


def _migrate_provider_search_settings() -> None:
    """Copy legacy global ls / search_max_pages into per-provider keys once."""
    legacy_ls = addon.getSetting('ls')
    if legacy_ls and str(legacy_ls).strip():
        if not _setting_nonempty('prehrajto_ls'):
            addon.setSetting('prehrajto_ls', legacy_ls)
        if not _setting_nonempty('sledujteto_ls'):
            addon.setSetting('sledujteto_ls', legacy_ls)
        if not _setting_nonempty('hellspy_ls'):
            addon.setSetting('hellspy_ls', legacy_ls)
    legacy_pages = addon.getSetting('search_max_pages')
    if legacy_pages and str(legacy_pages).strip():
        if not _setting_nonempty('prehrajto_search_max_pages'):
            addon.setSetting('prehrajto_search_max_pages', legacy_pages)
        if not _setting_nonempty('sledujteto_search_max_pages'):
            addon.setSetting('sledujteto_search_max_pages', legacy_pages)
        if not _setting_nonempty('hellspy_search_max_pages'):
            addon.setSetting('hellspy_search_max_pages', legacy_pages)


_migrate_provider_search_settings()


def _apply_search_limit_defaults() -> None:
    """Move installs that still have the previous defaults (50 videos, 20 pages)."""
    if addon.getSetting('search_defaults_applied') == '20_3':
        return
    for key in ('prehrajto_ls', 'sledujteto_ls', 'hellspy_ls', 'ls'):
        if addon.getSetting(key) == '50':
            addon.setSetting(key, '20')
    for key in (
            'prehrajto_search_max_pages',
            'sledujteto_search_max_pages',
            'hellspy_search_max_pages',
            'search_max_pages',
    ):
        if addon.getSetting(key) == '20':
            addon.setSetting(key, '3')
    addon.setSetting('search_defaults_applied', '20_3')


_apply_search_limit_defaults()

_LEGACY_LS_DEFAULT = 20
_LEGACY_SEARCH_MAX_PAGES_DEFAULT = 3


### SETTINGS
g_is_debug_logs_enabled = True if addon.getSetting("is_debug_logs_enabled") == 'true' else False
g_is_debug_info_on = True if addon.getSetting("is_debug_info_on") == 'true' else False
g_prehrajto_max_searched_vids = _int_setting('prehrajto_ls', _LEGACY_LS_DEFAULT)
g_sledujteto_max_searched_vids = _int_setting('sledujteto_ls', _LEGACY_LS_DEFAULT)
g_hellspy_max_searched_vids = _int_setting('hellspy_ls', _LEGACY_LS_DEFAULT)
g_prehrajto_search_max_pages = max(1, _int_setting('prehrajto_search_max_pages', _LEGACY_SEARCH_MAX_PAGES_DEFAULT))
g_sledujteto_search_max_pages = max(1, _int_setting('sledujteto_search_max_pages', _LEGACY_SEARCH_MAX_PAGES_DEFAULT))
g_hellspy_search_max_pages = max(1, _int_setting('hellspy_search_max_pages', _LEGACY_SEARCH_MAX_PAGES_DEFAULT))
g_max_duplicities = _int_setting("max_duplicities", 2)
g_truncate_titles = True if addon.getSetting("truncate_titles") == 'true' else False
g_highlight_fake_streams = True if addon.getSetting("highlight_fake_streams") == 'true' else False
g_download_path = addon.getSetting("download")
g_download_max_simultaneous = max(1, _int_setting("download_max_simultaneous", 1))
g_prehrajto_allow_parallel_downloads = addon.getSetting("prehrajto_allow_parallel_downloads") == 'true'
g_prehrajto_premium_subtitles = addon.getSetting("prehrajto_premium_subtitles") == 'true'
g_prehrajto_premium_subs_if_none = addon.getSetting("prehrajto_premium_subs_if_none") == 'true'
g_sledujteto_allow_parallel_downloads = addon.getSetting("sledujteto_allow_parallel_downloads") == 'true'
g_hellspy_allow_parallel_downloads = addon.getSetting("hellspy_allow_parallel_downloads") == 'true'
g_unpack_context_menu = addon.getSetting("unpack_context_menu") == 'true'
g_search_cache_ttl_seconds = max(0, _int_setting("search_cache_ttl", 5)) * 60


def is_search_cache_enabled() -> bool:
    return addon.getSetting('search_cache_enabled') != 'false'
g_search_page_delay_seconds = max(0, _int_setting("search_page_delay", 3))

g_is_prehrajto_enabled = True if addon.getSetting("is_provider_prehrajto_enabled") == 'true' else False
g_is_sledujteto_enabled = True if addon.getSetting("is_provider_sledujteto_enabled") == 'true' else False
g_is_hellspy_enabled = addon.getSetting("is_provider_hellspy_enabled") != 'false'
g_all_sources_disabled = not (g_is_prehrajto_enabled or g_is_sledujteto_enabled or g_is_hellspy_enabled)

SEARCH_SOURCE_NO_RESULTS_PROP = 'SourceNoResults'
COLOR_LIST_MUTED = 'FF909090'

PROVIDER_ORDER_DEFAULT = ('prehrajto', 'hellspy', 'sledujteto')
PROVIDER_ORDER_LABELS = {
    'prehrajto': 'Prehraj.to',
    'sledujteto': 'Sledujteto.cz',
    'hellspy': 'HellSpy',
}
_PROVIDER_ORDER_INFO_DEFAULT = '1. Prehraj.to, 2. HellSpy, 3. Sledujteto.cz'
_PROVIDER_ORDER_PREVIOUS_DEFAULT = 'prehrajto,sledujteto,hellspy'


def display_provider_headers() -> bool:
    return addon.getSetting('display_provider_headers') != 'false'


def short_provider_names() -> bool:
    return addon.getSetting('short_provider_names') != 'false'


def get_provider_order() -> List[str]:
    raw = addon.getSetting('provider_order') or ''
    order = []
    for part in raw.split(','):
        provider_id = part.strip()
        if provider_id in PROVIDER_ORDER_LABELS and provider_id not in order:
            order.append(provider_id)
    for provider_id in PROVIDER_ORDER_DEFAULT:
        if provider_id not in order:
            order.append(provider_id)
    return order


def format_provider_order_label(order: List[str] = None) -> str:
    chosen = order if order is not None else get_provider_order()
    if not chosen:
        return _PROVIDER_ORDER_INFO_DEFAULT
    return ', '.join(
        f'{index}. {PROVIDER_ORDER_LABELS[provider_id]}'
        for index, provider_id in enumerate(chosen, 1)
    )


def move_provider(provider_id: str, direction: int) -> Tuple[List[str], bool, str]:
    """Move a provider earlier (direction -1) or later (direction +1).

    The first provider moved up wraps to the end. The last provider moved down wraps to the start.
    """
    order = get_provider_order()
    if provider_id not in PROVIDER_ORDER_LABELS or provider_id not in order:
        return order, False, 'Neznámý zdroj'
    if direction == 0 or len(order) < 2:
        info = format_provider_order_label(order)
        return order, False, info
    index = order.index(provider_id)
    order.pop(index)
    if direction < 0 and index == 0:
        order.append(provider_id)
    elif direction > 0 and index == len(order):
        order.insert(0, provider_id)
    else:
        order.insert(index + direction, provider_id)
    addon.setSetting('provider_order', ','.join(order))
    info = format_provider_order_label(order)
    addon.setSetting('provider_order_info', info)
    return order, True, info


def _apply_provider_order_default() -> None:
    if addon.getSetting('provider_order_default_applied') == 'phs':
        return
    current = (addon.getSetting('provider_order') or '').strip()
    if not current or current == _PROVIDER_ORDER_PREVIOUS_DEFAULT:
        order = list(PROVIDER_ORDER_DEFAULT)
        addon.setSetting('provider_order', ','.join(order))
        addon.setSetting('provider_order_info', format_provider_order_label(order))
    addon.setSetting('provider_order_default_applied', 'phs')


_apply_provider_order_default()

_PREHRAJTO_ACCOUNT_LISTING_SETTINGS = {
    'played': 'prehrajto_account_show_played',
    'liked': 'prehrajto_account_show_liked',
    'uploaded': 'prehrajto_account_show_uploaded',
    'favorites': 'prehrajto_account_show_favorites',
}


def is_prehrajto_account_listing_enabled(kind: str) -> bool:
    setting_id = _PREHRAJTO_ACCOUNT_LISTING_SETTINGS.get(kind)
    if not setting_id:
        return False
    return addon.getSetting(setting_id) != 'false'


def is_prehrajto_account_name_visible() -> bool:
    return addon.getSetting('prehrajto_account_show_name') == 'true'


def is_sledujteto_account_name_visible() -> bool:
    return addon.getSetting('sledujteto_account_show_name') == 'true'


def is_sledujteto_my_videos_enabled() -> bool:
    return addon.getSetting('sledujteto_account_show_my_videos') != 'false'


def is_sledujteto_watchlist_enabled() -> bool:
    return addon.getSetting('sledujteto_account_show_watchlist') != 'false'


def is_hellspy_account_name_visible() -> bool:
    return addon.getSetting('hellspy_account_show_name') == 'true'


def is_hellspy_my_videos_enabled() -> bool:
    return addon.getSetting('hellspy_account_show_my_videos') != 'false'


DEVELOPER_PASSWORD = 'bumbacpass'


def is_developer_mode() -> bool:
    return addon.getSetting('developer_password') == DEVELOPER_PASSWORD


def is_csfd_menu_enabled() -> bool:
    return is_developer_mode() and addon.getSetting('is_csfd_enabled') == 'true'


g_is_nsfw_enabled = (
    is_developer_mode() and addon.getSetting('is_nsfw_enabled') == 'true'
)

qss = addon.getSetting('quality_selector') or ''
_QUALITY_SELECTOR_LABELS = ('Komprimovaná', 'Max', 'Vybrat')
if str(qss).strip().isdigit():
    _qss_idx = int(str(qss).strip())
    qss = _QUALITY_SELECTOR_LABELS[_qss_idx] if 0 <= _qss_idx < len(_QUALITY_SELECTOR_LABELS) else ''
else:
    qss = str(qss).strip()

g_quality_selector: QS = QS.BestCompressed
if qss == 'Max':
    g_quality_selector = QS.Max
elif qss == 'Komprimovaná':
    g_quality_selector = QS.BestCompressed
elif qss == 'Vybrat':
    g_quality_selector = QS.Selector

### PATHs
translated_path = xbmcvfs.translatePath('special://home/addons/' + _ADDON_ID)
_legacy_history_path = os.path.join(translated_path, 'resources', 'history.txt')
_profile_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
if not os.path.exists(_profile_path):
    os.makedirs(_profile_path)
history_path = os.path.join(_profile_path, 'search_history.txt')
if os.path.exists(_legacy_history_path) and not os.path.exists(history_path):
    try:
        with open(_legacy_history_path, 'r', encoding='utf-8') as src:
            legacy = src.read()
        if legacy.strip():
            with open(history_path, 'w', encoding='utf-8') as dst:
                dst.write(legacy if legacy.endswith('\n') else legacy + '\n')
    except OSError:
        pass
images_path = os.path.join(translated_path,'resources', 'images/')
quality_icons_path = os.path.join(translated_path,'resources', 'images/quality/')
icons_path = os.path.join(translated_path,'resources', 'icons/')
qr_path = os.path.join(translated_path,'resources', 'qr.png')

ICON_DOWNLOAD = 'download.png'
ICON_BIN_DELETE = 'bin-delete.png'
ICON_REFRESH = 'refresh.png'
ICON_COPY = 'copy.png'
ICON_QR = 'qr-code.png'


def action_icon(filename: str) -> str:
    return xbmcvfs.translatePath(
        f'special://home/addons/{_ADDON_ID}/resources/icons/{filename}'
    )


def apply_action_icon(list_item, filename: str) -> None:
    icon = action_icon(filename)
    list_item.setArt({'icon': icon})


def set_list_icon(list_item, filename: str) -> None:
    apply_action_icon(list_item, filename)

def get_user_agent() -> str:
    return resolve_user_agent(xbmcaddon.Addon(id=_ADDON_ID))


def get_headers(extra=None) -> dict:
    h = {'User-Agent': get_user_agent()}
    if extra:
        h.update(extra)
    return h

def is_prehrajto_auto_login_enabled() -> bool:
    return addon.getSetting('prehrajto_auto_login') != 'false'


def set_prehrajto_auto_login_enabled(enabled: bool) -> None:
    addon.setSetting('prehrajto_auto_login', 'true' if enabled else 'false')


def is_prehrajto_premium_subtitles_enabled() -> bool:
    return addon.getSetting('prehrajto_premium_subtitles') == 'true'


def is_prehrajto_premium_subs_if_none_enabled() -> bool:
    """Child setting is only meaningful when premium subtitles master toggle is on."""
    return (
        is_prehrajto_premium_subtitles_enabled()
        and addon.getSetting('prehrajto_premium_subs_if_none') == 'true'
    )


def is_sledujteto_auto_login_enabled() -> bool:
    return addon.getSetting('sledujteto_auto_login') != 'false'


def set_sledujteto_auto_login_enabled(enabled: bool) -> None:
    addon.setSetting('sledujteto_auto_login', 'true' if enabled else 'false')


def is_hellspy_auto_login_enabled() -> bool:
    return addon.getSetting('hellspy_auto_login') != 'false'


def set_hellspy_auto_login_enabled(enabled: bool) -> None:
    addon.setSetting('hellspy_auto_login', 'true' if enabled else 'false')

_BASE_NSFW = [
    'rychly prachy', 'rychlý prachy', 'rychlýprachy', 'rychlyprachy',
    'porno', 'sex', 'porn', 'nymfomanka', 'nymphomaniac',
    'xxx', 'milf', 'hentai', 'onlyfans',
    'erotik', 'erotika', 'erotic',
    'bdsm', 'fetiš', 'fetish', 'orgasmus', 'orgasm',
    'blowjob', 'handjob', 'deepthroat', 'gangbang', 'creampie',
    'camgirl', 'striptease',
    'brazzers', 'bangbros', 'czechcasting', 'czechstreets', 'fakehub', 'teamskeet',
    'šuk', 'mrdat', 'mrdá', 'kokot', 'čurák', 'curak', 'xxxfile'
]


def _normalize_nsfw_text(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip()).lower()


def _split_nsfw_setting(setting_id: str) -> list:
    words = []
    raw = addon.getSetting(setting_id) or ''
    for part in raw.split(','):
        word = _normalize_nsfw_text(part)
        if word and word not in words:
            words.append(word)
    return words


def _build_nsfw_keywords() -> list:
    keywords = [_normalize_nsfw_text(word) for word in _BASE_NSFW]
    for word in _split_nsfw_setting('nsfw_filter_keywords'):
        if word not in keywords:
            keywords.append(word)
    return keywords


def _nsfw_exceptions() -> list:
    return _split_nsfw_setting('nsfw_filter_exceptions')


g_NSFW = _build_nsfw_keywords()


def is_possible_nsfw(query: str, nsfw_keywords=None, nsfw_exceptions=None) -> bool:
    if nsfw_keywords is None:
        nsfw_keywords = _build_nsfw_keywords()
    if nsfw_exceptions is None:
        nsfw_exceptions = _nsfw_exceptions()

    haystack = _normalize_nsfw_text(query)
    if not haystack:
        return False

    matched = []
    for word in nsfw_keywords:
        needle = _normalize_nsfw_text(word)
        if needle and needle in haystack and needle not in matched:
            matched.append(needle)
    if not matched:
        return False

    active_exceptions = [
        exception for exception in nsfw_exceptions
        if exception and exception in haystack
    ]
    for needle in matched:
        if not any(needle in exception for exception in active_exceptions):
            return True
    return False


def go_to_main_menu() -> None:
    xbmc.executebuiltin(f'RunPlugin(plugin://{_ADDON_ID}/)')