import glob
import os
import shutil
from dataclasses import dataclass
from typing import List, Optional, Tuple

import xbmcvfs

from common import addon, g_download_path
from downloads.download_queue import queue_summary

DISKSPACE_FREE = 2

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm', '.m4v')
MB_500 = 500 * 1024 * 1024
EXTENSIONLESS_VIDEO_MIN_BYTES = 1024 * 1024


@dataclass
class DownloadEntry:
    path: str
    name: str
    size_bytes: int
    mtime: float


@dataclass
class SubtitleFilesInfo:
    paths: List[str]
    count: int
    total_bytes: int


def get_download_folder() -> Optional[str]:
    raw = addon.getSetting('download') or g_download_path
    if not raw:
        return None
    folder = xbmcvfs.translatePath(raw)
    if not folder.endswith(os.sep):
        folder += os.sep
    return folder


def format_list_size(size_bytes: int) -> str:
    if size_bytes < MB_500:
        return f'{int(round(size_bytes / (1024 ** 2)))} MB'
    return f'{size_bytes / (1024 ** 3):.2f} GB'


def format_gb(size_bytes: int) -> str:
    gb = size_bytes / (1024 ** 3)
    if gb < 0.01 and size_bytes > 0:
        return '<0.01'
    text = f'{gb:.2f}'.rstrip('0').rstrip('.')
    return text or '0'


def format_used_free_gb(used_bytes: int, free_bytes: int) -> str:
    return f'{format_gb(used_bytes)} / {format_gb(free_bytes)} GB'


def get_volume_free_bytes(folder: str) -> Optional[int]:
    path = xbmcvfs.translatePath(folder.rstrip(os.sep)) or folder.rstrip(os.sep)
    if not path:
        return None

    check_path = path if os.path.isdir(path) else os.path.dirname(path)
    if not check_path:
        return None

    try:
        free = xbmcvfs.getDiskSpace(check_path, DISKSPACE_FREE)
        if free and free > 0:
            return int(free)
    except (TypeError, ValueError, AttributeError):
        pass

    try:
        return shutil.disk_usage(check_path).free
    except OSError:
        return None


def get_downloads_root_label() -> str:
    folder = get_download_folder()

    if folder is None:
        return 'Stažené'

    used_bytes = get_total_occupied_size()
    free_bytes = get_volume_free_bytes(folder)
    if free_bytes is None:
        return f'Stažené ({format_list_size(used_bytes)})'
    return f'Stažené ({format_used_free_gb(used_bytes, free_bytes)})'


def get_download_queue_root_label() -> str:
    summary = queue_summary()
    active = summary['pending'] + summary['running']
    return f'Fronta stahování ({active} aktivních / {summary["total"]} celkem)'


def format_subtitle_total_size(size_bytes: int) -> str:
    if size_bytes < 1024 * 1024:
        return f'{int(round(size_bytes / 1024))} KB'
    return f'{int(round(size_bytes / (1024 ** 2)))} MB'


def scan_downloads() -> List[DownloadEntry]:
    folder = get_download_folder()
    if folder is None or not os.path.isdir(folder):
        return []

    entries: List[DownloadEntry] = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext == '.srt':
            continue
        if ext not in VIDEO_EXTENSIONS and ext:
            continue
        try:
            size_bytes = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if ext not in VIDEO_EXTENSIONS and size_bytes < EXTENSIONLESS_VIDEO_MIN_BYTES:
            continue
        entries.append(DownloadEntry(path=path, name=name, size_bytes=size_bytes, mtime=mtime))

    entries.sort(key=lambda e: e.mtime, reverse=True)
    return entries


def scan_subtitle_files() -> SubtitleFilesInfo:
    folder = get_download_folder()
    if folder is None or not os.path.isdir(folder):
        return SubtitleFilesInfo(paths=[], count=0, total_bytes=0)

    paths: List[str] = []
    total = 0
    for name in os.listdir(folder):
        if not name.lower().endswith('.srt'):
            continue
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
        paths.append(path)

    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return SubtitleFilesInfo(paths=paths, count=len(paths), total_bytes=total)


def get_total_occupied_size() -> int:
    folder = get_download_folder()
    if folder is None or not os.path.isdir(folder):
        return 0

    total = 0
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in VIDEO_EXTENSIONS or ext == '.srt':
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        elif not ext:
            try:
                if os.path.getsize(path) >= EXTENSIONLESS_VIDEO_MIN_BYTES:
                    total += os.path.getsize(path)
            except OSError:
                pass
    return total


def find_subtitles_for_video(video_path: str) -> List[str]:
    folder = os.path.dirname(video_path)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    patterns = [
        os.path.join(folder, stem + '-*.srt'),
        os.path.join(folder, stem + '*.srt'),
    ]
    found: List[str] = []
    for pattern in patterns:
        for path in glob.glob(pattern):
            if path != video_path and os.path.isfile(path):
                found.append(path)
    return sorted(set(found))


def _delete_file(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def cleanup_subtitle_sidecars(name_wo_ext: str, folder: Optional[str] = None) -> int:
    """Remove subtitle files matching a video base name. Returns count deleted."""
    if not name_wo_ext:
        return 0
    if folder is None:
        folder = get_download_folder()
    if folder is None or not os.path.isdir(folder):
        return 0

    deleted = 0
    patterns = [
        os.path.join(folder, name_wo_ext + '-*.srt'),
        os.path.join(folder, name_wo_ext + '*.srt'),
        os.path.join(folder, name_wo_ext + '-*.vtt'),
        os.path.join(folder, name_wo_ext + '*.vtt'),
    ]
    for pattern in patterns:
        for path in glob.glob(pattern):
            if os.path.isfile(path):
                _delete_file(path)
                deleted += 1
    return deleted


def delete_video_and_subs(video_path: str) -> None:
    for sub_path in find_subtitles_for_video(video_path):
        _delete_file(sub_path)
    _delete_file(video_path)


def delete_all_subtitle_files() -> Tuple[int, int]:
    info = scan_subtitle_files()
    for path in info.paths:
        _delete_file(path)
    return info.count, info.total_bytes


def delete_all_downloads() -> Tuple[int, int]:
    """Delete all videos and .srt files. Returns (files_deleted, bytes_freed)."""
    folder = get_download_folder()
    if folder is None or not os.path.isdir(folder):
        return 0, 0

    deleted = 0
    freed = 0
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext == '.srt' or ext in VIDEO_EXTENSIONS:
            pass
        elif not ext:
            try:
                if os.path.getsize(path) < EXTENSIONLESS_VIDEO_MIN_BYTES:
                    continue
            except OSError:
                continue
        else:
            continue
        try:
            freed += os.path.getsize(path)
        except OSError:
            pass
        _delete_file(path)
        deleted += 1
    return deleted, freed
