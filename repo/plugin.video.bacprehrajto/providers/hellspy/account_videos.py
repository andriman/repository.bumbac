"""HellSpy account video list and public/private changes."""
import re
from typing import Any, Dict, List, Optional, Tuple

from common import get_hellspy_api_base, get_hellspy_base
from providers.hellspy.auth import ensure_access_token, request_headers
from providers.hellspy.payload import ordered_conversions
from providers.hellspy.session import get_session, save_session
from utils.StrUtils import convert_size
from utils.utils import dprint

_TIMEOUT = 30
_MAX_PAGES = 20
_CLIENT_VIDEO_ID = re.compile(r'/client/video/(\d+)(?:[/?#]|$)')
_FILE_MP4_RE = re.compile(r'https?://[^\s"\'<>]+?/file\.mp4(?:\?[^\s"\'<>]*)?', re.IGNORECASE)


def client_video_id(page_url: str) -> str:
    match = _CLIENT_VIDEO_ID.search(page_url or '')
    if not match:
        return ''
    return match.group(1)


def _video_id(value: object) -> str:
    text = str(value or '').strip()
    if text.isdigit():
        return text
    return ''


def _clock_label(duration: object) -> str:
    seconds = _duration_seconds(duration)
    if seconds is None:
        return ''
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}'


def _duration_seconds(duration: object) -> Optional[int]:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return None
    if duration <= 0:
        return None
    return int(duration)


def _size_label(size: object) -> str:
    try:
        return convert_size(int(size), 2)
    except (TypeError, ValueError):
        return ''


def _size_bytes(size: object) -> Optional[int]:
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return None
    if size < 0:
        return None
    return int(size)


def _first_thumb(raw: object) -> str:
    if not isinstance(raw, list):
        return ''
    for candidate in raw:
        if isinstance(candidate, str) and candidate.strip().startswith(('http://', 'https://')):
            return candidate.strip()
    return ''


def _api_headers(referer: str) -> dict:
    base = get_hellspy_base().rstrip('/')
    return request_headers({
        'Accept': 'application/json',
        'Origin': base,
        'Referer': referer,
    })


def _require_token() -> None:
    if not ensure_access_token():
        raise RuntimeError('Pro Moje videa se musíte přihlásit')


def _video_object(payload: Any) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    if any(key in payload for key in ('public', 'filename', 'fullFilename', 'thumbnailUrls')):
        return payload
    data = payload.get('data')
    if isinstance(data, dict):
        nested = _video_object(data)
        return nested if nested is not None else data
    items = payload.get('items')
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                return item
    if payload.get('id') is not None:
        return payload
    return None


def _clean_url(url: str) -> str:
    text = (url or '').strip().replace('\\/', '/').replace('\\u0026', '&').replace('&amp;', '&')
    return text.rstrip('\\')


def _remember_url(url: str, seen: set, pairs: List[Tuple[str, str]], key: str) -> None:
    cleaned = _clean_url(url)
    if not cleaned.startswith(('http://', 'https://')):
        return
    if '/file.mp4' not in cleaned.lower():
        return
    if cleaned in seen:
        return
    seen.add(cleaned)
    pairs.append((key, cleaned))


def _walk_file_mp4(value: Any, seen: set, pairs: List[Tuple[str, str]], key: str, skip_public_url: bool) -> None:
    if isinstance(value, str):
        _remember_url(value, seen, pairs, key)
        return
    if isinstance(value, dict):
        for field, nested in value.items():
            if skip_public_url and field == 'publicUrl':
                continue
            if field in ('thumbnailUrls', 'thumbs'):
                continue
            _walk_file_mp4(nested, seen, pairs, key, skip_public_url=True)
        return
    if isinstance(value, list):
        for nested in value:
            _walk_file_mp4(nested, seen, pairs, key, skip_public_url=False)


def playback_pairs(detail: Optional[dict], html: str = '') -> List[Tuple[str, str]]:
    """Signed file.mp4 URLs. publicUrl is a different download link and is ignored."""
    pairs: List[Tuple[str, str]] = []
    seen = set()
    if isinstance(detail, dict):
        for key, url in ordered_conversions(detail.get('conversions')):
            _remember_url(url, seen, pairs, key)
        height = detail.get('height')
        key = 'MP4'
        if isinstance(height, (int, float)) and not isinstance(height, bool) and int(height) >= 144:
            key = str(int(height))
        _walk_file_mp4(detail, seen, pairs, key, skip_public_url=True)
    for match in _FILE_MP4_RE.findall(html or ''):
        _remember_url(match, seen, pairs, 'MP4')
    return pairs


def _entry(item: dict, base: str) -> Optional[dict]:
    video_id = _video_id(item.get('id'))
    if not video_id:
        return None
    title = str(item.get('filename') or item.get('fullFilename') or '').strip()
    if not title:
        title = f'Video {video_id}'
    return {
        'id': video_id,
        'title': title,
        'public': bool(item.get('public')),
        'page_url': f'{base}/client/video/{video_id}',
        'size_label': _size_label(item.get('size')),
        'duration_label': _clock_label(item.get('duration')),
        'duration_seconds': _duration_seconds(item.get('duration')),
        'size_bytes': _size_bytes(item.get('size')),
        'thumb': _first_thumb(item.get('thumbnailUrls')),
    }


def _account_client_id() -> str:
    from providers.hellspy.auth import fetch_identity

    identity = fetch_identity()
    if not isinstance(identity, dict):
        return ''
    client = identity.get('client')
    if isinstance(client, dict):
        return _video_id(client.get('id'))
    return _video_id(client)


def fetch_my_videos() -> List[dict]:
    """GET /clients/{id}/videos. Follows offset until it is null."""
    _require_token()
    client_id = _account_client_id()
    if not client_id:
        dprint('hellspy my videos: missing client id')
        raise RuntimeError('Moje videa se nepodařilo načíst')
    base = get_hellspy_base().rstrip('/')
    session = get_session()
    client_url = base + '/client'
    try:
        dprint(f'hellspy my videos: GET {client_url}')
        session.get(client_url, headers=_api_headers(base + '/'), timeout=_TIMEOUT)
        save_session()
    except Exception as exc:
        dprint(f'hellspy my videos: client page: {exc}')

    items: List[dict] = []
    seen_ids = set()
    offset = None
    seen_offsets = set()
    api_url = get_hellspy_api_base().rstrip('/') + '/clients/' + client_id + '/videos'
    for _page in range(_MAX_PAGES):
        params = {}
        if offset is not None:
            params['offset'] = offset
        try:
            dprint(f'hellspy my videos: GET {api_url} offset={offset!r}')
            response = session.get(
                api_url,
                params=params or None,
                headers=_api_headers(client_url),
                timeout=_TIMEOUT,
            )
        except Exception as exc:
            dprint(f'hellspy my videos: {exc}')
            raise RuntimeError('Moje videa se nepodařilo načíst')
        if response.status_code in (401, 403):
            dprint(f'hellspy my videos: HTTP {response.status_code} {response.text[:300]}')
            if not ensure_access_token():
                raise RuntimeError('Pro Moje videa se musíte přihlásit')
            raise RuntimeError('Moje videa se nepodařilo načíst')
        if not response.ok:
            dprint(f'hellspy my videos: HTTP {response.status_code} {response.text[:300]}')
            raise RuntimeError('Moje videa se nepodařilo načíst')
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError('Moje videa se nepodařilo načíst')
        if not isinstance(payload, dict):
            break
        batch = payload.get('items')
        if not isinstance(batch, list) or not batch:
            break
        for raw in batch:
            if not isinstance(raw, dict):
                continue
            entry = _entry(raw, base)
            if entry is None or entry['id'] in seen_ids:
                continue
            seen_ids.add(entry['id'])
            items.append(entry)
        next_offset = payload.get('offset')
        if next_offset is None:
            break
        if isinstance(next_offset, str) and not next_offset.strip():
            break
        marker = str(next_offset)
        if marker in seen_offsets or (offset is not None and marker == str(offset)):
            break
        seen_offsets.add(marker)
        offset = next_offset
    return items


def _conversion_entry(item: dict, video_id: str) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    if item.get('active') is False or item.get('valid') is False:
        return None
    linked = item.get('video')
    if linked is not None and _video_id(linked) != video_id:
        return None
    url = _clean_url(str(item.get('publicUrl') or ''))
    if '/file.mp4' not in url.lower() or not url.startswith(('http://', 'https://')):
        return None
    height = item.get('height')
    key = 'MP4'
    if isinstance(height, (int, float)) and not isinstance(height, bool) and int(height) >= 144:
        key = str(int(height))
    return {
        'key': key,
        'url': url,
        'size': item.get('size'),
        'height': int(height) if key != 'MP4' else 0,
    }


def fetch_video_conversions(video_id: str) -> List[dict]:
    """GET /videos/{id}/video_conversions. publicUrl on each item is the file.mp4 player."""
    video_id = _video_id(video_id)
    if not video_id or not ensure_access_token():
        return []
    base = get_hellspy_base().rstrip('/')
    page_url = f'{base}/client/video/{video_id}'
    api_url = get_hellspy_api_base().rstrip('/') + '/videos/' + video_id + '/video_conversions'
    session = get_session()
    found: List[dict] = []
    seen_urls = set()
    offset = None
    seen_offsets = set()
    saw_items = False
    for _page in range(_MAX_PAGES):
        params = {}
        if offset is not None:
            params['offset'] = offset
        try:
            dprint(f'hellspy video conversions: GET {api_url} offset={offset!r}')
            response = session.get(
                api_url,
                params=params or None,
                headers=_api_headers(page_url),
                timeout=_TIMEOUT,
            )
        except Exception as exc:
            dprint(f'hellspy video conversions: {exc}')
            return found
        if not response.ok:
            dprint(f'hellspy video conversions: HTTP {response.status_code}')
            return found
        try:
            payload = response.json()
        except ValueError:
            return found
        if not isinstance(payload, dict):
            break
        batch = payload.get('items')
        if not isinstance(batch, list) or not batch:
            break
        saw_items = True
        for raw in batch:
            entry = _conversion_entry(raw, video_id)
            if entry is None or entry['url'] in seen_urls:
                continue
            seen_urls.add(entry['url'])
            found.append(entry)
        next_offset = payload.get('offset')
        if next_offset is None:
            break
        if isinstance(next_offset, str) and not next_offset.strip():
            break
        marker = str(next_offset)
        if marker in seen_offsets or (offset is not None and marker == str(offset)):
            break
        seen_offsets.add(marker)
        offset = next_offset
    if saw_items and not found:
        dprint(f'hellspy video conversions: video {video_id} has no playback url')
    found.sort(key=lambda item: (-int(item.get('height') or 0), item['key']))
    return found


def fetch_video_detail(video_id: str) -> Optional[dict]:
    video_id = _video_id(video_id)
    if not video_id or not ensure_access_token():
        return None
    base = get_hellspy_base().rstrip('/')
    page_url = f'{base}/client/video/{video_id}'
    api_url = get_hellspy_api_base().rstrip('/') + '/videos/' + video_id
    try:
        dprint(f'hellspy video detail: GET {api_url}')
        response = get_session().get(
            api_url,
            headers=_api_headers(page_url),
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        dprint(f'hellspy video detail: {exc}')
        return None
    if not response.ok:
        dprint(f'hellspy video detail: HTTP {response.status_code}')
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return _video_object(payload)


def set_video_public(video_id: str, public: bool) -> bool:
    video_id = _video_id(video_id)
    if not video_id:
        return False
    _require_token()
    base = get_hellspy_base().rstrip('/')
    page_url = f'{base}/client/video/{video_id}'
    api_url = get_hellspy_api_base().rstrip('/') + '/videos/' + video_id
    headers = _api_headers(page_url)
    headers['Content-Type'] = 'application/json'
    try:
        dprint(f'hellspy video visibility: PATCH {api_url} public={public}')
        response = get_session().patch(
            api_url,
            json={'public': bool(public)},
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        dprint(f'hellspy video visibility: {exc}')
        return False
    if not response.ok:
        dprint(f'hellspy video visibility: HTTP {response.status_code}')
        return False
    return True


def is_public_video(detail: Optional[dict]) -> bool:
    return isinstance(detail, dict) and detail.get('public') is True


def detail_stream_meta(detail: Optional[dict]) -> Dict[str, Any]:
    if not isinstance(detail, dict):
        return {}
    return {
        'size': detail.get('size'),
        'duration': detail.get('duration'),
        'title': str(detail.get('filename') or detail.get('fullFilename') or ''),
    }
