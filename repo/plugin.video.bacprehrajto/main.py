# -*- coding: utf-8 -*-

import json
import os
import sys
from typing import List, Optional, Tuple
from urllib.parse import parse_qsl, unquote
from urllib.parse import urlparse

import requests
import unicodedata
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from common import _ADDON_ID, addon, g_max_searched_vids, g_download_path, g_quality_selector, \
    history_path, \
    get_headers, cache_path, images_path, icons_path, _ADDON_NAME, get_prehrajto_base, normalize_prehrajto_url, \
    g_highlight_fake_streams, \
    g_is_prehrajto_enabled, g_is_sledujteto_enabled, ICON_DOWNLOAD, ICON_BIN_DELETE, ICON_REFRESH, set_list_icon, \
    go_to_main_menu
from model.QS import QS
from model.StreamData import StreamData
from model.SubData import SubData
from modules.SplitSelectorDialog import search_variants_dialog
from providers.UniversalProvider import UniversalProvider
from providers.prehrajto.auth import ensure_premium
from providers.prehrajto.download import resolve_premium_download_url
from providers.prehrajto.playback_context import (
    build_prehrajto_stream_context,
    resolve_stream_path_for_playback,
    resolve_subtitles_for_selection,
)
from providers.browsing_context import remember_provider_page
from providers.prehrajto.session import get_session, has_auth_cookies
from account.account_menu import PROVIDER_PREHRAJTO, PROVIDER_SLEDUJTETO, get_account_root_label
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
from tmdb.tmdb_router import tmdb_router
from unidecode.unidecode import unidecode
from utils.ClipboardUtils import ClipboardUtils
from utils.stream_fake_hint import maybe_highlight_fake_stream_in_listitem
from utils.video_actions_menu import show_video_actions_menu
from utils.utils import dprint, \
    urlencode, apply_stream_headers, apply_context_menu_items, build_video_context_menu_items

_url = sys.argv[0]
_handle = int(sys.argv[1])

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


def _play_prehrajto_selected(
        page_url: str,
        content: bytes,
        cookies,
        selected: StreamData,
) -> xbmcgui.ListItem:
    ctx = build_prehrajto_stream_context(page_url, content, cookies)
    subs = resolve_subtitles_for_selection(ctx, selected)
    selected = resolve_stream_path_for_playback(ctx, selected)
    return _build_stream_listitem(selected, subs, content, page_url)


def _sledujteto_cookie_header() -> Optional[str]:
    if not g_is_sledujteto_enabled:
        return None
    try:
        from providers.sledujteto.session import get_session
        parts = [f'{c.name}={c.value}' for c in get_session().cookies if c.value]
        return '; '.join(parts) if parts else None
    except Exception:
        return None


def _build_stream_listitem(
        stream: StreamData,
        subs: Optional[List[SubData]],
        page_content: bytes,
        page_url: str,
) -> xbmcgui.ListItem:
    listitem = xbmcgui.ListItem(path=stream.path)

    cookies = _sledujteto_cookie_header() if 'sledujteto' in stream.path else None
    apply_stream_headers(listitem, stream.headers, cookies=cookies)

    referer = page_url if 'prehraj' in page_url else None
    sub_paths = subtitle_paths_for_playback(subs, referer=referer)
    if sub_paths:
        listitem.setSubtitles(sub_paths)
    return listitem


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
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return
        ctx = build_prehrajto_stream_context(page_url, content, cookies)
        premium = _first_premium_stream(ctx.streams)
        if premium is None:
            dprint('play_video(): premium stream unavailable (login required?)')
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return
        subs = resolve_subtitles_for_selection(ctx, premium)
        premium = resolve_stream_path_for_playback(ctx, premium)
        if not premium.path:
            dprint('play_video(): premium link unavailable')
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return
        dprint('play_video(): premium link: ' + premium.path)
        listitem = _build_stream_listitem(premium, subs, content, page_url)
        xbmcplugin.setResolvedUrl(_handle, True, listitem)
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
            if 'prehraj' in page_url:
                listitem = _play_prehrajto_selected(page_url, content, cookies, selected)
            else:
                listitem = _build_stream_listitem(selected, subs, content, page_url)
            xbmcplugin.setResolvedUrl(_handle, True, listitem)
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
            xbmcplugin.setResolvedUrl(_handle, True, listitem)


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
    premium = _first_premium_stream(ctx.streams)
    if premium is None:
        dprint('play_video_premium(): premium stream not in list')
        return

    subs = resolve_subtitles_for_selection(ctx, premium)
    premium = resolve_stream_path_for_playback(ctx, premium)
    if not premium.path:
        dprint('play_video_premium(): Location header missing')
        return

    listitem = _build_stream_listitem(premium, subs, content, page_url)
    xbmcplugin.setResolvedUrl(_handle, True, listitem)

def history():
    name_list = []
    if os.path.exists(history_path):
        name_list = open(history_path, "r", encoding="utf-8").read().splitlines()
    if name_list:
        delete_item = xbmcgui.ListItem(label='Smazat historii')
        set_list_icon(delete_item, ICON_BIN_DELETE)
        xbmcplugin.addDirectoryItem(
            _handle, get_url(action='clear_search_history'), delete_item, False,
        )
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category)
        url = get_url(action='listing_search', name=category)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
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


def _normalize_search_query(text: str) -> str:
    return unidecode(text.strip())


def _save_search_history(q: str) -> None:
    entry = _normalize_search_query(q)
    if not entry:
        return

    entries = []
    if os.path.exists(history_path):
        with open(history_path, 'r', encoding='utf-8') as f:
            entries = [line.strip() for line in f if line.strip()]

    if entry in entries:
        entries.remove(entry)
    entries.insert(0, entry)
    entries = entries[:10]

    with open(history_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(entries) + '\n')


def _render_search_results(
        videos: List[xbmcgui.ListItem], name: str, params,
        from_cache: bool = False, cached_count: Optional[int] = None,
) -> None:
    xbmcplugin.setContent(_handle, 'videos')

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

    dprint('search(): found: ' + str(len(videos)))
    for vid_item in videos[:int(g_max_searched_vids)]:
        list_item = vid_item

        if params:
            video_info_raw = params.get("videoInfo")
            if video_info_raw:
                try:
                    video_info = json.loads(video_info_raw)
                    maybe_highlight_fake_stream_in_listitem(
                        list_item, video_info, g_highlight_fake_streams
                    )
                    list_item.setInfo("video", video_info)
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    dprint("search(): videoInfo: " + str(e))
            art_raw = params.get("art")
            if art_raw:
                try:
                    art = json.loads(art_raw)
                    merged = dict(art)
                    if hasattr(list_item, "getArt"):
                        for key in ("thumb", "poster", "icon", "fanart"):
                            cur = list_item.getArt(key)
                            if cur:
                                merged[key] = cur
                    list_item.setArt(merged)
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    dprint("search(): art: " + str(e))

        list_item.setProperty('IsPlayable', 'true')
        vid_url = vid_item.getPath()
        apply_context_menu_items(list_item, build_video_context_menu_items(_url, vid_url))
        url = get_url(action='play', link=vid_url)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, False)

    search_var_item = xbmcgui.ListItem(label='Změnit hledaný výraz')
    search_var_item.setProperty('IsPlayable', 'false')
    sv_url = get_url(action='search_variant', name=name, params=params)
    xbmcplugin.addDirectoryItem(_handle, sv_url, search_var_item, True)

    xbmcplugin.endOfDirectory(_handle)


def search(name, params=None):
    q = _resolve_search_query(name)
    if q is None:
        return

    dprint(f'Search(): ' + q)
    _save_search_history(q)

    cache_key = make_cache_key(q)
    force_refresh = (params or {}).get('force_refresh') == '1'
    if force_refresh:
        invalidate(cache_key)

    videos: Optional[List[xbmcgui.ListItem]] = None
    from_cache = False

    videos = try_load_cache(cache_key, force_refresh=force_refresh)
    from_cache = videos is not None

    search_meta = None
    if not from_cache:
        videos, search_meta = _provider.search(q)
        if videos and search_meta.is_complete:
            set_cached(cache_key, videos, search_meta.pages_scraped)
        elif videos and search_meta:
            dprint(
                f'search_cache: skip incomplete items={len(videos)} '
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
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category[0])
        url = get_url(action=category[1], name=category[2], type=category[3])
        if category[1] in ('listing_downloads', 'listing_download_queue'):
            set_list_icon(list_item, ICON_DOWNLOAD)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)

    xbmcplugin.addDirectoryItem(_handle, '', get_CSFD_item(), isFolder=True)

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

    xbmcplugin.endOfDirectory(_handle)

def get_CSFD_item() -> xbmcgui.ListItem:
    name = 'CSFD'
    icon = images_path + 'CSFD.png'
    plot = ''
    list_item = xbmcgui.ListItem(label=name)
    list_item.setInfo('video', {
                          'title': name,
                          'plot': plot or name,
                          # 'mediatype': 'video'
                      })
    list_item.setArt({'thumb': icon, 'icon': icon, 'fanart': icon})
    list_item.setProperty('IsPlayable', 'true')
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


def router(paramstring):
    params = dict(parse_qsl(paramstring))
    if params:
        if params["action"] == "home":
            home()
        if params["action"] == "listing_search":
            search(params["name"], params)
        if params["action"] == "search_variant":
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
                "account_my_videos", "account_watchlist",
        ):
            account_router(_handle, _url, params)
        elif params["action"].__contains__("listing_") or params["action"] == "search_tmdb":
            tmdb_router(_handle, _url, params)
        elif params["action"] == "select_stream":
            select_and_play_stream(params["link"])
        elif params["action"] == "play":
            mark_play_return()
            link = params["link"]
            if 'prehraj' in link and g_is_prehrajto_enabled:
                premium, cookies = get_premium()
                if premium == 1 and g_quality_selector == QS.Max:
                    play_video_premium(link, cookies)
                else:
                    play_video(link)
            else:
                play_video(link)
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
