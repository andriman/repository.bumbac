# -*- coding: utf-8 -*-
"""Hooks for external addons: context-menu search and TMDB Helper player install."""

from __future__ import annotations

import os
from typing import Dict, Optional
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from common import _ADDON_ID, _ADDON_NAME

_TMDB_HELPER_ID = 'plugin.video.themoviedb.helper'
_PLAYER_FILENAME = 'bacprehrajto.json'
_SETTING_CONTEXT_SEARCH = 'context_menu_search'


def is_context_search_enabled() -> bool:
    try:
        return xbmcaddon.Addon(id=_ADDON_ID).getSetting(_SETTING_CONTEXT_SEARCH) != 'false'
    except Exception:
        return True


def _safe_int(value) -> Optional[int]:
    try:
        if value is None or value == '':
            return None
        number = int(value)
        if number < 0:
            return None
        return number
    except (TypeError, ValueError):
        return None


def build_search_query_from_listitem(listitem) -> str:
    """Build a Hledat query from a context-menu ListItem (movie / episode / show)."""
    if listitem is None:
        return ''

    title = ''
    showname = ''
    media = ''
    year = None
    season = None
    episode = None

    try:
        tag = listitem.getVideoInfoTag()
    except (AttributeError, RuntimeError, TypeError):
        tag = None

    if tag is not None:
        try:
            media = (tag.getMediaType() or '').strip().lower()
        except (AttributeError, RuntimeError, TypeError):
            media = ''
        try:
            title = (tag.getTitle() or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            title = ''
        try:
            showname = (tag.getTVShowTitle() or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            showname = ''
        try:
            year = _safe_int(tag.getYear())
        except (AttributeError, RuntimeError, TypeError):
            year = None
        try:
            season = _safe_int(tag.getSeason())
        except (AttributeError, RuntimeError, TypeError):
            season = None
        try:
            episode = _safe_int(tag.getEpisode())
        except (AttributeError, RuntimeError, TypeError):
            episode = None

    if not title:
        try:
            title = (listitem.getLabel() or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            title = ''

    if media == 'episode' or (showname and season is not None and episode is not None):
        show = showname or title
        if show and season is not None and episode is not None:
            return f'{show} S{season:02d}E{episode:02d}'

    if media == 'season' and showname and season is not None:
        return f'{showname} S{season:02d}'

    if media == 'tvshow':
        return showname or title

    # Movies / generic video: title only (year often hurts hoster filename matches).
    return title or showname


def open_search(query: str, extra: Optional[Dict[str, str]] = None) -> None:
    q = (query or '').strip()
    if not q:
        xbmcgui.Dialog().notification(
            _ADDON_NAME,
            'Nelze zjistit název pro hledání',
            xbmcgui.NOTIFICATION_INFO,
            3000,
            sound=False,
        )
        return

    params = {'action': 'listing_search', 'name': q}
    if extra:
        for key, value in extra.items():
            if value is None or value == '':
                continue
            params[key] = str(value)
    plugin_url = f'plugin://{_ADDON_ID}/?{urlencode(params)}'
    xbmc.executebuiltin(f'ActivateWindow(Videos,{plugin_url},return)')


def run_context_search(listitem) -> None:
    if not is_context_search_enabled():
        return
    query = build_search_query_from_listitem(listitem)
    open_search(query)


def _player_source_path() -> str:
    addon_path = xbmcaddon.Addon(id=_ADDON_ID).getAddonInfo('path')
    return os.path.join(addon_path, 'resources', 'players', _PLAYER_FILENAME)


def _player_dest_dir() -> str:
    return xbmcvfs.translatePath(
        f'special://profile/addon_data/{_TMDB_HELPER_ID}/players/'
    )


def _player_dest_path() -> str:
    return os.path.join(_player_dest_dir(), _PLAYER_FILENAME)


def install_tmdb_helper_player() -> None:
    """Copy bundled player JSON into TMDB Helper's players folder."""
    if not xbmc.getCondVisibility(f'System.HasAddon({_TMDB_HELPER_ID})'):
        xbmcgui.Dialog().ok(
            _ADDON_NAME,
            'TMDB Helper není nainstalovaný.\n\n'
            'Nainstalujte plugin.video.themoviedb.helper a akci opakujte.',
        )
        return

    src = _player_source_path()
    if not xbmcvfs.exists(src) and not os.path.isfile(src):
        xbmcgui.Dialog().notification(
            _ADDON_NAME,
            'Soubor přehrávače v addonu chybí',
            xbmcgui.NOTIFICATION_ERROR,
            4000,
        )
        return

    dest_dir = _player_dest_dir()
    dest = _player_dest_path()
    xbmcvfs.mkdirs(dest_dir)

    if xbmcvfs.exists(dest) or os.path.isfile(dest):
        if not xbmcgui.Dialog().yesno(
                _ADDON_NAME,
                'Přehrávač Přehraj.to už v TMDB Helper existuje.\n\nPřepsat?',
                nolabel='Ne',
                yeslabel='Ano',
        ):
            return

    if not xbmcvfs.copy(src, dest):
        # Fallback for paths where xbmcvfs.copy is picky on Windows.
        try:
            with open(src, 'rb') as f_src:
                data = f_src.read()
            with open(dest, 'wb') as f_dst:
                f_dst.write(data)
        except OSError as exc:
            xbmcgui.Dialog().notification(
                _ADDON_NAME,
                f'Kopírování selhalo: {exc}',
                xbmcgui.NOTIFICATION_ERROR,
                4000,
            )
            return

    xbmcgui.Dialog().ok(
        _ADDON_NAME,
        'Přehrávač Přehraj.to byl nainstalován do TMDB Helper.\n\n'
        'Restartujte Kodi (nebo TMDB Helper) a v nastavení TMDB Helper '
        'zkontrolujte, že je přehrávač povolený.',
    )
