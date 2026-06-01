from urllib.parse import quote

import xbmc
import xbmcgui
import xbmcplugin

from common import _ADDON_NAME, ICON_BIN_DELETE, ICON_DOWNLOAD, set_list_icon, icons_path
from downloads.downloads_utils import (
    format_list_size,
    format_subtitle_total_size,
    get_download_folder,
    get_total_occupied_size,
    scan_downloads,
    scan_subtitle_files,
)
from utils.action_menu import open_icon_action_menu
from utils.utils import apply_context_menu_items, build_local_file_context_menu_items, get_url


def _add_info_item(_handle, label: str) -> None:
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'false')
    xbmcplugin.addDirectoryItem(_handle, '', item, False)


def show_downloads_menu(_handle, _url: str) -> None:
    folder = get_download_folder()
    if folder is None:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Nastavte složku pro stahování',
            xbmcgui.NOTIFICATION_ERROR, 4000)
        xbmcplugin.endOfDirectory(_handle)
        return

    entries = scan_downloads()
    total_size = get_total_occupied_size()
    subtitle_info = scan_subtitle_files()

    xbmcplugin.setContent(_handle, 'videos')

    if entries:
        delete_selected_item = xbmcgui.ListItem(label='Smazat vybrané')
        delete_selected_item.setProperty('IsPlayable', 'false')
        set_list_icon(delete_selected_item, ICON_BIN_DELETE)
        xbmcplugin.addDirectoryItem(
            _handle, get_url(_url, action='delete_selected_downloads'), delete_selected_item, False)

    if entries or subtitle_info.count > 0:
        delete_all_label = f'Smazat vše ({format_list_size(total_size)})'
        delete_all_item = xbmcgui.ListItem(label=delete_all_label)
        delete_all_item.setProperty('IsPlayable', 'false')
        set_list_icon(delete_all_item, ICON_BIN_DELETE)
        xbmcplugin.addDirectoryItem(
            _handle, get_url(_url, action='delete_all_downloads'), delete_all_item, False)

    if subtitle_info.count > 0:
        sub_label = (
            f'Smazat titulky (Počet: {subtitle_info.count}, '
            f'{format_subtitle_total_size(subtitle_info.total_bytes)})'
        )
        sub_item = xbmcgui.ListItem(label=sub_label)
        sub_item.setProperty('IsPlayable', 'false')
        set_list_icon(sub_item, ICON_BIN_DELETE)
        xbmcplugin.addDirectoryItem(
            _handle, get_url(_url, action='delete_subtitle_files'), sub_item, False)

    if not entries and subtitle_info.count == 0:
        _add_info_item(_handle, 'Žádné stažené soubory')
    elif not entries and subtitle_info.count > 0:
        _add_info_item(_handle, 'Žádné video soubory (nalezeny pouze titulky)')

    for entry in entries:
        size_label = format_list_size(entry.size_bytes)
        size_mb = int(round(entry.size_bytes / (1024 ** 2)))
        list_item = xbmcgui.ListItem(label=entry.name, label2=size_label, path=entry.path)
        list_item.setInfo('video', {
            'title': entry.name,
            'mediatype': 'video',
            'size': size_mb * (1024 ** 2),
        })
        list_item.setProperty('IsPlayable', 'true')
        list_item.setArt({'icon': icons_path + 'prehrajto.png'})
        play_url = get_url(_url, action='play_local', path=quote(entry.path, safe=''))
        apply_context_menu_items(list_item, build_local_file_context_menu_items(
            _url, quote(entry.path, safe='')))
        xbmcplugin.addDirectoryItem(_handle, play_url, list_item, False)

    xbmcplugin.endOfDirectory(_handle)


def refresh_downloads_menu(_url: str) -> None:
    xbmc.executebuiltin(
        f'Container.Update({get_url(_url, action="listing_downloads")},replace)')
