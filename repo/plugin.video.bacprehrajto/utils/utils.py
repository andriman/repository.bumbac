import re
from typing import Callable, List, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from common import g_is_debug_logs_enabled, quality_icons_path, _ADDON_NAME, g_is_debug_info_on, g_unpack_context_menu
from downloads.download_queue import (
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
)

PREFIX_DOWNLOAD = '⇩ '
PREFIX_COPY = '📋 '
PREFIX_LIBRARY = '🖬 '
PREFIX_REFRESH = '↻ '
PREFIX_DELETE = '🗑 '
PREFIX_QR = '▣ '
from model.SubData import SubData
from utils.StrUtils import get_file_size_human_readable, response_total_size

_SIZE_HINT_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB)\b', re.IGNORECASE)


def dprint(text):
    if g_is_debug_logs_enabled:
        print(text)

def build_headers(user_agent: str, referer: str) -> Dict[str, str]:
    headers = {'User-Agent': user_agent}
    headers.update({'Referer': referer})
    return headers

def filter_subtitles(data) -> List[SubData]:
    dprint(f'filter_subtitles(): data: ' + str(len(data)))

    # Now filter and clean the tracks.
    subtitle_pattern = re.compile(r'- (cze|eng)\d*$', re.IGNORECASE)
    subtitle_pattern2 = re.compile(r'(CZ|EN) -', re.IGNORECASE)

    filtered_tracks: List[SubData] = []
    for track in data:  # assuming dt is the list of track dicts
        label = track.get('label', '')
        match = subtitle_pattern.search(label)
        if not match:
            match = subtitle_pattern2.search(label)

        if match:
            lang_code = match.group(1)
            # If there's a number after cze/eng, include it (e.g., cze1)
            full_match = re.search(r'(cze|eng)\d*$', label, re.IGNORECASE)

            if full_match:
                lang_code = full_match.group(0)  # e.g., "cze", "cze1", "eng"
            else:
                lcu = lang_code.upper()
                if 'CZ' == lcu: lang_code = 'cze'
                elif 'EN' == lcu: lang_code = 'eng'

            file = track.get('file', '')
            if len(file) > 0:
                sub_data = SubData(label=lang_code, path=file)

                if any(x.label == lang_code for x in filtered_tracks):
                    # Prevent skipping/overwriting the subtitle file.
                    sub_data.label = lang_code + '_' + str(len(filtered_tracks))

                filtered_tracks.append(sub_data)

    # Print result
    dprint(f'filter_subtitles(): finish: ' + str(len(data)) + ' -> ' + str(len(filtered_tracks)))
    for t in filtered_tracks:
        dprint(t)

    return filtered_tracks


def apply_stream_headers(
        listitem: xbmcgui.ListItem,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[str] = None,
) -> None:
    if cookies:
        listitem.setProperty('http-cookies', cookies)
    if not headers:
        return
    try:
        listitem.setHttpHeaders(headers)
        return
    except AttributeError:
        pass
    ua = headers.get('User-Agent') or headers.get('user-agent')
    ref = headers.get('Referer') or headers.get('referer')
    if ua:
        listitem.setProperty('http-user-agent', ua)
    if ref:
        listitem.setProperty('http-referrer', ref)


def _size_hint_to_label(size_hint: Optional[str]) -> Optional[str]:
    if not size_hint:
        return None
    match = _SIZE_HINT_RE.search(size_hint.strip())
    return match.group(0).strip() if match else None


def notify_file_size(file, size_hint: Optional[str] = None, headers: Optional[Dict[str, str]] = None):
    file_size_str = _size_hint_to_label(size_hint)
    if file_size_str is None and file is not None:
        file_size_str = get_file_size_human_readable(file, headers=headers)
    if file_size_str is None:
        file_size_str = "Unknown"

    dprint(f'notify_file_size(): ' + file_size_str)

    if g_is_debug_info_on and not file_size_str.__eq__('Unknown'):
        xbmcgui.Dialog().notification(
            heading=_ADDON_NAME,
            message=f"Velikost: {file_size_str}",
            icon=xbmcgui.NOTIFICATION_INFO,
            time=4000,
            sound=False
        )

def get_url(plugin_url=None, **kwargs):
    if plugin_url is None:
        plugin_url = kwargs.pop('url', None)
    if not plugin_url:
        raise TypeError('get_url() missing 1 required positional argument: plugin_url')
    return '{0}?{1}'.format(plugin_url, urlencode(kwargs))


def apply_context_menu_items(list_item, items: List[tuple]) -> None:
    """Kodi only supports (label, action) pairs in addContextMenuItems — no PNG icons."""
    plain = []
    for item in items:
        if len(item) >= 2:
            plain.append((item[0], item[1]))
    if plain:
        list_item.addContextMenuItems(plain)


def build_video_context_menu_items(plugin_url: str, vid_url: str) -> List[tuple]:
    if not g_unpack_context_menu:
        return [
            ('Akce…', 'RunPlugin({})'.format(
                get_url(plugin_url, action='video_actions', url=vid_url))),
        ]
    return [
        (PREFIX_REFRESH + 'Vybrat stream', 'RunPlugin({})'.format(
            get_url(plugin_url, action='select_stream', link=vid_url))),
        (PREFIX_COPY + 'Kopírovat URL', 'RunPlugin({})'.format(
            get_url(plugin_url, action='copy_url', url=vid_url))),
        (PREFIX_LIBRARY + 'Uložit do knihovny', 'RunPlugin({})'.format(
            get_url(plugin_url, action='library', url=vid_url))),
        (PREFIX_DOWNLOAD + 'Stáhnout', 'RunPlugin({})'.format(
            get_url(plugin_url, action='download', url=vid_url))),
        (PREFIX_DOWNLOAD + 'Přidat do fronty', 'RunPlugin({})'.format(
            get_url(plugin_url, action='download_enqueue', url=vid_url))),
        (PREFIX_DOWNLOAD + 'Stáhnout na pozadí', 'RunPlugin({})'.format(
            get_url(plugin_url, action='download_background', url=vid_url))),
        (PREFIX_QR + 'QR kód streamu', 'RunPlugin({})'.format(
            get_url(plugin_url, action='qr', url=vid_url))),
    ]


def build_local_file_context_menu_items(plugin_url: str, file_path: str) -> List[tuple]:
    delete_action = 'RunPlugin({})'.format(
        get_url(plugin_url, action='delete_download', path=file_path))
    if not g_unpack_context_menu:
        return [
            ('Akce…', 'RunPlugin({})'.format(
                get_url(plugin_url, action='local_file_actions', path=file_path))),
        ]
    return [(PREFIX_DELETE + 'Smazat', delete_action)]


def build_queue_job_context_menu_items(plugin_url: str, job_id: str, job) -> List[tuple]:
    if not g_unpack_context_menu:
        return [
            ('Akce…', f'RunPlugin({get_url(plugin_url, action="queue_job_actions", job_id=job_id)})'),
        ]
    items = []
    if job.status in (STATUS_PENDING, STATUS_RUNNING):
        items.append((
            PREFIX_DELETE + 'Zrušit',
            f'RunPlugin({get_url(plugin_url, action="download_cancel", job_id=job_id)})',
        ))
    if job.status in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELED):
        items.append((
            PREFIX_DELETE + 'Odstranit z fronty',
            f'RunPlugin({get_url(plugin_url, action="download_remove", job_id=job_id)})',
        ))
    return items


def stream_http_download(
        url: str,
        dest_path: str,
        headers: Optional[Dict[str, str]] = None,
        session: Optional[requests.Session] = None,
        block_sz: int = 256 * 1024,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
) -> Tuple[int, int, bool]:
    """Download a remote file with optional Referer/Range headers. Returns (downloaded, total, canceled)."""
    sess = session or requests.Session()
    hdrs = dict(headers or {})
    if 'Range' not in hdrs:
        hdrs['Range'] = 'bytes=0-'

    downloaded = 0
    total = 0
    canceled = False

    with sess.get(url, headers=hdrs, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = response_total_size(resp)
        with open(dest_path, 'wb') as out_file:
            for chunk in resp.iter_content(chunk_size=block_sz):
                if cancel_check and cancel_check():
                    canceled = True
                    break
                if not chunk:
                    continue
                out_file.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)

    return downloaded, total, canceled


def get_quality_icon(q: int):
    icon = 'sd.png'
    if q >= 2160:
        icon = '4k.png'
    elif q >= 1080:
        icon = '1080p.png'
    elif q >= 720:
        icon = '720p.png'

    return quality_icons_path + icon


def size_str_to_bytes(size_str: str) -> int:
    """
    Converts size string like "374.43 MB" to bytes (int).
    Supports: B, KB, MB, GB, TB (case insensitive, with or without space).

    Args:
        size_str (str): Size in format "123.45 MB" or "500KB"

    Returns:
        int: Total bytes

    Example:
        >>> size_str_to_bytes("374.43 MB")
        392659763
        >>> size_str_to_bytes("1.5GB")
        1610612736
    """
    size_str = size_str.strip()

    # Pattern: number (with optional decimal), optional space, unit
    pattern = r'^([\d.]+)\s*([a-zA-Z]*)$'
    match = re.match(pattern, size_str)

    if not match:
        raise ValueError(f"Invalid size format: {size_str}")

    value_str, unit = match.groups()

    try:
        value = float(value_str)
    except ValueError:
        raise ValueError(f"Invalid numeric value: {value_str}")

    unit = unit.upper()

    multipliers = {
        '': 1,  # Assume bytes if no unit
        'B': 1,
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
        'TB': 1024 ** 4,
    }

    if unit not in multipliers:
        raise ValueError(f"Unknown unit: {unit}")

    total_bytes = int(value * multipliers[unit])
    return total_bytes