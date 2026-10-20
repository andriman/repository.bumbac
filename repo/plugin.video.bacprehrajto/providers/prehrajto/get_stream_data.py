import json
import os
import re
from typing import Tuple, List, Optional

import xbmcgui
from bs4 import BeautifulSoup

import hjson
from common import _ADDON_NAME, get_user_agent, get_prehrajto_base
from model.StreamData import StreamData
from model.SubData import SubData
from utils.utils import dprint, filter_subtitles, build_headers
from utils.StrUtils import contains_pattern, find_pattern
from utils.TimeUtils import format_time_ago


def _label2_with_upload(base_label2: str, upload_date: Optional[str]) -> str:
    if not upload_date:
        return base_label2
    nab = f"Nahráno: {upload_date}"
    if not base_label2:
        return nab
    return f"{base_label2} | {nab}"


def _stream_from_label_and_path(label: str, path: str, upload_date: Optional[str]) -> StreamData:
    quality = int(label.strip('p'))
    label2 = _label2_with_upload('', upload_date)
    return StreamData(label=label, label2=label2, quality=quality, path=path, upload_date=upload_date)


def _update_progress(dialog: Optional[xbmcgui.DialogProgress], pct: int, msg: str) -> None:
    if dialog:
        dialog.update(pct, msg)


def _close_progress(dialog: Optional[xbmcgui.DialogProgress]) -> None:
    if dialog:
        dialog.close()


def _upload_date_from_html(dgl: str) -> Optional[str]:
    upload_raw = find_pattern(dgl, r'Datum nahr.n.:</span>\s*?<span>([^<]+)')
    return upload_raw.strip() if upload_raw else None


def sanitize_subtitle_label(label: str) -> str:
    """Filesystem-safe display name from the player's track label."""
    label = (label or '').strip()
    label = re.sub(r'[<>:"/\\|?*]', '_', label)
    label = re.sub(r'\s+', ' ', label).strip()
    if len(label) > 120:
        label = label[:120].strip()
    return label or 'sub'


_TRACKS_PATTERN = re.compile(r'var\s+tracks\s*=\s*(\[.*?\])\s*;', re.DOTALL)


def _load_tracks_raw(src_bytes: bytes) -> List[dict]:
    soup = BeautifulSoup(src_bytes, 'html.parser')
    tracks_script = soup.find('script', string=_TRACKS_PATTERN)
    if tracks_script is None:
        return []
    match = _TRACKS_PATTERN.search(tracks_script.string)
    if not match:
        return []
    sub_data = hjson.loads(match.group(1))
    return json.loads(json.dumps(sub_data))


def merge_subtitle_lists(*lists: List[SubData]) -> List[SubData]:
    """Merge by URL; keep the most descriptive label per file."""
    by_path: dict = {}
    order: List[str] = []
    for subs in lists:
        for sub in subs:
            if not sub.path:
                continue
            if sub.path not in by_path:
                by_path[sub.path] = sub
                order.append(sub.path)
            elif len(sub.label) > len(by_path[sub.path].label):
                by_path[sub.path] = sub
    return [by_path[path] for path in order]


def tracks_to_subdata_all(tracks: List[dict]) -> List[SubData]:
    """All caption tracks using the page label (e.g. CZE - 9932006 - cze), not lang codes only."""
    subs: List[SubData] = []
    seen_files: set = set()
    used_labels: set = set()
    for track in tracks:
        file_url = (track.get('file') or '').strip()
        if not file_url or file_url in seen_files:
            continue
        seen_files.add(file_url)
        display = sanitize_subtitle_label(track.get('label') or '')
        label = display
        suffix = 2
        while label in used_labels:
            label = f'{display} ({suffix})'
            suffix += 1
        used_labels.add(label)
        subs.append(SubData(label=label, path=file_url))
    return subs


def parse_all_subtitles_from_html(src_bytes: bytes) -> List[SubData]:
    try:
        return tracks_to_subdata_all(_load_tracks_raw(src_bytes))
    except Exception as e:
        dprint('parse_all_subtitles_from_html(): exception:\n' + str(e))
        return []


def parse_subtitles_from_html(src_bytes: bytes) -> List[SubData]:
    try:
        return filter_subtitles(_load_tracks_raw(src_bytes))
    except Exception as e:
        dprint('parse_subtitles_from_html(): exception:\n' + str(e))
        return []


def parse_streams_from_html(src_bytes: bytes) -> List[StreamData]:
    soup = BeautifulSoup(src_bytes, 'html.parser')
    sources_pattern = re.compile(r'var sources = (\[.*?);', re.DOTALL)
    script_f = soup.find('script', string=sources_pattern)
    if script_f is None:
        return []

    dgl = src_bytes.decode('utf-8')
    upload_date = _upload_date_from_html(dgl)
    script = script_f.string
    stream_items: List[StreamData] = []

    download_link = find_pattern(
        dgl,
        r'href="/([^\?]+\?do=download)\" class="button cta cta--large\">\s*?<span class=\"icon-download\">',
    )
    if download_link:
        download_link = get_prehrajto_base() + '/' + download_link.lstrip('/')
        page_for_headers = download_link.split('?do=download')[0]
        hdrs = build_headers(get_user_agent(), page_for_headers)
        size_txt = find_pattern(dgl, r'Velikost:</span>\s*?<span>([^<]+?)</span>')
        premium_item = StreamData(
            label='Premium',
            label2=_label2_with_upload(size_txt or '', upload_date),
            path=download_link,
            headers=hdrs,
            is_premium=True,
            upload_date=upload_date,
        )

        quality = find_pattern(dgl, r'Rozli.en.:</span>\s*?<span>([^<]+?)</span>')
        if quality is not None:
            quality = quality.replace(' ', '')
            height = find_pattern(quality, r'[0-9]+x([0-9]+)')
            if height.isnumeric():
                premium_item.quality = int(height)
                premium_item.label = height + 'p'

        stream_items.append(premium_item)

    try:
        streams_re = re.compile(r'file:\s*?["\'](.+?)["\'],\s*?label: ["\'](.+?)["\']', re.DOTALL)
        sources = sources_pattern.findall(script)
        for sources_text in sources:
            all_streams = streams_re.findall(sources_text)
            for stream in all_streams:
                stream_items.append(_stream_from_label_and_path(stream[1], stream[0], upload_date))
    except Exception as e:
        dprint('parse_streams_from_html(): vidfile exception:\n' + str(e))
        src = re.compile(r'src:\s*?["\'](.+?)["\'][^\}]+?label:\s*?["\'](.+?)["\']', re.DOTALL)
        all_streams = src.findall(sources_pattern.findall(script)[0])
        for stream in all_streams:
            stream_items.append(_stream_from_label_and_path(stream[1], stream[0], upload_date))

    stream_items.sort(key=lambda x: (not x.is_premium, -x.quality))
    return stream_items


def get_streams_data(
        src_bytes: bytes,
        show_progress: bool = True,
        progress_dialog: Optional[xbmcgui.DialogProgress] = None,
) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
    dprint('get_stream_data()')

    p_dialog = progress_dialog
    owns_dialog = False
    if show_progress and p_dialog is None:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create('Hledám streamy')
        owns_dialog = True

    dgl = src_bytes.decode('utf-8')
    upload_raw = find_pattern(dgl, r'Datum nahr.n.:</span>\s*?<span>([^<]+)')
    sources_pattern = re.compile(r'var sources = (\[.*?);', re.DOTALL)
    soup = BeautifulSoup(src_bytes, 'html.parser')
    script_f = soup.find('script', string=sources_pattern)

    if script_f is None:
        if contains_pattern(dgl, r'>\s*?Video se zpracov'):
            time_ago = format_time_ago(upload_raw)
            if owns_dialog:
                _close_progress(p_dialog)
            xbmcgui.Dialog().notification(
                heading=_ADDON_NAME,
                message='Video se teprve zpracovává:\nNahráno:\n' + time_ago,
                icon=xbmcgui.NOTIFICATION_INFO,
                time=4000,
                sound=False,
            )
        else:
            dprint('get_stream_data(): script not found:\n' + str(dgl))
            if owns_dialog:
                _close_progress(p_dialog)
            xbmcgui.Dialog().notification(
                heading=_ADDON_NAME,
                message='Script not found',
                icon=xbmcgui.NOTIFICATION_INFO,
                time=4000,
                sound=False,
            )
        return None, None

    _update_progress(p_dialog, 10, 'Hledám video streamy')
    stream_items = parse_streams_from_html(src_bytes)

    _update_progress(p_dialog, 60, 'Hledám titulky')
    filtered_sub_data = parse_subtitles_from_html(src_bytes)

    _update_progress(p_dialog, 100, '')
    if owns_dialog:
        _close_progress(p_dialog)
    return stream_items, filtered_sub_data
