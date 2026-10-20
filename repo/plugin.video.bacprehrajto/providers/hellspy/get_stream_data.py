import json
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import xbmc

from common import get_hellspy_api_base, get_user_agent
from model.StreamData import StreamData
from model.SubData import SubData
from providers.hellspy.payload import (
    conversion_quality,
    extract_initial_data,
    ordered_conversions,
    subtitle_entries,
    video_record,
)
from utils.StrUtils import convert_size
from utils.utils import build_headers, dprint

_PROBE_TIMEOUT = 20
_DOWNLOAD_TIMEOUT = 30
_DOWNLOAD_HREF = re.compile(
    r'https?://[^"\'\s<>]+?/gw/video/\d+/[0-9a-fA-F]+/download|/gw/video/\d+/[0-9a-fA-F]+/download',
    re.IGNORECASE,
)


def _duration_seconds(duration: object) -> Optional[int]:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return None
    if duration <= 0:
        return None
    return int(duration)


def _clock_label(duration: object) -> str:
    seconds = _duration_seconds(duration)
    if seconds is None:
        return ''
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def _size_label(size: object) -> str:
    try:
        return convert_size(int(size), 2)
    except (TypeError, ValueError):
        return ''


def _playback_headers(page_url: str, stream_url: str) -> dict:
    headers = build_headers(get_user_agent(), page_url)
    host = (urlparse(stream_url).netloc or '').lower()
    if 'hellspy.' not in host:
        return headers
    from providers.hellspy.auth import request_headers
    authorization = request_headers().get('Authorization')
    if authorization:
        headers['Authorization'] = authorization
    return headers


def _log_playback(message: str) -> None:
    dprint(message)
    try:
        xbmc.log(message, xbmc.LOGINFO)
    except Exception:
        pass


def _response_size(response) -> Optional[int]:
    content_range = response.headers.get('Content-Range') or ''
    if '/' in content_range:
        total = content_range.rsplit('/', 1)[-1].strip()
        if total.isdigit():
            return int(total)
    if response.status_code == 200:
        length = (response.headers.get('Content-Length') or '').strip()
        if length.isdigit():
            return int(length)
    return None


def _probe_playback(url: str, headers: dict) -> Tuple[bool, Optional[int]]:
    from providers.hellspy.session import get_session

    probe_headers = dict(headers or {})
    probe_headers['Range'] = 'bytes=0-0'
    try:
        response = get_session().get(
            url,
            headers=probe_headers,
            timeout=_PROBE_TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
    except Exception as exc:
        _log_playback(f'hellspy playback url invalid: {exc} url={url}')
        return False, None
    status = response.status_code
    size = _response_size(response)
    response.close()
    if status < 400:
        return True, size
    _log_playback(f'hellspy playback url invalid: HTTP {status} url={url}')
    return False, None


def _download_page_url(page_url: str, record: dict, html: str) -> str:
    match = _DOWNLOAD_HREF.search(html or '')
    if match:
        found = match.group(0).replace('&amp;', '&').replace('\\u0026', '&')
        if found.startswith('/'):
            return get_hellspy_api_base().rstrip('/') + found
        return found
    video_id = record.get('id')
    file_hash = str(record.get('fileHash') or '').strip()
    if video_id is not None and file_hash:
        return (
            get_hellspy_api_base().rstrip('/')
            + f'/gw/video/{video_id}/{file_hash}/download'
        )
    public_url = str(record.get('publicUrl') or '').strip().replace('\\/', '/').replace('&amp;', '&')
    if public_url.startswith(('http://', 'https://')) and '/file' in public_url.lower():
        return public_url
    return ''


def _json_source_url(body: str) -> str:
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return ''
    if isinstance(data, str) and data.startswith(('http://', 'https://')):
        return data
    if not isinstance(data, dict):
        return ''
    for key in ('url', 'downloadUrl', 'publicUrl', 'src', 'path'):
        value = data.get(key)
        if isinstance(value, str) and value.startswith(('http://', 'https://')):
            return value
    return ''


def _resolve_download_source(download_url: str, page_url: str) -> str:
    from providers.hellspy.session import get_session

    headers = _playback_headers(page_url, download_url)
    _log_playback(f'hellspy playback fallback: requesting download url {download_url}')
    try:
        response = get_session().get(
            download_url,
            headers=headers,
            timeout=_DOWNLOAD_TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
    except Exception as exc:
        _log_playback(f'hellspy playback fallback failed: {exc} url={download_url}')
        return ''
    status = response.status_code
    final_url = response.url or ''
    content_type = (response.headers.get('Content-Type') or '').lower()
    body = ''
    if 'json' in content_type or 'text' in content_type:
        try:
            body = response.text[:8000]
        except Exception:
            body = ''
    response.close()
    _log_playback(
        f'hellspy playback fallback: download HTTP {status} '
        f'content-type={content_type} source={final_url}'
    )
    if status >= 400:
        return ''
    source = _json_source_url(body) if body else ''
    if source:
        _log_playback(f'hellspy playback fallback: source url {source}')
        return source
    if final_url.startswith(('http://', 'https://')):
        _log_playback(f'hellspy playback fallback: source url {final_url}')
        return final_url
    return ''


_HEIGHT_IN_TITLE = re.compile(r'(2160|1440|1080|720|480)\s*p', re.IGNORECASE)


def _stream_label2(size: object, duration: object) -> str:
    return ' - '.join(
        part for part in (_size_label(size), _clock_label(duration)) if part
    )


def _original_height(record: dict) -> int:
    height = record.get('height')
    if isinstance(height, (int, float)) and not isinstance(height, bool) and int(height) >= 144:
        return int(height)
    title = str(record.get('title') or record.get('filename') or '')
    match = _HEIGHT_IN_TITLE.search(title)
    if match:
        return int(match.group(1))
    return 0


def _maximum_stream(
        page_url: str,
        record: dict,
        html: str,
        template: Optional[StreamData],
) -> Optional[StreamData]:
    download_url = _download_page_url(page_url, record, html)
    if not download_url:
        _log_playback('hellspy maximum stream: no download url')
        return None
    source = _resolve_download_source(download_url, page_url)
    if not source:
        _log_playback(
            f'hellspy maximum stream: download url did not yield a source {download_url}'
        )
        return None
    duration = template.duration if template is not None else _duration_seconds(record.get('duration'))
    quality = _original_height(record)
    label = f'Maximum {quality}p' if quality else 'Maximum'
    size = record.get('size')
    _log_playback(
        f'hellspy stream maximum: label={label} size={_size_label(size)} url={source}'
    )
    return StreamData(
        label=label,
        label2=_stream_label2(size, duration),
        quality=quality,
        path=source,
        headers=_playback_headers(page_url, source),
        is_premium=True,
        duration=duration,
    )


def _with_playable_source(
        streams: Optional[List[StreamData]],
        subs: Optional[List[SubData]],
        page_url: str,
        record: Optional[dict],
        html: str,
) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
    record = record or {}
    compressed: List[StreamData] = []
    for stream in streams or []:
        if stream.is_premium:
            continue
        headers = stream.headers or _playback_headers(page_url, stream.path)
        ok, size = _probe_playback(stream.path, headers)
        if not ok:
            continue
        original_size = _size_label(record.get('size'))
        if original_size and (stream.label2 or '').startswith(original_size):
            stream.label2 = _clock_label(stream.duration)
        if size:
            stream.label2 = _stream_label2(size, stream.duration)
        _log_playback(
            f'hellspy stream compressed: label={stream.label} size={stream.label2} url={stream.path}'
        )
        compressed.append(stream)

    template = compressed[0] if compressed else ((streams or [None])[0])
    maximum = _maximum_stream(page_url, record, html, template)
    if compressed and maximum is None:
        _log_playback('hellspy streams: compressed playback only, maximum download unavailable')
    if not compressed and maximum is not None:
        _log_playback(
            'hellspy streams: compressed playback unavailable, maximum download remains'
        )
    if not compressed and maximum is None:
        return streams, subs

    # Compressed first so Best compressed plays the page stream. Maximum stays selectable.
    chosen: List[StreamData] = list(compressed)
    if maximum is not None:
        chosen.append(maximum)
    _log_playback(
        f'hellspy streams: compressed={len(compressed)} maximum={int(maximum is not None)}'
    )
    return chosen, subs


def _stream_label(key: str) -> str:
    quality = conversion_quality(key)
    if quality:
        return f'{quality}p'
    return 'MP4'


def _streams_from_pairs(
        page_url: str,
        pairs: List[Tuple[str, str]],
        record: dict,
        file_mp4_only: bool = False,
) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
    file_pairs = list(pairs)
    if file_mp4_only:
        file_pairs = [(key, url) for key, url in pairs if '/file.mp4' in url.lower()]
    if not file_pairs:
        return None, None
    duration_seconds = _duration_seconds(record.get('duration'))
    label2 = ' - '.join(
        part for part in (_size_label(record.get('size')), _clock_label(duration_seconds)) if part
    )
    streams = [
        StreamData(
            label=_stream_label(key),
            label2=label2,
            quality=conversion_quality(key),
            path=url,
            headers=_playback_headers(page_url, url),
            is_premium=False,
            duration=duration_seconds,
        )
        for key, url in file_pairs
    ]
    subs = [
        SubData(label=entry['label'], path=entry['url'])
        for entry in subtitle_entries(record.get('subtitles'))
    ]
    return streams, subs


def _client_streams(
        page_url: str,
        html: str,
        video_id: str,
        record: Optional[dict],
) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]], dict]:
    from providers.hellspy.account_videos import (
        fetch_video_conversions,
        fetch_video_detail,
        is_public_video,
        playback_pairs,
    )

    detail = fetch_video_detail(video_id)
    meta = detail if isinstance(detail, dict) else {}
    if not is_public_video(detail):
        dprint(f'hellspy get_stream_data(): client video {video_id} is not public')
        return None, None, meta

    if record is not None:
        conversions = ordered_conversions(record.get('conversions'))
        streams, subs = _streams_from_pairs(page_url, conversions, record, file_mp4_only=True)
        if streams:
            dprint(f'hellspy get_stream_data(): client video {video_id} html streams={len(streams)}')
            return streams, subs, meta

    conversion_items = fetch_video_conversions(video_id)
    if conversion_items:
        duration_seconds = _duration_seconds(meta.get('duration'))
        clock = _clock_label(duration_seconds)
        streams = []
        for item in conversion_items:
            size_label = _size_label(item.get('size')) or _size_label(meta.get('size'))
            label2 = ' - '.join(part for part in (size_label, clock) if part)
            streams.append(StreamData(
                label=_stream_label(item['key']),
                label2=label2,
                quality=conversion_quality(item['key']),
                path=item['url'],
                headers=_playback_headers(page_url, item['url']),
                is_premium=False,
                duration=duration_seconds,
            ))
        dprint(
            f'hellspy get_stream_data(): client video {video_id} conversions={len(streams)} '
            f'title={meta.get("filename")!r}'
        )
        return streams, [], meta

    pairs = playback_pairs(meta, html)
    streams, subs = _streams_from_pairs(page_url, pairs, meta)
    if not streams:
        dprint(f'hellspy get_stream_data(): client video {video_id} has no file.mp4')
        return None, None, meta
    dprint(
        f'hellspy get_stream_data(): client video {video_id} streams={len(streams)} '
        f'title={meta.get("filename")!r}'
    )
    return streams, subs, meta


def _account_original_url(record: dict) -> str:
    """Video.publicUrl is the original file. Conversion publicUrl is the smaller file.mp4."""
    public_url = str(record.get('publicUrl') or '').strip().replace('\\/', '/').replace('&amp;', '&')
    if not public_url.startswith(('http://', 'https://')):
        return ''
    if '/file.mp4' in public_url.lower():
        return ''
    if '/file' not in public_url.lower():
        return ''
    return public_url


def _account_playback_streams(
        streams: Optional[List[StreamData]],
        subs: Optional[List[SubData]],
        page_url: str,
        record: dict,
) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
    """Play the conversion file.mp4 and the original /file URL without fetching them first."""
    compressed = [stream for stream in (streams or []) if stream.path and not stream.is_premium]
    duration = compressed[0].duration if compressed else _duration_seconds(record.get('duration'))
    chosen: List[StreamData] = list(compressed)
    original = _account_original_url(record)
    if original:
        quality = _original_height(record)
        label = f'Maximum {quality}p' if quality else 'Maximum'
        maximum = StreamData(
            label=label,
            label2=_stream_label2(record.get('size'), duration),
            quality=quality,
            path=original,
            headers=_playback_headers(page_url, original),
            is_premium=True,
            duration=duration,
        )
        chosen.append(maximum)
        _log_playback(
            f'hellspy account stream maximum: label={label} size={_size_label(record.get("size"))}'
        )
    for stream in compressed:
        _log_playback(
            f'hellspy account stream compressed: label={stream.label} size={stream.label2}'
        )
    if not chosen:
        return None, None
    _log_playback(
        f'hellspy account streams: compressed={len(compressed)} maximum={int(bool(original))}'
    )
    return chosen, subs or []


def get_streams_data(
        page_url: str,
        src_bytes: bytes,
) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
    html = src_bytes.decode('utf-8', errors='replace')
    record = video_record(extract_initial_data(html))
    from providers.hellspy.account_videos import client_video_id, is_public_video
    video_id = client_video_id(page_url)
    if video_id:
        streams, subs, meta = _client_streams(page_url, html, video_id, record)
        if not is_public_video(meta):
            return None, None
        return _account_playback_streams(streams, subs, page_url, meta)

    if record is None:
        dprint(f'hellspy get_stream_data(): no video payload for {page_url}')
        return None, None

    conversions = ordered_conversions(record.get('conversions'))
    streams, subs = _streams_from_pairs(page_url, conversions, record)
    if streams:
        dprint(
            f'hellspy get_stream_data(): streams={len(streams)} subs={len(subs)} '
            f'title={record.get("title")!r}'
        )
    else:
        dprint(f'hellspy get_stream_data(): no conversions for {page_url}')
        subs = subs or []
    streams, subs = _with_playable_source(streams, subs, page_url, record, html)
    if not streams:
        return None, None
    return streams, subs
