import re
from typing import List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from common import get_user_agent
from model.StreamData import StreamData
from model.SubData import SubData
from providers.sledujteto.parse_set_tracks import parse_set_tracks
from providers.sledujteto.session import get_session
from utils.StrUtils import find_pattern, find_pattern_groups
from utils.utils import build_headers, dprint

_VIDEO_SRC_RE = re.compile(
    r'<video[^>]+class="[^"]*jw-video[^"]*"[^>]+src="([^"]+)"',
    re.IGNORECASE,
)
_SUBTITLE_URL_RE = re.compile(
    r'https?://[^\s"\'<>]+\.(?:vtt|srt)(?:\?[^\s"\'<>]*)?',
    re.IGNORECASE,
)


def _table_value(soup: BeautifulSoup, label_fragment: str) -> str:
    for row in soup.select('.parameters-wrapper tr, table.table-striped tr'):
        cells = row.find_all('td')
        if len(cells) < 3:
            continue
        label = cells[1].get_text(' ', strip=True)
        if label_fragment.lower() not in label.lower():
            continue
        return cells[2].get_text(' ', strip=True)
    return ''


def _resolve_stream_via_init(html: str, page_url: str) -> Optional[str]:
    id_server = find_pattern_groups(html, r'init\(([0-9]+),\s*?\'([^\']+)\'')
    if id_server is None:
        return None

    ssurl = urlsplit(id_server.group(2))
    api = urlunsplit((ssurl.scheme, ssurl.netloc, 'services/add-file-link', '', ''))
    headers = build_headers(get_user_agent(), page_url)
    headers['X-Requested-With'] = 'XMLHttpRequest'

    resp = get_session().post(
        api,
        headers=headers,
        json={'params': {'id': int(id_server.group(1))}},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get('error'):
        dprint(f'sledujteto get_stream_data(): add-file-link error: {payload.get("msg")}')
        return None

    stream_url = payload.get('video_url') or payload.get('hash')
    if stream_url and not stream_url.startswith('http'):
        serverurl = urlunsplit((ssurl.scheme, ssurl.netloc, '', '', ''))
        stream_url = f'{serverurl}/player/index/sledujteto/{stream_url}'
    return stream_url


def _parse_stream_url(html: str, page_url: str) -> Optional[str]:
    video = BeautifulSoup(html, 'html.parser').find('video', class_=re.compile(r'jw-video'))
    if video and video.get('src'):
        return video['src'].strip()

    match = _VIDEO_SRC_RE.search(html)
    if match:
        return match.group(1).strip()

    direct = find_pattern(html, r'src="(https?://[^"]+/player/index/sledujteto/[^"]+)"')
    if direct:
        return direct

    return _resolve_stream_via_init(html, page_url)


def _parse_subtitles(html: str) -> List[SubData]:
    sub_data: List[SubData] = []
    seen_paths = set()

    for track in parse_set_tracks(html):
        path = track.file or track.path
        if path and path not in seen_paths:
            seen_paths.add(path)
            sub_data.append(SubData(label=track.label or path, path=path))

    soup = BeautifulSoup(html, 'html.parser')
    for link in soup.select('table.table-subtitles a.subtitles-link'):
        label = link.get_text(strip=True)
        for attr in ('href', 'data-url', 'data-src'):
            path = link.get(attr, '')
            if path and path not in ('#', '') and path not in seen_paths:
                seen_paths.add(path)
                sub_data.append(SubData(label=label or path, path=path))

    for url in _SUBTITLE_URL_RE.findall(html):
        if url not in seen_paths:
            seen_paths.add(url)
            label = url.rsplit('/', 1)[-1].split('?', 1)[0]
            sub_data.append(SubData(label=label, path=url))

    if not sub_data:
        dprint('sledujteto get_stream_data(): no external subtitle URLs found (may be player-embedded)')
    return sub_data


def get_streams_data(
        page_url: str,
        src_bytes: bytes,
) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
    html = src_bytes.decode('utf-8', errors='replace')

    stream_url = _parse_stream_url(html, page_url)
    if not stream_url:
        dprint('sledujteto get_stream_data(): stream URL not found')
        return None, None

    soup = BeautifulSoup(html, 'html.parser')
    resolution = _table_value(soup, 'Rozli')
    size = _table_value(soup, 'Velikost')
    duration = _table_value(soup, 'Trvání')

    quality = 0
    label = resolution or 'Stream'
    if resolution and '*' in resolution:
        try:
            quality = int(resolution.split('*', 1)[1])
        except ValueError:
            pass

    label2 = size or duration
    headers = build_headers(get_user_agent(), page_url)

    stream_data = StreamData(
        label=label,
        label2=label2,
        quality=quality,
        path=stream_url,
        headers=headers,
    )

    sub_data = _parse_subtitles(html)
    dprint(f'sledujteto get_stream_data(): stream={stream_url} subs={len(sub_data)}')
    return [stream_data], sub_data
