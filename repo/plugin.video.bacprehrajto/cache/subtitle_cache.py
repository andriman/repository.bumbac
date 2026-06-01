import os
from typing import Tuple

import xbmc
import xbmcaddon
import xbmcvfs

from common import _ADDON_ID, addon
from utils.StrUtils import convert_size
from utils.user_agent_presets import refresh_user_agent_setting
from utils.utils import dprint

_SUBTITLE_CACHE_DIRNAME = 'subtitle_cache'
_SETTINGS_REFRESH_INTERVAL_S = 2


def get_subtitle_cache_dir() -> str:
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    cache_dir = os.path.join(profile, _SUBTITLE_CACHE_DIRNAME)
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_subtitle_cache_stats() -> Tuple[int, int]:
    """Return (file_count, total_bytes)."""
    cache_dir = get_subtitle_cache_dir()
    if not os.path.isdir(cache_dir):
        return 0, 0

    file_count = 0
    total_bytes = 0
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        if os.path.isfile(path):
            file_count += 1
            try:
                total_bytes += os.path.getsize(path)
            except OSError:
                pass
    return file_count, total_bytes


def format_subtitle_cache_size_label() -> str:
    file_count, total_bytes = get_subtitle_cache_stats()
    if file_count == 0:
        return '0 B (0 souborů)'
    size_str = convert_size(total_bytes, 1)
    if file_count == 1:
        files_word = '1 soubor'
    elif 2 <= file_count <= 4:
        files_word = f'{file_count} soubory'
    else:
        files_word = f'{file_count} souborů'
    return f'{size_str} ({files_word})'


def clear_subtitle_cache() -> Tuple[int, int]:
    """Delete cached subtitle files. Returns (files_removed, bytes_freed)."""
    cache_dir = get_subtitle_cache_dir()
    if not os.path.isdir(cache_dir):
        return 0, 0

    removed = 0
    freed = 0
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
            os.remove(path)
            removed += 1
            freed += size
        except OSError as exc:
            dprint(f'clear_subtitle_cache(): could not remove {path}: {exc}')
    return removed, freed


def refresh_subtitle_cache_setting() -> str:
    """Update the readonly settings field and return the label text."""
    label = format_subtitle_cache_size_label()
    try:
        current = addon.getSetting('subtitle_cache_size_info') or ''
        if current != label:
            addon.setSetting('subtitle_cache_size_info', label)
    except Exception as exc:
        dprint(f'refresh_subtitle_cache_setting(): {exc}')
    return label


def is_own_addon_settings_visible() -> bool:
    if not xbmc.getCondVisibility('Window.IsVisible(addonsettings)'):
        return False
    try:
        if xbmc.getCondVisibility(f'String.IsEqual(System.CurrentAddonSettings,{_ADDON_ID})'):
            return True
    except Exception:
        pass
    for infolabel in (
        'System.CurrentAddonSettings',
        'Window.Property(Addon.ID)',
    ):
        try:
            value = (xbmc.getInfoLabel(infolabel) or '').strip()
        except Exception:
            value = ''
        if value == _ADDON_ID:
            return True
    return False


class SubtitleCacheSettingsMonitor:
    """Refresh readonly settings fields while this add-on's settings window is open."""

    def __init__(self) -> None:
        self._settings_visible = False
        self._seconds_visible = 0

    def tick(self) -> None:
        visible = is_own_addon_settings_visible()
        if visible:
            refresh_user_agent_setting(xbmcaddon.Addon(id=_ADDON_ID))
            if not self._settings_visible or self._seconds_visible % _SETTINGS_REFRESH_INTERVAL_S == 0:
                refresh_subtitle_cache_setting()
            self._seconds_visible += 1
        else:
            self._seconds_visible = 0
        self._settings_visible = visible
