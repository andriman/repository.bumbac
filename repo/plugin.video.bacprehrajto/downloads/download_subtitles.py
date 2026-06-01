import hashlib
import os
from typing import List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import requests
from cache.subtitle_cache import get_subtitle_cache_dir
from common import g_download_path, get_headers, get_user_agent
from downloads.downloads_utils import cleanup_subtitle_sidecars, get_download_folder
from model.SubData import SubData
from providers.prehrajto.get_stream_data import sanitize_subtitle_label
from utils.StrUtils import convert_size
from utils.utils import build_headers, dprint


def _subtitle_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith('.vtt'):
        return '.vtt'
    if path.endswith('.srt'):
        return '.srt'
    if path.endswith('.ass') or path.endswith('.ssa'):
        return os.path.splitext(path)[1]
    return '.vtt'


def _fetch_subtitle_bytes(url: str, referer: Optional[str] = None) -> bytes:
    headers = get_headers()
    if referer:
        headers = build_headers(get_user_agent(), referer)
    try:
        res = requests.get(url, headers=headers, timeout=20)
        res.raise_for_status()
        return res.content
    except requests.RequestException:
        req = Request(url, headers=headers)
        return urlopen(req, timeout=20).read()


def _label_with_size(base_label: str, size_str: Optional[str]) -> str:
    if not size_str:
        return base_label
    if f'({size_str})' in base_label:
        return base_label
    return f'{base_label} ({size_str})'


def _materialize_remote_subtitle(sub: SubData, referer: Optional[str] = None) -> str:
    """Cache remote subs with track label and size visible in Kodi's subtitle list."""
    ext = _subtitle_extension(sub.path)
    safe_label = sanitize_subtitle_label(sub.label)
    url_key = hashlib.md5(sub.path.encode('utf-8', errors='replace')).hexdigest()[:10]

    data = _fetch_subtitle_bytes(sub.path, referer=referer)
    size_str = convert_size(len(data), 1)
    display_label = _label_with_size(safe_label, size_str)
    filename = f'{display_label} [{url_key}]{ext}'
    local_path = os.path.join(get_subtitle_cache_dir(), filename)

    if os.path.isfile(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    with open(local_path, 'wb') as fs:
        fs.write(data)
    return local_path


def subtitle_paths_for_playback(
        subs: Optional[List[SubData]],
        referer: Optional[str] = None,
) -> Optional[List[str]]:
    if not subs:
        return None
    paths: List[str] = []
    for sub in subs:
        if not sub.path:
            continue
        if sub.path.startswith('http://') or sub.path.startswith('https://'):
            try:
                paths.append(_materialize_remote_subtitle(sub, referer=referer))
            except Exception as exc:
                dprint(f'subtitle_paths_for_playback(): cache failed for {sub.label}: {exc}')
                paths.append(sub.path)
        else:
            paths.append(sub.path)
    return paths or None


def download_subtitles(
        subs: Optional[List[SubData]],
        name_wo_ext: str,
        use_name_as_subfolder: bool = False,
        path: Optional[str] = None,
        referer: Optional[str] = None,
) -> Optional[List[str]]:
    if subs is None or len(subs) == 0:
        return None

    if path is None:
        path = get_download_folder() or g_download_path
    if not path:
        return None

    if use_name_as_subfolder:
        sub_dir = os.path.join(path.rstrip('/\\'), name_wo_ext)
        if os.path.isdir(sub_dir):
            for item in os.listdir(sub_dir):
                if item.lower().endswith(('.srt', '.vtt', '.ass', '.ssa')):
                    try:
                        os.remove(os.path.join(sub_dir, item))
                    except OSError:
                        pass
        path = sub_dir + os.sep
        dprint('download_subtitles(): ' + path)
    else:
        removed = cleanup_subtitle_sidecars(name_wo_ext, path)
        if removed:
            dprint(f'download_subtitles(): removed {removed} old subtitle sidecar(s) for {name_wo_ext}')

    sub_paths: List[str] = []
    os.makedirs(path.rstrip('/\\'), exist_ok=True)

    for sub in subs:
        name_prefix = "" if use_name_as_subfolder else (name_wo_ext + "-")
        ext = _subtitle_extension(sub.path)
        safe_label = sanitize_subtitle_label(sub.label)
        data = _fetch_subtitle_bytes(sub.path, referer=referer)

        size_str = convert_size(len(data), 1)
        display_label = _label_with_size(safe_label, size_str)
        name_subtitles = name_prefix + display_label + ext

        abs_path = path + name_subtitles
        with open(abs_path, "wb") as fs:
            fs.write(data)

        sub_paths.append(abs_path)

    return sub_paths
