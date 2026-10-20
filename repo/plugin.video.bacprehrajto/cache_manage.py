# -*- coding: utf-8 -*-
"""Unified cache management (invoked from add-on settings)."""

import sys

import xbmcgui

from cache.manager import (
    clear_all_caches,
    format_total_cache_size_label,
    refresh_all_cache_settings,
)
from cache.search_cache import (
    clear_search_cache,
    format_search_cache_size_label,
    refresh_search_cache_setting,
)
from cache.subtitle_cache import (
    clear_subtitle_cache,
    format_subtitle_cache_size_label,
    refresh_subtitle_cache_setting,
)
from common import _ADDON_NAME
from utils.StrUtils import convert_size


def _notify(heading: str, message: str, icon=xbmcgui.NOTIFICATION_INFO) -> None:
    xbmcgui.Dialog().notification(heading, message, icon, 4000, sound=False)


def _run_refresh() -> None:
    refresh_all_cache_settings()


def _run_clear_search() -> None:
    current = format_search_cache_size_label()
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME,
            f'Smazat cache hledání?\n\nAktuální velikost: {current}',
            nolabel='Ne',
            yeslabel='Ano',
    ):
        return

    removed, freed = clear_search_cache()
    refresh_all_cache_settings()
    if removed == 0:
        _notify(_ADDON_NAME, 'Cache hledání je již prázdná')
        return
    _notify(_ADDON_NAME, f'Smazáno {removed} souborů ({convert_size(freed, 1)})')


def _run_clear_subtitles() -> None:
    current = format_subtitle_cache_size_label()
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME,
            f'Smazat cache titulků?\n\nAktuální velikost: {current}',
            nolabel='Ne',
            yeslabel='Ano',
    ):
        return

    removed, freed = clear_subtitle_cache()
    refresh_all_cache_settings()
    if removed == 0:
        _notify(_ADDON_NAME, 'Cache titulků je již prázdná')
        return
    _notify(_ADDON_NAME, f'Smazáno {removed} souborů ({convert_size(freed, 1)})')


def _run_clear_all() -> None:
    current = format_total_cache_size_label()
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME,
            f'Smazat veškerou cache?\n\nAktuální velikost: {current}',
            nolabel='Ne',
            yeslabel='Ano',
    ):
        return

    result = clear_all_caches()
    refresh_all_cache_settings()
    if result.total_removed == 0:
        _notify(_ADDON_NAME, 'Cache je již prázdná')
        return
    _notify(
        _ADDON_NAME,
        f'Smazáno {result.total_removed} souborů ({convert_size(result.total_freed, 1)})',
    )


if __name__ == '__main__':
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'refresh').strip().lower()
    if mode == 'clear_all':
        _run_clear_all()
    elif mode == 'clear_search':
        _run_clear_search()
    elif mode == 'clear_subtitles':
        _run_clear_subtitles()
    else:
        _run_refresh()
