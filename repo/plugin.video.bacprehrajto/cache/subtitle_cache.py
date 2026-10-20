import os
from typing import Tuple

import xbmc
import xbmcaddon

from common import _ADDON_ID, addon, refresh_prehrajto_base_cache
from cache.manager import format_cache_size_label, refresh_all_cache_settings
from cache.paths import ensure_cache_initialized, get_subtitle_cache_dir
from utils.user_agent_presets import refresh_user_agent_setting
from utils.utils import dprint

_SETTINGS_REFRESH_INTERVAL_S = 2


def get_subtitle_cache_stats() -> Tuple[int, int]:
    """Return (file_count, total_bytes)."""
    ensure_cache_initialized()
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
    return format_cache_size_label(file_count, total_bytes)


def clear_subtitle_cache() -> Tuple[int, int]:
    """Delete cached subtitle files. Returns (files_removed, bytes_freed)."""
    ensure_cache_initialized()
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
    try:
        from cache.manager import refresh_total_cache_setting
        refresh_total_cache_setting()
    except Exception as exc:
        dprint(f'refresh_subtitle_cache_setting(): total refresh failed: {exc}')
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
            if not self._settings_visible:
                refresh_prehrajto_base_cache()
            if not self._settings_visible or self._seconds_visible % _SETTINGS_REFRESH_INTERVAL_S == 0:
                refresh_all_cache_settings()
            self._seconds_visible += 1
        else:
            if self._settings_visible:
                refresh_prehrajto_base_cache()
            self._seconds_visible = 0
        self._settings_visible = visible
