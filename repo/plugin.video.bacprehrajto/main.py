# -*- coding: utf-8 -*-

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote
from urllib.parse import urlparse

import requests
import unicodedata
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from common import _ADDON_ID, addon, g_download_path, g_quality_selector, \
    history_path, \
    get_headers, images_path, icons_path, _ADDON_NAME, get_prehrajto_base, normalize_prehrajto_url, \
    g_highlight_fake_streams, \
    g_is_prehrajto_enabled, g_is_sledujteto_enabled, g_is_hellspy_enabled, is_csfd_menu_enabled, display_provider_headers, ICON_BIN_DELETE, \
    ICON_REFRESH, set_list_icon, go_to_main_menu
from model.QS import QS
from model.StreamData import StreamData
from model.SubData import SubData
from modules.SplitSelectorDialog import search_variants_dialog
from providers.UniversalProvider import UniversalProvider
from providers.prehrajto.auth import ensure_premium, refresh_premium_from_html
from providers.prehrajto.download import _has_cookies, resolve_premium_download_url
from providers.prehrajto.playback_context import (
    build_prehrajto_stream_context,
    resolve_stream_path_for_playback,
    resolve_subtitles_for_selection,
)
from providers.browsing_context import remember_provider_page
from providers.prehrajto.session import get_session, has_auth_cookies
from account.account_menu import PROVIDER_HELLSPY, PROVIDER_PREHRAJTO, PROVIDER_SLEDUJTETO, get_account_root_label
from account.account_router import account_router
from cache.search_cache import (
    get_cached_item_count,
    invalidate,
    is_cache_enabled,
    make_cache_key,
    mark_play_return,
    set_cached,
    set_last_listing_key,
    try_load_cache,
)
from downloads.download_actions import download_direct, enqueue_background_download, enqueue_to_queue_only
from downloads.download_subtitles import subtitle_paths_for_playback
from downloads.downloads_router import downloads_router
from downloads.downloads_utils import cleanup_subtitle_sidecars, get_download_queue_root_label, get_downloads_root_label
from downloads.stream_select import pick_stream, open_stream_selector
from tmdb.tmdb import fetch_imdb_id, fetch_localized_title
from tmdb.tmdb_router import tmdb_router
from tmdb.tmdb_language import get_tmdb_language_menu_label, pick_tmdb_active_language_dialog
from unidecode.unidecode import unidecode
from utils.ClipboardUtils import ClipboardUtils
from utils.StrUtils import drop_trailing_stored_year, release_title_for_playback
from utils.external_integration import open_search
from utils.listitem_infotag import (
    IMDB_ID_PROP,
    PLAYBACK_INFO_PROP,
    apply_art, apply_deferred_listing_stream_info, apply_video_info, apply_video_stream_info,
)
from utils.stream_fake_hint import LISTING_THUMB_PROP, maybe_highlight_fake_stream_in_listitem
from utils.search_source_items import (
    group_search_results,
    is_provider_header_item,
    is_source_no_results_item,
)
from utils.video_actions_menu import show_video_actions_menu
from utils.utils import dprint, \
    urlencode, apply_stream_headers, apply_context_menu_items, build_video_context_menu_items

_url = sys.argv[0]
_handle = int(sys.argv[1])

_PLAYING_LINK_PROP = 'bacprehrajto.playing_link'
_PLAYING_MEDIA_PROP = 'bacprehrajto.playing_media'
_RESOLVE_LINK_PROP = 'bacprehrajto.resolve_link'
_RESOLVE_AT_PROP = 'bacprehrajto.resolve_at'
_RESOLVE_TTL_SECONDS = 20

_last_page_content = None

_provider = UniversalProvider()

_PLAYBACK_TIMEOUT = 20


def get_url(**kwargs):
    return '{0}?{1}'.format(_url, urlencode(kwargs))


def encode(string):
    line = unicodedata.normalize('NFKD', string)
    output = ''
    for c in line:
        if not unicodedata.combining(c):
            output += c
    return output


def get_premium():
    """Returns (1|0, cookies) for Prehrajto; skips login when Prehrajto source is disabled."""
    if not g_is_prehrajto_enabled:
        return 0, None
    is_premium, cookies = ensure_premium(addon)
    return (1 if is_premium else 0), cookies


# def play_video(link):
#     data = urlparse(link)
#
#     dprint(f'play_video(): quality_selector: ' + quality_selector)
#
#     # Max Compressed
#     url = requests.get("https://prehraj.to" + data.path, headers=headers).content
#     file, sub = get_link(url)
#
#     notify_file_size(file)
#
#     listitem = xbmcgui.ListItem(path = file)
#     if sub != "":
#         subtitles = []
#         subtitles.append(sub)
#         listitem.setSubtitles(subtitles)
#
#     ############
#     # video_info = listitem.getInfo('video')
#     # video_info['plot'] = 'Stream size: '+file_size_str+'\r\n'+video_info.get('plot', '')
#     # listitem.setInfo('video', video_info)
#
#     xbmcplugin.setResolvedUrl(_handle, True, listitem)

def get_premium_link(link, cookies=None) -> Optional[str]:
    if cookies is None:
        dprint('get_premium_link(): login cookies required')
        return None
    return resolve_premium_download_url(link, cookies=cookies)


def _fetch_play_page(link: str) -> Tuple[str, bytes, Optional[object]]:
    try:
        if 'sledujteto' in link:
            from providers.sledujteto.session import get_session as get_sledujteto_session
            res = get_sledujteto_session().get(
                link, headers=get_headers(), allow_redirects=True, timeout=_PLAYBACK_TIMEOUT,
            )
            res.raise_for_status()
            remember_provider_page(res.url)
            return res.url, res.content, None

        if 'hellspy' in link.lower():
            from providers.hellspy.auth import request_headers
            from providers.hellspy.session import get_session as get_hellspy_session, save_session as save_hellspy_session
            res = get_hellspy_session().get(
                link, headers=request_headers(), allow_redirects=True, timeout=_PLAYBACK_TIMEOUT,
            )
            res.raise_for_status()
            save_hellspy_session()
            remember_provider_page(res.url)
            return res.url, res.content, None

        if 'prehraj' not in link:
            res = requests.get(
                link, headers=get_headers(), allow_redirects=True, timeout=_PLAYBACK_TIMEOUT,
            )
            res.raise_for_status()
            return res.url, res.content, None

        session = get_session()
        cookies = None
        if g_is_prehrajto_enabled:
            ensure_premium(addon)
            cookies = session.cookies if has_auth_cookies(session) else None
        fetch_link = normalize_prehrajto_url(link) if 'prehraj' in link else link
        res = session.get(
            fetch_link, headers=get_headers(), allow_redirects=True, timeout=_PLAYBACK_TIMEOUT,
        )
        res.raise_for_status()
        remember_provider_page(res.url)
        refresh_premium_from_html(res.content)
        return res.url, res.content, cookies
    except requests.RequestException as exc:
        dprint(f'_fetch_play_page(): {exc}')
        raise


def _get_play_streams(page_url: str, content: bytes):
    return _provider.get_streams_data(page_url, content, show_progress=False)


def _first_premium_stream(streams: List[StreamData]) -> Optional[StreamData]:
    for stream in streams:
        if stream.is_premium:
            return stream
    return None


def _first_non_premium_stream(streams: List[StreamData]) -> Optional[StreamData]:
    for stream in streams:
        if not stream.is_premium:
            return stream
    return None


def _is_premium_playback_ready(stream: StreamData, cookies=None) -> bool:
    if not stream.path:
        return False
    if stream.is_premium and '?do=download' in stream.path:
        return _has_cookies(cookies)
    return True


def _prehrajto_cookie_header(cookies=None) -> Optional[str]:
    jar = cookies
    if jar is None:
        jar = get_session().cookies
    if not jar:
        return None
    parts = [f'{c.name}={c.value}' for c in jar if c.value]
    return '; '.join(parts) if parts else None


def _resolve_prehrajto_max_playback(
        ctx,
        page_url: str,
        content: bytes,
        cookies,
) -> Optional[xbmcgui.ListItem]:
    premium = _first_premium_stream(ctx.streams)
    if premium is not None:
        subs = resolve_subtitles_for_selection(ctx, premium)
        resolved_premium = resolve_stream_path_for_playback(ctx, premium)
        if _is_premium_playback_ready(resolved_premium, cookies):
            dprint('play_video(): premium link: ' + resolved_premium.path)
            return _build_stream_listitem(resolved_premium, subs, content, page_url, cookies=cookies)

    compressed = _first_non_premium_stream(ctx.streams)
    if compressed is None:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Streamy nenalezeny',
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False,
        )
        return None

    if _has_cookies(cookies):
        fallback_msg = 'Premium není dostupný. Přehrávám nejvyšší komprimovanou kvalitu.'
    else:
        fallback_msg = 'Pro premium je nutné přihlášení. Přehrávám nejvyšší komprimovanou kvalitu.'
    xbmcgui.Dialog().notification(
        _ADDON_NAME, fallback_msg,
        xbmcgui.NOTIFICATION_INFO, 4000, sound=False,
    )
    return _play_prehrajto_selected(page_url, content, cookies, compressed)


def _play_prehrajto_selected(
        page_url: str,
        content: bytes,
        cookies,
        selected: StreamData,
) -> xbmcgui.ListItem:
    ctx = build_prehrajto_stream_context(page_url, content, cookies)
    subs = resolve_subtitles_for_selection(ctx, selected)
    selected = resolve_stream_path_for_playback(ctx, selected)
    return _build_stream_listitem(selected, subs, content, page_url, cookies=cookies)


def _sledujteto_cookie_header() -> Optional[str]:
    if not g_is_sledujteto_enabled:
        return None
    try:
        from providers.sledujteto.session import get_session
        parts = [f'{c.name}={c.value}' for c in get_session().cookies if c.value]
        return '; '.join(parts) if parts else None
    except Exception:
        return None


def _selected_playback_item():
    return getattr(sys, 'listitem', None)


def _tag_value(tag, method_name: str):
    method = getattr(tag, method_name, None)
    if method is None:
        return None
    try:
        return method()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _selected_playback_title() -> str:
    """Name of the directory item that started playback."""
    item = _selected_playback_item()
    if item is not None:
        try:
            label = (item.getLabel() or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            label = ''
        if label:
            return label
        try:
            tag = item.getVideoInfoTag()
            title = (tag.getTitle() or '').strip() if tag is not None else ''
        except (AttributeError, RuntimeError, TypeError):
            title = ''
        if title:
            return title
    for key in ('ListItem.Label', 'ListItem.Title', 'Container.ListItem.Label'):
        try:
            label = (xbmc.getInfoLabel(key) or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            label = ''
        if label:
            return label
    return ''


def _stored_playback_info(item) -> Dict[str, Any]:
    try:
        raw = (item.getProperty(PLAYBACK_INFO_PROP) or '').strip()
    except (AttributeError, RuntimeError, TypeError):
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _container_stored_playback_info() -> Dict[str, Any]:
    """Directory row metadata. The resolve listitem is a new empty item."""
    for key in (
            f'Container.ListItem.Property({PLAYBACK_INFO_PROP})',
            f'ListItem.Property({PLAYBACK_INFO_PROP})',
    ):
        try:
            raw = (xbmc.getInfoLabel(key) or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            raw = ''
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(data, dict) and data:
            return data
    return {}


def _playback_info_is_identified(info: Dict[str, Any]) -> bool:
    imdb = str(info.get('imdbnumber') or '').strip()
    if imdb.startswith('tt'):
        return True
    unique = info.get('uniqueid')
    if isinstance(unique, dict) and str(unique.get('imdb') or '').startswith('tt'):
        return True
    if str(info.get('tvshowtitle') or '').strip():
        return True
    return info.get('season') is not None or info.get('episode') is not None


def _playback_info_from_item(item) -> Dict[str, Any]:
    """Metadata a4kSubtitles reads from the playing item. Label stays the release name."""
    info: Dict[str, Any] = {}
    if item is None:
        return info

    stored = _stored_playback_info(item)
    imdb = ''
    try:
        imdb = (item.getProperty(IMDB_ID_PROP) or '').strip()
    except (AttributeError, RuntimeError, TypeError):
        imdb = ''
    if not imdb.startswith('tt'):
        imdb = str(stored.get('imdbnumber') or '').strip()

    try:
        tag = item.getVideoInfoTag()
    except (AttributeError, RuntimeError, TypeError):
        tag = None

    unique: Dict[str, str] = {}
    stored_unique = stored.get('uniqueid')
    if isinstance(stored_unique, dict):
        tmdb_id = str(stored_unique.get('tmdb') or '').strip()
        if tmdb_id:
            unique['tmdb'] = tmdb_id
        stored_imdb = str(stored_unique.get('imdb') or '').strip()
        if stored_imdb.startswith('tt'):
            imdb = stored_imdb

    if tag is not None:
        title = str(_tag_value(tag, 'getTitle') or '').strip()
        if title:
            info['title'] = title
        tvshow = str(_tag_value(tag, 'getTVShowTitle') or '').strip()
        if tvshow:
            info['tvshowtitle'] = tvshow
        year_raw = _tag_value(tag, 'getYear')
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            year = 0
        if year > 0:
            info['year'] = year
        premiered = str(_tag_value(tag, 'getPremiered') or '').strip()
        if premiered:
            info['premiered'] = premiered
        plot = str(_tag_value(tag, 'getPlot') or '').strip()
        if plot:
            info['plot'] = plot
        outline = str(_tag_value(tag, 'getPlotOutline') or '').strip()
        if outline:
            info['plotoutline'] = outline
        try:
            rating = float(_tag_value(tag, 'getRating'))
        except (TypeError, ValueError):
            rating = 0
        if rating > 0:
            info['rating'] = rating
        media = str(_tag_value(tag, 'getMediaType') or '').strip().lower()
        if media in ('movie', 'episode'):
            info['mediatype'] = media
        get_unique = getattr(tag, 'getUniqueID', None)
        if get_unique is not None:
            try:
                tag_imdb = str(get_unique('imdb') or '').strip()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                tag_imdb = ''
            if tag_imdb.startswith('tt'):
                imdb = tag_imdb
            try:
                tmdb_id = str(get_unique('tmdb') or '').strip()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                tmdb_id = ''
            if tmdb_id:
                unique['tmdb'] = tmdb_id
        if not imdb.startswith('tt'):
            imdb_number = str(_tag_value(tag, 'getIMDBNumber') or '').strip()
            if imdb_number.startswith('tt'):
                imdb = imdb_number

    for key in ('title', 'tvshowtitle', 'year', 'premiered', 'mediatype', 'plot', 'plotoutline', 'rating'):
        if info.get(key) not in (None, ''):
            continue
        value = stored.get(key)
        if value is None or value == '':
            continue
        if key == 'mediatype' and str(value).strip().lower() not in ('movie', 'episode'):
            continue
        info[key] = value

    if str(info.get('mediatype') or '').strip().lower() == 'episode':
        for key, getter in (('season', 'getSeason'), ('episode', 'getEpisode')):
            number = None
            if tag is not None:
                try:
                    number = int(_tag_value(tag, getter))
                except (TypeError, ValueError):
                    number = None
            if number is None or number < 0:
                try:
                    number = int(stored.get(key))
                except (TypeError, ValueError):
                    number = None
            if number is not None and number >= 0:
                info[key] = number

    if imdb.startswith('tt'):
        unique['imdb'] = imdb
        info['imdbnumber'] = imdb
    if unique:
        info['uniqueid'] = unique
    return info


def _playback_info_from_selected() -> Dict[str, Any]:
    info = _playback_info_from_item(_selected_playback_item())
    if _playback_info_is_identified(info):
        return info
    stored = _container_stored_playback_info()
    if not stored:
        return info
    merged = dict(stored)
    for key, value in info.items():
        if value is None or value == '':
            continue
        merged[key] = value
    return _playback_info_from_stored(merged)


def _playback_info_from_stored(stored: Dict[str, Any]) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    for key in (
            'title', 'tvshowtitle', 'year', 'premiered', 'mediatype', 'season', 'episode',
            'plot', 'plotoutline', 'rating',
    ):
        value = stored.get(key)
        if value is None or value == '':
            continue
        if key == 'mediatype' and str(value).strip().lower() not in ('movie', 'episode'):
            continue
        info[key] = value
    unique: Dict[str, str] = {}
    stored_unique = stored.get('uniqueid')
    if isinstance(stored_unique, dict):
        for uid_type in ('tmdb', 'imdb'):
            uid_val = str(stored_unique.get(uid_type) or '').strip()
            if uid_val:
                unique[uid_type] = uid_val
    imdb = str(unique.get('imdb') or stored.get('imdbnumber') or '').strip()
    if imdb.startswith('tt'):
        unique['imdb'] = imdb
        info['imdbnumber'] = imdb
    elif 'imdb' in unique:
        unique.pop('imdb', None)
    if unique:
        info['uniqueid'] = unique
    return info


def _copy_item_art(source, dest) -> None:
    if source is None or dest is None:
        return
    art = {}
    for key in ('poster', 'fanart', 'thumb', 'landscape', 'icon', 'clearlogo', 'banner', 'clearart'):
        try:
            value = (source.getArt(key) or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            value = ''
        if value:
            art[key] = value
    if art:
        apply_art(dest, art)


def _build_stream_listitem(
        stream: StreamData,
        subs: Optional[List[SubData]],
        page_content: bytes,
        page_url: str,
        cookies=None,
) -> xbmcgui.ListItem:
    release_label = release_title_for_playback(_selected_playback_title())
    playback_info = _playback_info_from_selected()
    known_title = str(playback_info.get('title') or '').strip()
    if known_title:
        label = known_title
    else:
        label = release_label
        if label:
            playback_info['title'] = drop_trailing_stored_year(label, playback_info.get('year')) or label
        elif playback_info.get('title'):
            playback_info['title'] = release_title_for_playback(str(playback_info['title']))
            label = str(playback_info.get('title') or '')
    listitem = xbmcgui.ListItem(label=label, path=stream.path)
    try:
        listitem.setContentLookup(False)
    except (AttributeError, RuntimeError, TypeError):
        pass
    path_lower = (stream.path or '').lower()
    if '/file.mp4' in path_lower or '/file?' in path_lower or path_lower.endswith('.mp4'):
        try:
            listitem.setMimeType('video/mp4')
        except (AttributeError, RuntimeError, TypeError):
            pass
        listitem.setProperty('mimetype', 'video/mp4')
    if stream.duration:
        stream_info = {'duration': stream.duration}
        if playback_info.get('mediatype') not in ('movie', 'episode'):
            stream_info['mediatype'] = 'video'
        apply_video_stream_info(listitem, stream_info)
    if playback_info.get('mediatype') not in ('movie', 'episode'):
        playback_info['mediatype'] = 'video'
    if playback_info:
        apply_video_info(listitem, playback_info)
    _copy_item_art(_selected_playback_item(), listitem)

    cookie_str = None
    if 'sledujteto' in stream.path:
        cookie_str = _sledujteto_cookie_header()
    elif 'prehraj' in page_url and stream.is_premium and _has_cookies(cookies):
        cookie_str = _prehrajto_cookie_header(cookies)
    apply_stream_headers(listitem, stream.headers, cookies=cookie_str)

    referer = page_url if ('prehraj' in page_url or 'hellspy' in page_url.lower()) else None
    sub_paths = subtitle_paths_for_playback(subs, referer=referer)
    if sub_paths:
        listitem.setSubtitles(sub_paths)
    return listitem


def _publish_hellspy_for_playback(link: str) -> bool:
    """Ask to publish a private HellSpy video, then allow playback."""
    from providers.hellspy.account_videos import client_video_id, set_video_public

    video_id = client_video_id(link)
    if not video_id:
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return False
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME,
            'Video není veřejné. Bez zveřejnění ho nelze přehrát. Zveřejnit?',
            nolabel='Ne',
            yeslabel='Ano',
    ):
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return False
    try:
        changed = set_video_public(video_id, True)
    except Exception as exc:
        dprint(f'hellspy publish for playback: {exc}')
        changed = False
    if not changed:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Změna se nezdařila',
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return False
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Video je veřejné',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    return True


def _normalize_link(link: str) -> str:
    return unquote(link or '').strip()


def _link_from_plugin_path(path: str) -> str:
    if not path.startswith('plugin://'):
        return ''
    parsed = urlparse(path)
    if parsed.netloc != _ADDON_ID:
        return ''
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query.get('action') not in ('play', 'resume_or_play'):
        return ''
    return _normalize_link(query.get('link') or '')


def _video_player_id() -> Optional[int]:
    try:
        raw = xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0',
            'method': 'Player.GetActivePlayers',
            'id': 1,
        }))
        players = json.loads(raw).get('result') or []
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    for player in players:
        if player.get('type') == 'video':
            return player.get('playerid')
    return None


def _playing_identity_paths() -> List[str]:
    """Paths that still identify the playing plugin item, plus the resolved file."""
    paths: List[str] = []
    try:
        playing_file = xbmc.Player().getPlayingFile() or ''
    except RuntimeError:
        playing_file = ''
    if playing_file:
        paths.append(playing_file)

    player_id = _video_player_id()
    if player_id is not None:
        try:
            raw = xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0',
                'method': 'Player.GetItem',
                'params': {'playerid': player_id, 'properties': ['file']},
                'id': 1,
            }))
            item = (json.loads(raw).get('result') or {}).get('item') or {}
            file_path = item.get('file') or ''
            if file_path:
                paths.append(file_path)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
    position = playlist.getposition()
    if position >= 0:
        try:
            item_path = playlist[position].getPath() or ''
        except (RuntimeError, IndexError, TypeError):
            item_path = ''
        if item_path:
            paths.append(item_path)

    focused = (
        ('Container.ListItem.IsPlaying', 'Container.ListItem.FilenameAndPath'),
        ('Container(10025).ListItem.IsPlaying', 'Container(10025).ListItem.FilenameAndPath'),
        ('ListItem.IsPlaying', 'ListItem.FilenameAndPath'),
    )
    for condition, label in focused:
        if not xbmc.getCondVisibility(condition):
            continue
        path = xbmc.getInfoLabel(label) or ''
        if path:
            paths.append(path)
    return paths


def _remember_playing(link: str, listitem: xbmcgui.ListItem) -> None:
    window = xbmcgui.Window(10000)
    window.setProperty(_PLAYING_LINK_PROP, link or '')
    window.setProperty(_PLAYING_MEDIA_PROP, listitem.getPath() or '')


def _stored_playback_matches(wanted: str) -> bool:
    window = xbmcgui.Window(10000)
    if _normalize_link(window.getProperty(_PLAYING_LINK_PROP)) != wanted:
        return False
    stored_media = (window.getProperty(_PLAYING_MEDIA_PROP) or '').strip()
    if not stored_media:
        return False
    try:
        playing_file = (xbmc.Player().getPlayingFile() or '').strip()
    except RuntimeError:
        return False
    return playing_file == stored_media


def _clicked_link_is_playing(link: str) -> bool:
    wanted = _normalize_link(link)
    if not wanted or not xbmc.Player().isPlayingVideo():
        return False
    for path in _playing_identity_paths():
        if _normalize_link(_link_from_plugin_path(path)) == wanted:
            return True
        if _normalize_link(path) == wanted:
            return True
    return _stored_playback_matches(wanted)


def _show_playing_fullscreen() -> None:
    """Open fullscreen video. The click must not be a player resolve."""
    dprint('play: already playing, returning to fullscreen')
    xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')


def _resume_or_play_url(link: str, publish: str = '') -> str:
    if publish == '1':
        return get_url(action='resume_or_play', link=link, publish='1')
    return get_url(action='resume_or_play', link=link)


def _claim_list_resolve(link: str) -> None:
    window = xbmcgui.Window(10000)
    window.setProperty(_RESOLVE_LINK_PROP, link or '')
    window.setProperty(_RESOLVE_AT_PROP, str(time.time()))


def _take_list_resolve(link: str) -> bool:
    """True when this call is the player resolve started by a list click."""
    window = xbmcgui.Window(10000)
    if _normalize_link(window.getProperty(_RESOLVE_LINK_PROP)) != _normalize_link(link):
        return False
    try:
        started = float(window.getProperty(_RESOLVE_AT_PROP) or '0')
    except ValueError:
        return False
    window.clearProperty(_RESOLVE_LINK_PROP)
    window.clearProperty(_RESOLVE_AT_PROP)
    return time.time() - started <= _RESOLVE_TTL_SECONDS


def _play_listed_url(url: str) -> None:
    """Start playback from the clicked row. The resolve call only sees this new item."""
    listitem = xbmcgui.ListItem(path=url)
    listitem.setProperty('IsPlayable', 'true')
    source = _selected_playback_item()
    if source is not None:
        try:
            label = (source.getLabel() or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            label = ''
        if label:
            try:
                listitem.setLabel(label)
            except (AttributeError, RuntimeError, TypeError):
                pass
    info = _playback_info_from_selected()
    if info:
        apply_video_info(listitem, info)
        known_title = str(info.get('title') or '').strip()
        if known_title:
            try:
                listitem.setLabel(known_title)
            except (AttributeError, RuntimeError, TypeError):
                pass
    _copy_item_art(source, listitem)
    xbmc.Player().play(url, listitem)


def _start_play_action(link: str, params: dict) -> None:
    mark_play_return()
    if params.get('publish') == '1' and not _publish_hellspy_for_playback(link):
        return
    play_video(link)
    if params.get('publish') == '1':
        xbmc.executebuiltin('Container.Refresh')


def _resolve_and_play(listitem: xbmcgui.ListItem, link: str) -> None:
    _remember_playing(link, listitem)
    xbmcplugin.setResolvedUrl(_handle, True, listitem)


def play_video(link, force_quality=None):
    dprint(
        f'play_video(): quality_selector = ' + str(g_quality_selector) +
            ', force_quality = ' + str(force_quality)
    )

    if force_quality == QS.Max or g_quality_selector == QS.Max:  # Premium.
        try:
            page_url, content, cookies = _fetch_play_page(link)
        except requests.RequestException:
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return
        if 'prehraj' not in page_url:
            streams, subs = _get_play_streams(page_url, content)
            if streams is None or len(streams) == 0:
                dprint(f'play_video(): no streams for {page_url}')
                xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
                return
            selected = streams[0]
            if 'hellspy' in page_url.lower():
                selected = _first_premium_stream(streams) or selected
                dprint(f'play_video(): hellspy maximum {selected.label} {selected.path}')
            listitem = _build_stream_listitem(selected, subs, content, page_url)
            _resolve_and_play(listitem, link)
            return
        ctx = build_prehrajto_stream_context(page_url, content, cookies)
        listitem = _resolve_prehrajto_max_playback(ctx, page_url, content, cookies)
        if listitem is not None:
            _remember_playing(link, listitem)
        xbmcplugin.setResolvedUrl(_handle, listitem is not None, listitem or xbmcgui.ListItem())
    else:
        try:
            page_url, content, cookies = _fetch_play_page(link)
        except requests.RequestException:
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return

        if 'prehraj' in page_url:
            ctx = build_prehrajto_stream_context(page_url, content, cookies)
            if not ctx.streams:
                xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
                return
            streams = ctx.streams
        else:
            streams, subs = _get_play_streams(page_url, content)
            if streams is None or len(streams) == 0:
                xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
                return

        if g_quality_selector == QS.BestCompressed:  # Max Compressed
            selected = streams[0]
            if 'hellspy' in page_url.lower():
                selected = _first_non_premium_stream(streams) or selected
                dprint(f'play_video(): hellspy compressed {selected.label} {selected.path}')
            if 'prehraj' in page_url:
                listitem = _play_prehrajto_selected(page_url, content, cookies, selected)
            else:
                listitem = _build_stream_listitem(selected, subs, content, page_url)
            _resolve_and_play(listitem, link)
        elif g_quality_selector == QS.Selector:  # Selector
            selected = pick_stream(streams)

            if selected is None:
                xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
                return

            dprint('SELECTED: ' + str(selected.is_premium))
            dprint('SELECTED: ' + selected.path)

            if 'prehraj' in page_url:
                listitem = _play_prehrajto_selected(page_url, content, cookies, selected)
            else:
                listitem = _build_stream_listitem(selected, subs, content, page_url)
            _resolve_and_play(listitem, link)


def select_and_play_stream(link: str) -> None:
    """Pick a stream via dialog and play it directly (cancel does not stop current playback)."""
    try:
        page_url, content, cookies = _fetch_play_page(link)
    except requests.RequestException:
        return
    if 'prehraj' in page_url:
        ctx = build_prehrajto_stream_context(page_url, content, cookies)
        if not ctx.streams:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Streamy nenalezeny',
                xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
            return
        streams = ctx.streams
    else:
        streams, subs = _get_play_streams(page_url, content)
        if streams is None or len(streams) == 0:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Streamy nenalezeny',
                xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
            return

    selected = open_stream_selector(streams)
    if selected is None:
        return

    if 'prehraj' in page_url:
        listitem = _play_prehrajto_selected(page_url, content, cookies, selected)
    else:
        listitem = _build_stream_listitem(selected, subs, content, page_url)
    _remember_playing(link, listitem)
    xbmc.Player().play(listitem.getPath(), listitem)


def create_premium_link(link) -> str:
    return get_prehrajto_base() + urlparse(normalize_prehrajto_url(link)).path + "?do=download"


def play_video_premium(link, cookies):
    canonical = get_prehrajto_base() + urlparse(normalize_prehrajto_url(link)).path
    res = get_session().get(canonical, headers=get_headers(), allow_redirects=True)
    remember_provider_page(res.url)
    content = res.content
    page_url = res.url

    ctx = build_prehrajto_stream_context(page_url, content, cookies)
    listitem = _resolve_prehrajto_max_playback(ctx, page_url, content, cookies)
    if listitem is not None:
        _remember_playing(link, listitem)
    xbmcplugin.setResolvedUrl(_handle, listitem is not None, listitem or xbmcgui.ListItem())

_HISTORY_META_KEYS = (
    'imdb', 'tmdb', 'mediatype', 'title', 'tvshowtitle', 'year', 'season', 'episode',
)


def _parse_video_info(raw: Any) -> Optional[dict]:
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _attach_imdb_id(params: dict) -> None:
    """Fill videoInfo with a tt id when the search came from a TMDB movie or show."""
    video_info = _parse_video_info(params.get('videoInfo'))
    if not video_info:
        return
    unique = video_info.get('uniqueid')
    if not isinstance(unique, dict):
        unique = {}
    else:
        unique = dict(unique)
    imdb = str(unique.get('imdb') or video_info.get('imdbnumber') or '').strip()
    if not imdb.startswith('tt'):
        tmdb_id = str(unique.get('tmdb') or '').strip()
        if not tmdb_id:
            return
        mediatype = str(video_info.get('mediatype') or '')
        imdb = fetch_imdb_id(tmdb_id, mediatype)
        if not imdb.startswith('tt'):
            return
    unique['imdb'] = imdb
    video_info['uniqueid'] = unique
    video_info['imdbnumber'] = imdb
    params['videoInfo'] = json.dumps(video_info)


def _history_meta_from_video_info(video_info: Optional[dict]) -> Dict[str, Any]:
    if not isinstance(video_info, dict):
        return {}
    unique = video_info.get('uniqueid')
    if not isinstance(unique, dict):
        unique = {}
    meta: Dict[str, Any] = {}
    imdb = str(unique.get('imdb') or video_info.get('imdbnumber') or '').strip()
    if imdb.startswith('tt'):
        meta['imdb'] = imdb
    tmdb_id = str(unique.get('tmdb') or '').strip()
    if tmdb_id:
        meta['tmdb'] = tmdb_id
    for key in ('mediatype', 'title', 'tvshowtitle', 'year', 'season', 'episode'):
        value = video_info.get(key)
        if value is None or value == '':
            continue
        meta[key] = value
    return meta


def _parse_history_line(line: str) -> Optional[dict]:
    text = (line or '').strip()
    if not text:
        return None
    if text.startswith('{'):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            query = str(data.get('q') or '').strip()
            if query:
                data['q'] = query
                return data
    return {'q': text}


def _load_search_history() -> List[dict]:
    if not os.path.exists(history_path):
        return []
    entries = []
    with open(history_path, 'r', encoding='utf-8') as f:
        for line in f:
            entry = _parse_history_line(line)
            if entry and entry.get('q'):
                entries.append(entry)
    return entries


def _dump_history_entry(entry: dict) -> str:
    query = str(entry.get('q') or '').strip()
    payload: Dict[str, Any] = {'q': query}
    for key in _HISTORY_META_KEYS:
        value = entry.get(key)
        if value is None or value == '':
            continue
        payload[key] = value
    if len(payload) == 1:
        return query
    return json.dumps(payload, ensure_ascii=False)


def _video_info_from_history(entry: dict) -> Optional[dict]:
    info: Dict[str, Any] = {}
    for key in ('mediatype', 'title', 'tvshowtitle', 'year', 'season', 'episode'):
        value = entry.get(key)
        if value is None or value == '':
            continue
        info[key] = value
    unique: Dict[str, str] = {}
    tmdb_id = str(entry.get('tmdb') or '').strip()
    imdb = str(entry.get('imdb') or '').strip()
    if tmdb_id:
        unique['tmdb'] = tmdb_id
    if imdb.startswith('tt'):
        unique['imdb'] = imdb
        info['imdbnumber'] = imdb
    if unique:
        info['uniqueid'] = unique
    return info or None


def history():
    entries = _load_search_history()
    if entries:
        delete_item = xbmcgui.ListItem(label='Smazat historii')
        set_list_icon(delete_item, ICON_BIN_DELETE)
        xbmcplugin.addDirectoryItem(
            _handle, get_url(action='clear_search_history'), delete_item, False,
        )
    for entry in entries:
        query = str(entry.get('q') or '').strip()
        if not query:
            continue
        list_item = xbmcgui.ListItem(label=query)
        url_kwargs = {'action': 'listing_search', 'name': query}
        video_info = _video_info_from_history(entry)
        if video_info:
            url_kwargs['videoInfo'] = json.dumps(video_info)
        xbmcplugin.addDirectoryItem(_handle, get_url(**url_kwargs), list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def clear_search_history():
    if os.path.exists(history_path):
        os.remove(history_path)
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Historie hledání smazána', xbmcgui.NOTIFICATION_INFO, 3000, sound=False,
    )
    go_to_main_menu()

def _resolve_search_query(name: str) -> Optional[str]:
    if name == "None":
        kb = xbmc.Keyboard("", 'Zadejte název filmu nebo seriálu')
        kb.doModal()
        if not kb.isConfirmed():
            return None
        q = kb.getText()
        return _normalize_search_query(q) if q else None
    return _normalize_search_query(name)


def _listing_search_name_from_params(params: dict) -> str:
    """Stable search contract for external players: name|query|title|search|q."""
    for key in ('name', 'query', 'title', 'search', 'q'):
        value = params.get(key)
        if value is None:
            continue
        text = unquote(str(value)).strip()
        if text:
            return text
    return 'None'


def _normalize_search_query(text: str) -> str:
    return unidecode(text.strip())


def _save_search_history(q: str, video_info: Optional[dict] = None) -> None:
    entry_q = _normalize_search_query(q)
    if not entry_q:
        return

    incoming = {'q': entry_q}
    incoming.update(_history_meta_from_video_info(video_info))

    kept = []
    previous = None
    for entry in _load_search_history():
        existing_q = _normalize_search_query(str(entry.get('q') or ''))
        if not existing_q:
            continue
        if existing_q == entry_q:
            previous = entry
            continue
        entry['q'] = existing_q
        kept.append(entry)

    if previous is not None and not str(incoming.get('imdb') or '').startswith('tt'):
        merged = dict(previous)
        merged['q'] = entry_q
    else:
        merged = {'q': entry_q}
        for key in _HISTORY_META_KEYS:
            value = incoming.get(key)
            if value is None or value == '':
                continue
            merged[key] = value

    kept.insert(0, merged)
    kept = kept[:10]

    with open(history_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(_dump_history_entry(entry) for entry in kept) + '\n')


def _listing_provider_icon(list_item: xbmcgui.ListItem) -> str:
    path = ''
    try:
        path = (list_item.getPath() or '').lower()
    except (AttributeError, RuntimeError, TypeError):
        path = ''
    if 'hellspy' in path:
        icon_name = 'hellspy.png'
    elif 'sledujteto' in path:
        icon_name = 'sledujteto.jpg'
    else:
        icon_name = 'prehrajto.png'
    return icons_path + icon_name


def _art_value(list_item: xbmcgui.ListItem, key: str) -> str:
    try:
        return (list_item.getArt(key) or '').strip()
    except (AttributeError, RuntimeError, TypeError):
        return ''


def _apply_search_listing_art(list_item: xbmcgui.ListItem) -> None:
    """Apply poster/thumb after search — setArt during scrape blocks ~300ms per item on Kodi.

    A thumbnail from the stream page wins over the movie/series poster passed in with the search.
    That poster stays only when the result has no thumbnail of its own.
    """
    if not list_item:
        return
    stream_thumb = (list_item.getProperty(LISTING_THUMB_PROP) or '').strip()
    if stream_thumb:
        apply_art(list_item, {
            'thumb': stream_thumb,
            'poster': stream_thumb,
            'icon': stream_thumb,
        })
        return
    existing_thumb = _art_value(list_item, 'thumb')
    if existing_thumb:
        if not _art_value(list_item, 'poster'):
            apply_art(list_item, {'poster': existing_thumb})
        return
    if not _art_value(list_item, 'icon'):
        apply_art(list_item, {'icon': _listing_provider_icon(list_item)})


def _apply_search_listing_metadata(list_item: xbmcgui.ListItem) -> None:
    """Art + stream info at directory build (not during Prehrajto scrape)."""
    if not list_item:
        return
    _apply_search_listing_art(list_item)
    apply_deferred_listing_stream_info(list_item)


def _render_search_results(
        videos: List[xbmcgui.ListItem], name: str, params,
        from_cache: bool = False, cached_count: Optional[int] = None,
) -> None:
    try:
        xbmcplugin.setContent(_handle, 'videos')
    except (AttributeError, RuntimeError, TypeError):
        pass
    category = (name or '').strip()
    if category:
        try:
            xbmcplugin.setPluginCategory(_handle, category)
        except (AttributeError, RuntimeError, TypeError):
            pass

    if is_cache_enabled() or from_cache:
        refresh_label = 'Vynutit obnovení'
        if from_cache and cached_count:
            refresh_label = f'Vynutit obnovení ({cached_count} výsledků)'
        refresh_item = xbmcgui.ListItem(label=refresh_label)
        refresh_item.setProperty('IsPlayable', 'false')
        set_list_icon(refresh_item, ICON_REFRESH)
        refresh_params = {
            k: v for k, v in (params or {}).items()
            if k not in ('action', 'name', 'force_refresh')
        }
        refresh_params['force_refresh'] = '1'
        refresh_url = get_url(action='listing_search', name=name, **refresh_params)
        xbmcplugin.addDirectoryItem(_handle, refresh_url, refresh_item, False)
        if from_cache:
            dprint('search(): results loaded from cache')

    dprint('search(): found: ' + str(len(videos or [])))
    videos = group_search_results(list(videos or []))
    for vid_item in videos:
        if not vid_item:
            continue
        list_item = vid_item

        if is_source_no_results_item(list_item) or is_provider_header_item(list_item):
            xbmcplugin.addDirectoryItem(_handle, '', list_item, False)
            continue

        if params:
            video_info_raw = params.get('videoInfo')
            if video_info_raw:
                try:
                    video_info = json.loads(video_info_raw)
                    if isinstance(video_info, dict):
                        maybe_highlight_fake_stream_in_listitem(
                            list_item, video_info, g_highlight_fake_streams
                        )
                        apply_video_info(list_item, video_info)
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    dprint('search(): videoInfo: ' + str(e))
            art_raw = params.get('art')
            if art_raw:
                try:
                    art = json.loads(art_raw)
                    if isinstance(art, dict):
                        merged = {k: v for k, v in art.items() if v}
                        stream_thumb = (list_item.getProperty(LISTING_THUMB_PROP) or '').strip()
                        if stream_thumb:
                            merged.pop('thumb', None)
                            merged.pop('poster', None)
                            merged.pop('icon', None)
                        elif hasattr(list_item, 'getArt'):
                            for key in ('thumb', 'poster', 'icon', 'fanart', 'landscape'):
                                try:
                                    cur = list_item.getArt(key)
                                except (AttributeError, RuntimeError, TypeError):
                                    cur = None
                                if cur:
                                    merged[key] = cur
                        apply_art(list_item, merged)
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    dprint('search(): art: ' + str(e))

        list_item.setProperty('IsPlayable', 'false')
        if display_provider_headers():
            label = list_item.getLabel() or ''
            if not label.startswith('  '):
                list_item.setLabel('  ' + label)
        _apply_search_listing_metadata(list_item)
        vid_url = vid_item.getPath()
        if not vid_url:
            continue
        apply_context_menu_items(list_item, build_video_context_menu_items(_url, vid_url))
        url = _resume_or_play_url(vid_url)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, False)

    search_var_item = xbmcgui.ListItem(label='Změnit hledaný výraz')
    search_var_item.setProperty('IsPlayable', 'false')
    # Keep videoInfo (IMDb id, season, episode) when the query is shortened or translated.
    sv_params = {
        k: v for k, v in (params or {}).items()
        if k not in ('action', 'name', 'force_refresh', 'params') and v not in (None, '')
    }
    sv_url = get_url(action='search_variant', name=name, **sv_params)
    xbmcplugin.addDirectoryItem(_handle, sv_url, search_var_item, True)

    xbmcplugin.endOfDirectory(_handle)


def search(name, params=None):
    q = _resolve_search_query(name)
    if q is None:
        return

    if not isinstance(params, dict):
        params = {}
    _attach_imdb_id(params)

    dprint(f'Search(): ' + q)
    _save_search_history(q, _parse_video_info(params.get('videoInfo')))

    cache_key = make_cache_key(q)
    force_refresh = (params or {}).get('force_refresh') == '1'
    if force_refresh:
        invalidate(cache_key)

    videos: Optional[List[xbmcgui.ListItem]] = None
    from_cache = False

    videos = try_load_cache(cache_key, force_refresh=force_refresh)
    from_cache = videos is not None

    need_listing_upload_dates = bool(
        g_highlight_fake_streams
        and params
        and params.get('videoInfo')
    )

    search_meta = None
    if not from_cache:
        videos, search_meta = _provider.search(
            q, need_listing_upload_dates=need_listing_upload_dates,
        )
        if videos and search_meta.is_complete and is_cache_enabled():
            set_cached(cache_key, videos, search_meta.pages_scraped)
        elif videos and search_meta:
            if not is_cache_enabled():
                dprint(
                    f'search_cache: not stored (cache disabled) items={len(videos)} '
                    f'pages={search_meta.pages_scraped}'
                )
            elif not search_meta.is_complete:
                dprint(
                    f'search_cache: not stored (incomplete) items={len(videos)} '
                    f'pages={search_meta.pages_scraped} cancelled={search_meta.cancelled}'
                )

    if not videos:
        if name.count(' ') == 0:
            xbmcgui.Dialog().notification(_ADDON_NAME, "Nenalezeno:\r\n" + q, xbmcgui.NOTIFICATION_INFO, 4000,
                                          sound=False)
            return

        new_search = search_variants_dialog(name)
        if new_search is not None:
            search(new_search, params)

        return

    set_last_listing_key(cache_key)
    cached_count = get_cached_item_count(cache_key) if from_cache else None
    _render_search_results(
        videos, name, params, from_cache=from_cache, cached_count=cached_count,
    )

def search_variant(name: str, params):
    new_search = search_variants_dialog(name)
    if new_search is not None:
        search(new_search, params)

def menu():
    downloads_label = get_downloads_root_label()
    queue_label = get_download_queue_root_label()
    if os.path.exists(history_path):
        name_list = [("Hledat", "listing_search", "None", ""), ("Historie hledání", "listing_history", "None", ""),
                     ("Filmy", "listing_movie_category", "", ""), ("Seriály", "listing_serie_category", "", ""),
                     (downloads_label, "listing_downloads", "", ""),
                     (queue_label, "listing_download_queue", "", "")]
    else:
        name_list = [("Hledat", "listing_search", "None", ""), ("Filmy", "listing_movie_category", "", ""),
                     ("Seriály", "listing_serie_category", "", ""), (downloads_label, "listing_downloads", "", ""),
                     (queue_label, "listing_download_queue", "", "")]
    menu_icons = {
        'listing_search': 'search.png',
        'listing_history': 'history.png',
        'listing_movie_category': 'movies.png',
        'listing_serie_category': 'series.png',
        'listing_downloads': 'downloads.png',
        'listing_download_queue': 'queue.png',
    }
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category[0])
        url = get_url(action=category[1], name=category[2], type=category[3])
        _set_menu_icon(list_item, menu_icons[category[1]])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)

    lang_item = xbmcgui.ListItem(label=get_tmdb_language_menu_label())
    lang_item.setProperty('IsPlayable', 'false')
    _set_menu_icon(lang_item, 'language.png')
    xbmcplugin.addDirectoryItem(
        _handle, get_url(action='pick_tmdb_language'), lang_item, False)

    if is_csfd_menu_enabled():
        xbmcplugin.addDirectoryItem(_handle, '', get_CSFD_item(), isFolder=True)

    accounts_item = xbmcgui.ListItem(label='Účty')
    _set_menu_icon(accounts_item, 'account.png')
    xbmcplugin.addDirectoryItem(_handle, get_url(action='accounts_menu'), accounts_item, True)

    settings_item = xbmcgui.ListItem(label='Nastavení')
    settings_item.setProperty('IsPlayable', 'false')
    _set_menu_icon(settings_item, 'settings.png')
    xbmcplugin.addDirectoryItem(_handle, get_url(action='open_settings'), settings_item, False)

    xbmcplugin.endOfDirectory(_handle)


def _set_menu_icon(list_item, filename: str) -> None:
    icon = icons_path + filename
    list_item.setArt({'thumb': icon, 'icon': icon, 'poster': icon})


def accounts_menu():
    if g_is_prehrajto_enabled:
        prehrajto_item = xbmcgui.ListItem(label=get_account_root_label(PROVIDER_PREHRAJTO))
        prehrajto_icon = icons_path + 'prehrajto.png'
        prehrajto_item.setArt({'thumb': prehrajto_icon, 'icon': prehrajto_icon, 'fanart': prehrajto_icon})
        xbmcplugin.addDirectoryItem(
            _handle, get_url(action='account_menu', provider=PROVIDER_PREHRAJTO), prehrajto_item, True)

    if g_is_sledujteto_enabled:
        sledujteto_item = xbmcgui.ListItem(label=get_account_root_label(PROVIDER_SLEDUJTETO))
        sledujteto_icon = icons_path + 'sledujteto.jpg'
        sledujteto_item.setArt({'thumb': sledujteto_icon, 'icon': sledujteto_icon, 'fanart': sledujteto_icon})
        xbmcplugin.addDirectoryItem(
            _handle, get_url(action='account_menu', provider=PROVIDER_SLEDUJTETO), sledujteto_item, True)

    if g_is_hellspy_enabled:
        hellspy_item = xbmcgui.ListItem(label=get_account_root_label(PROVIDER_HELLSPY))
        hellspy_icon = icons_path + 'hellspy.png'
        hellspy_item.setArt({'thumb': hellspy_icon, 'icon': hellspy_icon, 'fanart': hellspy_icon})
        xbmcplugin.addDirectoryItem(
            _handle, get_url(action='account_menu', provider=PROVIDER_HELLSPY), hellspy_item, True)

    xbmcplugin.endOfDirectory(_handle)

def get_CSFD_item() -> xbmcgui.ListItem:
    name = 'CSFD'
    icon = images_path + 'CSFD.png'
    list_item = xbmcgui.ListItem(label=name)
    apply_video_info(list_item, {
        'title': name,
        'plot': name,
    })
    apply_art(list_item, {'thumb': icon, 'icon': icon, 'poster': icon, 'fanart': icon})
    list_item.setProperty('IsPlayable', 'false')
    return list_item

def home():
    xbmc.executebuiltin("Dialog.Close(all, true)")  # Zavře všechna okna/dialogy
    xbmc.executebuiltin(f"RunPlugin(plugin://{_ADDON_ID}/)")  # Spustí kořenovou stránku doplňku
    # xbmc.executebuiltin("ActivateWindow(Home)")  # Go to Kodi's main menu
    # xbmc.executebuiltin("Container.Update(plugin://plugin.video.bacprehrajto/, replace)")  # Go to root


def copy_to_clipboard(text: str) -> None:
    dprint(f'copy_to_clipboard(): ' + text)
    ClipboardUtils.copy_to_clipboard(text)


def delete_subtitles(
        subs: List[SubData], name_wo_ext: str,
        use_name_as_subfolder: bool = False,
        all_except_name: bool = False,
        path: str = g_download_path
):
    if subs is None or len(subs) == 0:
        return

    if use_name_as_subfolder:
        path = path + "/" + name_wo_ext

    try:
        if all_except_name:
            # TODO.
            os.chdir(path)
            for item in os.listdir(os.getcwd()):
                if item != name_wo_ext:
                    os.remove(item)
        else:
            for sub in subs:
                name_prefix = "" if use_name_as_subfolder else (name_wo_ext + "-")
                #name_size_suffix = (name_wo_ext + "-") if use_name_as_subfolder else ""
                name_subtitles = name_prefix + sub.label + ".srt"
                os.remove(path + name_subtitles)
            os.remove(path)
    except Exception as e:
        dprint('delete_subtitles(): could not delete subtitles:\n' + str(e))
        return


def _notify_missing_search_title() -> None:
    xbmcgui.Dialog().notification(
        _ADDON_NAME,
        'Nelze zjistit název pro hledání',
        xbmcgui.NOTIFICATION_INFO,
        3000,
        sound=False,
    )


def _zero_pad_index(value) -> str:
    try:
        return str(int(value)).zfill(2)
    except (TypeError, ValueError):
        return str(value or '00').zfill(2)


def search_in_language(params: dict) -> None:
    """Search one movie or episode using its title in the requested TMDB language."""
    lang = (params.get('lang') or '').strip().lower()
    media = (params.get('media') or '').strip().lower()
    tmdb_id = (params.get('tmdb_id') or '').strip()
    title = ''
    if lang and tmdb_id and media in ('movie', 'tv'):
        title = fetch_localized_title(media, tmdb_id, lang)
    if not title:
        _notify_missing_search_title()
        return

    if media == 'movie':
        year = (params.get('year') or '').strip()
        query = f'{title} {year}'.strip()
    else:
        season_z = _zero_pad_index(params.get('season'))
        ep_z = _zero_pad_index(params.get('episode'))
        query = f'{title} S{season_z}E{ep_z}'.strip()

    extra = {}
    if params.get('videoInfo'):
        extra['videoInfo'] = params['videoInfo']
    if params.get('art'):
        extra['art'] = params['art']
    open_search(query, extra)


def show_nsfw_filter_help() -> None:
    xbmcgui.Dialog().textviewer(
        'NSFW',
        'Filtrování je zapnuté, dokud není zaškrtnuté Include NSFW videos.\n\n'
        'Výsledek se skryje, když jeho název obsahuje některé z klíčových slov. '
        'Na velikosti písmen nezáleží a více mezer se bere jako jedna. '
        'Hledá se část textu, takže slovo „xxx“ skryje i „xxxfile“.\n\n'
        'Platí zabudovaný seznam slov. Další slova se píší do pole Další filtry, oddělená čárkou.\n\n'
        'Výjimka pustí název jen tehdy, když se její text v názvu vyskytuje a každé nalezené '
        'klíčové slovo je součástí některé takové výjimky. Výjimka „xxx“ tedy nechá „xXx“. '
        'Název „xxx porn“ zůstane skrytý, protože „porn“ výjimka „xxx“ nepokrývá.\n\n'
        'Platí pro vyhledávání u všech poskytovatelů, včetně výsledků z mezipaměti. '
        'Vlastní videa v Moje videa se nefiltrují.',
    )
    xbmcplugin.endOfDirectory(_handle, succeeded=False)


def router(paramstring):
    params = dict(parse_qsl(paramstring))
    if params:
        if params["action"] == "home":
            home()
        elif params["action"] == "accounts_menu":
            accounts_menu()
        elif params["action"] == "nsfw_filter_help":
            show_nsfw_filter_help()
        elif params["action"] == "open_settings":
            addon.openSettings()
            xbmcplugin.endOfDirectory(_handle, succeeded=False)
        elif params["action"] == "pick_tmdb_language":
            new_lang = pick_tmdb_active_language_dialog()
            if new_lang:
                xbmcgui.Dialog().notification(
                    _ADDON_NAME,
                    f'TMDB jazyk: {new_lang.upper()}',
                    xbmcgui.NOTIFICATION_INFO,
                    2500,
                    sound=False,
                )
            go_to_main_menu()
        elif params["action"] == "pick_tmdb_language_refresh":
            new_lang = pick_tmdb_active_language_dialog()
            if new_lang:
                xbmcgui.Dialog().notification(
                    _ADDON_NAME,
                    f'TMDB jazyk: {new_lang.upper()}',
                    xbmcgui.NOTIFICATION_INFO,
                    2500,
                    sound=False,
                )
                xbmc.executebuiltin('Container.Refresh')
            xbmcplugin.endOfDirectory(_handle, succeeded=False)
        elif params["action"] == "search_in_language":
            search_in_language(params)
            xbmcplugin.endOfDirectory(_handle, succeeded=False)
        elif params["action"] == "listing_search":
            search(_listing_search_name_from_params(params), params)
        elif params["action"] == "search_variant":
            search_variant(params["name"], params)
        elif params["action"] == "listing_history":
            history()
        elif params["action"] == "clear_search_history":
            clear_search_history()
        elif params["action"] in ("listing_downloads", "listing_download_queue", "play_local",
                                  "delete_download", "delete_selected_downloads", "delete_all_downloads", "delete_subtitle_files",
                                  "download_cancel", "download_remove", "download_queue_resume",
                                  "download_service_stop", "download_service_start", "download_queue_now",
                                  "download_queue_clear", "local_file_actions", "queue_job_actions"):
            downloads_router(_handle, _url, params)
        elif params["action"] in (
                "account_menu", "account_login", "account_logout",
                "account_my_videos", "account_watchlist", "account_listing",
                "account_hellspy_visibility",
        ):
            account_router(_handle, _url, params)
        elif params["action"].__contains__("listing_") or params["action"] == "search_tmdb":
            tmdb_router(_handle, _url, params)
        elif params["action"] == "select_stream":
            select_and_play_stream(params["link"])
        elif params["action"] == "resume_or_play":
            link = params["link"]
            if _take_list_resolve(link):
                _start_play_action(link, params)
            elif _clicked_link_is_playing(link):
                _show_playing_fullscreen()
            else:
                _claim_list_resolve(link)
                _play_listed_url(_resume_or_play_url(link, params.get('publish') or ''))
        elif params["action"] == "play":
            _start_play_action(params["link"], params)
        elif params["action"] == "library":
            if addon.getSetting("library") == "":
                xbmcgui.Dialog().notification(
                    _ADDON_NAME, "Nastavte složku pro knihovnu",
                    xbmcgui.NOTIFICATION_ERROR, 3000
                )
                return
            parsed1 = urlparse(params["url"]).path
            name = parsed1.split("/")[1]
            kb = xbmc.Keyboard(name.replace("-", " "), 'Zadejte název a rok filmu')
            kb.doModal()
            if not kb.isConfirmed():
                return
            q = kb.getText()
            if q == "":
                return
            f = open(addon.getSetting("library") + q + ".strm", "w")
            f.write("plugin://plugin.video.bacprehrajto/?action=play&link=" + params["url"])
            f.close()
            xbmcgui.Dialog().notification(_ADDON_NAME, "Uloženo", xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
        elif params["action"] == "qr":
            page_url = params["url"]
            res = requests.get(page_url, headers=get_headers(), allow_redirects=True)
            content = res.content
            final_url = res.url
            streams, _subs = _provider.get_streams_data(final_url, content)
            if streams is None or len(streams) == 0:
                xbmcgui.Dialog().notification(
                    _ADDON_NAME, "Streamy nenalezeny", xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
                return
            selected = pick_stream(streams)
            if selected is None:
                return

            qr_link = "https://quickchart.io/qr?text=" + selected.path.replace('&', '%26')
            dprint("qr: " + qr_link)
            xbmc.executebuiltin('ShowPicture(' + qr_link + ')')
        elif params["action"] == "copy_url":
            copy_to_clipboard(params["url"])
        elif params["action"] == "download":
            download_direct(params["url"])
        elif params["action"] == "download_background":
            enqueue_background_download(params["url"])
        elif params["action"] == "download_enqueue":
            enqueue_to_queue_only(params["url"])
        elif params["action"] == "video_actions":
            show_video_actions_menu(_url, params["url"])
    else:
        menu()


if __name__ == '__main__':
    router(sys.argv[2][1:])
