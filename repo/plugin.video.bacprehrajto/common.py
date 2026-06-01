import os
import re
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


def _prehrajto_domain_host() -> str:
    raw = addon.getSetting('prehrajto_domain') or ''
    if str(raw).strip().isdigit():
        idx = int(str(raw).strip())
        if 0 <= idx < len(_PREHRAJTO_DOMAIN_LABELS):
            return _PREHRAJTO_DOMAIN_LABELS[idx]
    host = str(raw).strip()
    if host in _PREHRAJTO_DOMAIN_LABELS:
        return host
    return _PREHRAJTO_DOMAIN_DEFAULT


def get_prehrajto_base() -> str:
    return 'https://' + _prehrajto_domain_host()


def normalize_prehrajto_url(url: str) -> str:
    """Map any Prehraj host to the domain selected in settings."""
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.netloc or '').lower()
    if 'prehrajto.cz' not in host and 'prehraj.to' not in host:
        return url
    base = get_prehrajto_base()
    path = parsed.path or '/'
    query = ('?' + parsed.query) if parsed.query else ''
    fragment = ('#' + parsed.fragment) if parsed.fragment else ''
    return base + path + query + fragment


# Deprecated alias — use get_prehrajto_base() for runtime domain from settings.
PREHRAJTO_BASE = get_prehrajto_base()

DEFAULT_UA = DEFAULT_USER_AGENT


def _int_setting(key: str, default: int) -> int:
    raw = addon.getSetting(key)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(raw)
    except ValueError:
        return default


### SETTINGS
g_is_debug_logs_enabled = True if addon.getSetting("is_debug_logs_enabled") == 'true' else False
g_is_debug_info_on = True if addon.getSetting("is_debug_info_on") == 'true' else False
g_max_searched_vids = _int_setting("ls", 50)
g_max_duplicities = _int_setting("max_duplicities", 2)
g_truncate_titles = True if addon.getSetting("truncate_titles") == 'true' else False
g_highlight_fake_streams = True if addon.getSetting("highlight_fake_streams") == 'true' else False
g_download_path = addon.getSetting("download")
g_download_max_simultaneous = max(1, _int_setting("download_max_simultaneous", 1))
g_prehrajto_allow_parallel_downloads = addon.getSetting("prehrajto_allow_parallel_downloads") == 'true'
g_prehrajto_premium_subtitles = addon.getSetting("prehrajto_premium_subtitles") == 'true'
g_prehrajto_premium_subs_if_none = addon.getSetting("prehrajto_premium_subs_if_none") == 'true'
g_sledujteto_allow_parallel_downloads = addon.getSetting("sledujteto_allow_parallel_downloads") == 'true'
g_unpack_context_menu = addon.getSetting("unpack_context_menu") == 'true'
g_search_cache_ttl_seconds = max(0, _int_setting("search_cache_ttl", 5)) * 60
g_search_page_delay_seconds = max(0, _int_setting("search_page_delay", 3))
g_search_max_pages = max(1, _int_setting("search_max_pages", 20))

g_is_prehrajto_enabled = True if addon.getSetting("is_provider_prehrajto_enabled") == 'true' else False
g_is_sledujteto_enabled = True if addon.getSetting("is_provider_sledujteto_enabled") == 'true' else False
g_all_sources_disabled = not (g_is_prehrajto_enabled or g_is_sledujteto_enabled)

DEVELOPER_PASSWORD = 'bumbacpass'


def is_developer_mode() -> bool:
    return addon.getSetting('developer_password') == DEVELOPER_PASSWORD


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
subtitles_path = os.path.join(translated_path,'resources', 'subtitles/')
images_path = os.path.join(translated_path,'resources', 'images/')
quality_icons_path = os.path.join(translated_path,'resources', 'images/quality/')
cache_path = os.path.join(translated_path,'resources', 'cache/')
SEARCH_DISK_CACHE_DIR = os.path.join(cache_path, 'search')
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

_BASE_NSFW = ['rychly prachy', 'rychlý prachy', 'rychlýprachy', 'rychlyprachy', 'porno', 'sex']

def _build_nsfw_keywords() -> list:
    keywords = list(_BASE_NSFW)
    extra = addon.getSetting('nsfw_filter_keywords') or ''
    for part in extra.split(','):
        word = part.strip().lower()
        if word and word not in keywords:
            keywords.append(word)
    return keywords


g_NSFW = _build_nsfw_keywords()


def is_possible_nsfw(query: str, nsfw_keywords=None) -> bool:
    if nsfw_keywords is None:
        nsfw_keywords = g_NSFW

    query = re.sub(r'\s+', ' ', query.strip())
    patterns = [
        r'\b' + r'\s*'.join(map(re.escape, word.split())) + r'\b'
        for word in nsfw_keywords
    ]
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in patterns)


def go_to_main_menu() -> None:
    xbmc.executebuiltin(f'RunPlugin(plugin://{_ADDON_ID}/)')