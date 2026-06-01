# -*- coding: utf-8 -*-
"""Refresh or clear the playback subtitle cache (invoked from add-on settings)."""

import sys

import xbmcgui

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
    refresh_subtitle_cache_setting()


def _run_clear() -> None:
    current = format_subtitle_cache_size_label()
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME,
            f'Smazat cache titulků?\n\nAktuální velikost: {current}',
            nolabel='Ne',
            yeslabel='Ano',
    ):
        return

    removed, freed = clear_subtitle_cache()
    refresh_subtitle_cache_setting()
    if removed == 0:
        _notify(_ADDON_NAME, 'Cache titulků je již prázdná')
        return
    _notify(
        _ADDON_NAME,
        f'Smazáno {removed} souborů ({convert_size(freed, 1)})',
    )


if __name__ == '__main__':
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'refresh').strip().lower()
    if mode == 'clear':
        _run_clear()
    else:
        _run_refresh()
