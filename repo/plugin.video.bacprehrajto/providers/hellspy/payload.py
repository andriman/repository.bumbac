"""Parse HellSpy Next.js payloads. No Kodi imports so the HTML samples can be checked locally."""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

_JS_ESCAPE_RE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/])')
_MIN_HEIGHT = 144


def _unescape_js(text: str) -> str:
    def repl(match):
        seq = match.group(0)
        if seq == r'\"':
            return '"'
        if seq == r'\\':
            return '\\'
        if seq == r'\/':
            return '/'
        return chr(int(seq[2:], 16))

    return _JS_ESCAPE_RE.sub(repl, text)


def _json_object_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


def _loads_object(chunk: str) -> Optional[dict]:
    if not chunk.startswith('{'):
        return None
    decoded = _unescape_js(chunk) if chunk.startswith('{\\') else chunk
    end = _json_object_end(decoded, 0)
    if end < 0:
        return None
    try:
        data = json.loads(decoded[:end])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _read_js_string(html: str, start: int) -> Tuple[str, int]:
    """Read a JS string literal body, keeping escape sequences for a later unescape."""
    chars = []
    index = start
    length = len(html)
    while index < length:
        char = html[index]
        if char == '\\' and index + 1 < length:
            chars.append(html[index:index + 2])
            index += 2
            continue
        if char == '"':
            return ''.join(chars), index
        chars.append(char)
        index += 1
    return ''.join(chars), index


def _join_next_flight(html: str) -> str:
    """Concatenate self.__next_f.push string chunks. Next.js splits one payload across script tags."""
    marker = 'self.__next_f.push([1,"'
    parts = []
    pos = 0
    while True:
        idx = html.find(marker, pos)
        if idx < 0:
            break
        raw, end = _read_js_string(html, idx + len(marker))
        if raw:
            parts.append(raw)
        pos = end + 1
    if not parts:
        return ''
    return _unescape_js(''.join(parts))


def _initial_data_from_text(text: str) -> Optional[dict]:
    pos = 0
    marker = 'initialData'
    while True:
        idx = text.find(marker, pos)
        if idx < 0:
            return None
        brace = text.find('{', idx)
        if brace < 0:
            return None
        data = _loads_object(text[brace:])
        if isinstance(data, dict) and data.get('kind') in ('search', 'video'):
            return data
        pos = idx + len(marker)


def extract_initial_data(html: str) -> Optional[dict]:
    """Read the Next.js initialData object embedded in a saved or live page."""
    if not html:
        return None
    flight = _join_next_flight(html)
    if flight:
        data = _initial_data_from_text(flight)
        if data is not None:
            return data
    return _initial_data_from_text(html)


def search_page(payload: Any) -> Tuple[List[dict], Optional[Any]]:
    """Return GWSearchVideo dicts and the next cursor from a page or API body."""
    if not isinstance(payload, dict):
        return [], None
    data = payload.get('data') if payload.get('kind') == 'search' else payload
    if not isinstance(data, dict):
        return [], None
    items = data.get('items')
    if not isinstance(items, list):
        return [], None
    videos = [item for item in items if isinstance(item, dict)]
    return videos, data.get('nextOffset')


def has_next_offset(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def same_offset(left: Any, right: Any) -> bool:
    if not has_next_offset(left) or not has_next_offset(right):
        return False
    return str(left) == str(right)


def video_record(payload: Any) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    if payload.get('kind') == 'video':
        data = payload.get('data')
        return data if isinstance(data, dict) else None
    if payload.get('objectType') == 'GWVideo' or 'conversions' in payload:
        return payload
    return None


def conversion_quality(key: str) -> int:
    try:
        height = int(str(key).strip())
    except (TypeError, ValueError):
        return 0
    if height >= _MIN_HEIGHT:
        return height
    return 0


def ordered_conversions(conversions: Any) -> List[Tuple[str, str]]:
    if not isinstance(conversions, dict):
        return []
    pairs: List[Tuple[str, str]] = []
    for key, url in conversions.items():
        if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
            continue
        pairs.append((str(key), url))
    pairs.sort(key=lambda item: (conversion_quality(item[0]) == 0, -conversion_quality(item[0]), item[0]))
    return pairs


def subtitle_entries(raw: Any) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    entries: List[Dict[str, str]] = []
    seen_labels = set()
    for item in raw:
        url = ''
        label = ''
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            for field in ('url', 'src', 'path'):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    url = value.strip()
                    break
            for field in ('title', 'language', 'label'):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    label = value.strip()
                    break
            if not label and item.get('id') is not None:
                label = str(item.get('id'))
        if not url.startswith(('http://', 'https://')):
            continue
        if not label:
            label = url.rsplit('/', 1)[-1].split('?', 1)[0] or 'sub'
        if label in seen_labels:
            label = f'{label}_{len(entries) + 1}'
        seen_labels.add(label)
        entries.append({'label': label, 'url': url})
    return entries
