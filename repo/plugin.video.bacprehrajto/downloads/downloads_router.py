from typing import Dict
from urllib.parse import unquote

import xbmcgui
import xbmcplugin

from common import _ADDON_NAME, ICON_BIN_DELETE, go_to_main_menu
from downloads.downloads_menu import refresh_downloads_menu, show_downloads_menu
from downloads.download_queue_menu import (
    handle_download_cancel,
    handle_download_queue_clear,
    handle_download_queue_now,
    handle_download_queue_resume,
    handle_download_remove,
    handle_download_service_start,
    handle_download_service_stop,
    handle_queue_job_actions,
    show_download_queue_menu,
)
from utils.action_menu import open_icon_action_menu
from downloads.downloads_utils import (
    delete_all_downloads,
    delete_all_subtitle_files,
    delete_video_and_subs,
    find_subtitles_for_video,
    format_list_size,
    format_subtitle_total_size,
    get_total_occupied_size,
    scan_downloads,
    scan_subtitle_files,
)


def play_local_file(_handle: int, file_path: str) -> None:
    import os
    if not os.path.isfile(file_path):
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Soubor nenalezen',
            xbmcgui.NOTIFICATION_ERROR, 3000, sound=False)
        return

    listitem = xbmcgui.ListItem(path=file_path)
    sub_paths = find_subtitles_for_video(file_path)
    if sub_paths:
        listitem.setSubtitles(sub_paths)
    xbmcplugin.setResolvedUrl(_handle, True, listitem)


def handle_delete_download(_handle, _url: str, file_path: str) -> None:
    import os
    name = os.path.basename(file_path)
    if not xbmcgui.Dialog().yesno(_ADDON_NAME, f'Smazat soubor?\n{name}'):
        show_downloads_menu(_handle, _url)
        return

    delete_video_and_subs(file_path)
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Soubor smazán',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    refresh_downloads_menu(_url)


def handle_delete_selected(_handle, _url: str) -> None:
    entries = scan_downloads()
    if not entries:
        show_downloads_menu(_handle, _url)
        return

    list_items = []
    for entry in entries:
        item = xbmcgui.ListItem(
            label=entry.name,
            label2=format_list_size(entry.size_bytes),
        )
        list_items.append(item)

    selected = xbmcgui.Dialog().multiselect(
        'Smazat vybrané',
        list_items,
        useDetails=True,
    )
    if selected is None:
        refresh_downloads_menu(_url)
        return
    if not selected:
        refresh_downloads_menu(_url)
        return

    count = len(selected)
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME, f'Smazat {count} vybraných souborů včetně titulků?'):
        refresh_downloads_menu(_url)
        return

    deleted = 0
    for index in selected:
        if 0 <= index < len(entries):
            delete_video_and_subs(entries[index].path)
            deleted += 1

    xbmcgui.Dialog().notification(
        _ADDON_NAME, f'Smazáno {deleted} souborů',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    refresh_downloads_menu(_url)


def handle_delete_all(_handle, _url: str) -> None:
    total = get_total_occupied_size()
    if total == 0:
        show_downloads_menu(_handle, _url)
        return

    size_label = format_list_size(total)
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME, f'Smazat všechny stažené soubory včetně titulků ({size_label})?'):
        show_downloads_menu(_handle, _url)
        return

    deleted, _ = delete_all_downloads()
    xbmcgui.Dialog().notification(
        _ADDON_NAME, f'Smazáno {deleted} souborů',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    go_to_main_menu()


def handle_delete_subtitles(_handle, _url: str) -> None:
    info = scan_subtitle_files()
    if info.count == 0:
        show_downloads_menu(_handle, _url)
        return

    size_label = format_subtitle_total_size(info.total_bytes)
    if not xbmcgui.Dialog().yesno(
            _ADDON_NAME, f'Smazat {info.count} souborů titulků ({size_label})?'):
        show_downloads_menu(_handle, _url)
        return

    deleted, _ = delete_all_subtitle_files()
    xbmcgui.Dialog().notification(
        _ADDON_NAME, f'Smazáno {deleted} titulků',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    refresh_downloads_menu(_url)


def handle_local_file_actions(_handle: int, _url: str, file_path: str) -> None:
    open_icon_action_menu('Akce k souboru', [
        ('Smazat', ICON_BIN_DELETE, lambda: handle_delete_download(_handle, _url, file_path)),
    ])


def downloads_router(_handle: int, _url: str, params: Dict) -> None:
    action = params.get('action', '')
    if action == 'listing_downloads':
        show_downloads_menu(_handle, _url)
    elif action == 'listing_download_queue':
        show_download_queue_menu(_handle, _url)
    elif action == 'download_cancel':
        handle_download_cancel(_url, params.get('job_id', ''))
    elif action == 'download_remove':
        handle_download_remove(_url, params.get('job_id', ''))
    elif action == 'download_queue_resume':
        handle_download_queue_resume(_url)
    elif action == 'download_service_stop':
        handle_download_service_stop(_url)
    elif action == 'download_service_start':
        handle_download_service_start(_url)
    elif action == 'download_queue_now':
        handle_download_queue_now(_url)
    elif action == 'download_queue_clear':
        handle_download_queue_clear(_url)
    elif action == 'play_local':
        play_local_file(_handle, unquote(params.get('path', '')))
    elif action == 'delete_download':
        handle_delete_download(_handle, _url, unquote(params.get('path', '')))
    elif action == 'delete_selected_downloads':
        handle_delete_selected(_handle, _url)
    elif action == 'delete_all_downloads':
        handle_delete_all(_handle, _url)
    elif action == 'delete_subtitle_files':
        handle_delete_subtitles(_handle, _url)
    elif action == 'local_file_actions':
        handle_local_file_actions(_handle, _url, unquote(params.get('path', '')))
    elif action == 'queue_job_actions':
        handle_queue_job_actions(_url, params.get('job_id', ''))
