import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import xbmcgui

from common import (
    SEARCH_SOURCE_NO_RESULTS_PROP,
    addon,
    g_is_prehrajto_enabled,
    g_is_sledujteto_enabled,
    g_is_hellspy_enabled,
    g_is_nsfw_enabled,
    is_possible_nsfw,
    g_max_duplicities,
    g_prehrajto_max_searched_vids,
    g_sledujteto_max_searched_vids,
    g_hellspy_max_searched_vids,
    get_hellspy_base,
    g_search_cache_ttl_seconds,
    is_search_cache_enabled,
)
from cache.manager import format_cache_size_label
from cache.paths import ensure_cache_initialized, get_search_cache_dir
from utils.listitem_infotag import (
    LISTING_STREAM_INFO_PROP,
    stream_info_from_listing_property,
)
from utils.search_source_items import SEARCH_PROVIDER_PROP
from utils.stream_fake_hint import LISTING_THUMB_PROP, LISTING_UPLOAD_PROP
from utils.utils import dprint

_return_key: Optional[str] = None
_last_listing_key: Optional[str] = None


@dataclass
class _CacheEntry:
    items: List[Dict[str, Any]]
    stored_at: float
    pages_scraped: int
    is_complete: bool
    item_count: int


_cache: Dict[str, _CacheEntry] = {}


def _hellspy_auth_cache_flag() -> bool:
    try:
        from providers.hellspy.auth import uses_account_session
        return uses_account_session()
    except Exception:
        return False


def make_cache_key(query: str) -> str:
    return (
        f'{query}|p{int(g_is_prehrajto_enabled)}|s{int(g_is_sledujteto_enabled)}'
        f'|h{int(g_is_hellspy_enabled)}'
        f'|pls{g_prehrajto_max_searched_vids}|sls{g_sledujteto_max_searched_vids}'
        f'|hls{g_hellspy_max_searched_vids}|hd{get_hellspy_base()}|ha{int(_hellspy_auth_cache_flag())}|md{g_max_duplicities}'
        f'|nsfwsub{int(g_is_nsfw_enabled)}:{(addon.getSetting("nsfw_filter_keywords") or "").strip().lower()}'
        f'|ex:{(addon.getSetting("nsfw_filter_exceptions") or "").strip().lower()}'
    )


_ART_KEYS = ('thumb', 'poster', 'icon', 'fanart', 'banner', 'clearart', 'clearlogo', 'discart', 'landscape')


def _search_cache_dir() -> str:
    ensure_cache_initialized()
    return get_search_cache_dir()


def _disk_path(key: str) -> str:
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
    return os.path.join(_search_cache_dir(), f'search_{digest}.json')


def _extract_art(item: xbmcgui.ListItem) -> Dict[str, str]:
    art: Dict[str, str] = {}
    if not hasattr(item, 'getArt'):
        return art
    for art_key in _ART_KEYS:
        try:
            value = item.getArt(art_key)
        except TypeError:
            break
        if value:
            art[art_key] = value
    return art


def listitem_to_entry(item: xbmcgui.ListItem) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        'label': item.getLabel(),
        'label2': item.getLabel2(),
        'path': item.getPath(),
        'art': _extract_art(item),
        'properties': {},
        'stream_info': {},
    }
    thumb_url = item.getProperty(LISTING_THUMB_PROP)
    if thumb_url:
        entry['art']['thumb'] = thumb_url
        entry['art']['poster'] = thumb_url
    upload_raw = item.getProperty(LISTING_UPLOAD_PROP)
    if upload_raw:
        entry['properties'][LISTING_UPLOAD_PROP] = upload_raw
    if item.getProperty('IsPlayable'):
        entry['properties']['IsPlayable'] = item.getProperty('IsPlayable')
    if item.getProperty(SEARCH_SOURCE_NO_RESULTS_PROP):
        entry['properties'][SEARCH_SOURCE_NO_RESULTS_PROP] = 'true'
    provider_id = (item.getProperty(SEARCH_PROVIDER_PROP) or '').strip()
    if provider_id:
        entry['properties'][SEARCH_PROVIDER_PROP] = provider_id
    stream_from_prop = stream_info_from_listing_property(item)
    if stream_from_prop:
        entry['stream_info'] = stream_from_prop
    else:
        try:
            stream = item.getVideoStreamInfo()
            if stream:
                if isinstance(stream, dict):
                    entry['stream_info'] = dict(stream)
                else:
                    entry['stream_info'] = {
                        k: stream.get(k) for k in stream if stream.get(k) is not None
                    }
        except (AttributeError, RuntimeError, TypeError):
            pass
    if entry['stream_info']:
        entry['properties'][LISTING_STREAM_INFO_PROP] = json.dumps(entry['stream_info'])
    return entry


def entry_to_listitem(entry: Dict[str, Any]) -> xbmcgui.ListItem:
    item = xbmcgui.ListItem(
        label=entry.get('label', ''),
        label2=entry.get('label2', ''),
        path=entry.get('path', ''),
        offscreen=True,
    )
    art = entry.get('art') or {}
    if art:
        item.setArt(art)
    for prop_key, value in (entry.get('properties') or {}).items():
        if value is not None:
            item.setProperty(prop_key, str(value))
    stream_info = entry.get('stream_info') or {}
    if stream_info and not item.getProperty(LISTING_STREAM_INFO_PROP):
        item.setProperty(LISTING_STREAM_INFO_PROP, json.dumps(stream_info))
    return item


def _entry_to_dict(entry: _CacheEntry) -> Dict[str, Any]:
    return {
        'stored_at': entry.stored_at,
        'pages_scraped': entry.pages_scraped,
        'is_complete': entry.is_complete,
        'item_count': entry.item_count,
        'items': entry.items,
    }


def _entry_from_dict(data: Dict[str, Any]) -> _CacheEntry:
    return _CacheEntry(
        items=data.get('items') or [],
        stored_at=float(data.get('stored_at') or 0),
        pages_scraped=int(data.get('pages_scraped') or 0),
        is_complete=bool(data.get('is_complete')),
        item_count=int(data.get('item_count') or len(data.get('items') or [])),
    )


def _write_disk(key: str, entry: _CacheEntry) -> None:
    try:
        cache_dir = _search_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        path = _disk_path(key)
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as handle:
            json.dump(_entry_to_dict(entry), handle, ensure_ascii=False)
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp_path, path)
    except OSError as exc:
        dprint(f'search_cache: disk write failed key={key!r}: {exc}')


def _read_disk(key: str) -> Optional[_CacheEntry]:
    path = _disk_path(key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        entry = _entry_from_dict(data)
        if not entry.is_complete or not entry.items:
            return None
        age = int(time.time() - entry.stored_at)
        dprint(f'search_cache: loaded disk key={key!r} items={entry.item_count} age={age}s')
        return entry
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        dprint(f'search_cache: disk read failed key={key!r}: {exc}')
        return None


def _is_expired(entry: _CacheEntry) -> bool:
    if g_search_cache_ttl_seconds <= 0:
        return True
    return (time.time() - entry.stored_at) > g_search_cache_ttl_seconds


def _get_entry(key: str) -> Optional[_CacheEntry]:
    entry = _cache.get(key)
    if entry is not None:
        return entry
    entry = _read_disk(key)
    if entry is not None:
        _cache[key] = entry
    return entry


def get_search_cache_stats() -> Tuple[int, int]:
    """Return (file_count, total_bytes) for on-disk search cache files."""
    cache_dir = _search_cache_dir()
    if not os.path.isdir(cache_dir):
        return 0, 0

    file_count = 0
    total_bytes = 0
    for name in os.listdir(cache_dir):
        if not name.startswith('search_') or not name.endswith('.json'):
            continue
        path = os.path.join(cache_dir, name)
        if os.path.isfile(path):
            file_count += 1
            try:
                total_bytes += os.path.getsize(path)
            except OSError:
                pass
    return file_count, total_bytes


def format_search_cache_size_label() -> str:
    file_count, total_bytes = get_search_cache_stats()
    return format_cache_size_label(file_count, total_bytes)


def clear_search_memory_state() -> None:
    global _return_key, _last_listing_key
    _return_key = None
    _last_listing_key = None


def clear_search_cache() -> Tuple[int, int]:
    """Remove all search cache files and in-memory entries. Returns (files_removed, bytes_freed)."""
    global _cache
    _cache.clear()
    clear_search_memory_state()

    cache_dir = _search_cache_dir()
    if not os.path.isdir(cache_dir):
        return 0, 0

    removed = 0
    freed = 0
    for name in os.listdir(cache_dir):
        if not name.startswith('search_'):
            continue
        path = os.path.join(cache_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
            os.remove(path)
            removed += 1
            freed += size
        except OSError as exc:
            dprint(f'clear_search_cache(): could not remove {path}: {exc}')
    return removed, freed


def refresh_search_cache_setting() -> str:
    label = format_search_cache_size_label()
    try:
        current = addon.getSetting('search_cache_size_info') or ''
        if current != label:
            addon.setSetting('search_cache_size_info', label)
    except Exception as exc:
        dprint(f'refresh_search_cache_setting(): {exc}')
    try:
        from cache.manager import refresh_total_cache_setting
        refresh_total_cache_setting()
    except Exception as exc:
        dprint(f'refresh_search_cache_setting(): total refresh failed: {exc}')
    return label


def invalidate(key: str) -> None:
    if key in _cache:
        del _cache[key]
    path = _disk_path(key)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    dprint(f'search_cache: invalidated key={key!r}')


def set_cached(key: str, items: List[xbmcgui.ListItem], pages_scraped: int) -> None:
    if not is_search_cache_enabled():
        return

    serialized: List[Dict[str, Any]] = []
    for item in items:
        try:
            serialized.append(listitem_to_entry(item))
        except Exception as exc:
            dprint(f'search_cache: skip item {item.getLabel()!r}: {exc}')

    if not serialized:
        dprint(f'search_cache: nothing to store for key={key!r}')
        return

    entry = _CacheEntry(
        items=serialized,
        stored_at=time.time(),
        pages_scraped=pages_scraped,
        is_complete=True,
        item_count=len(serialized),
    )
    _cache[key] = entry
    _write_disk(key, entry)
    dprint(
        f'search_cache: store complete key={key!r} '
        f'items={entry.item_count} pages={pages_scraped}'
    )


def _cached_entry_hidden(raw: Dict[str, Any]) -> bool:
    if g_is_nsfw_enabled:
        return False
    properties = raw.get('properties') or {}
    if properties.get(SEARCH_SOURCE_NO_RESULTS_PROP):
        return False
    return is_possible_nsfw(raw.get('label') or '')


def _visible_cached_items(entry: _CacheEntry) -> List[Dict[str, Any]]:
    return [raw for raw in entry.items if not _cached_entry_hidden(raw)]


def _entry_to_listitems(entry: _CacheEntry) -> List[xbmcgui.ListItem]:
    return [entry_to_listitem(raw) for raw in _visible_cached_items(entry)]


def try_load_cache(key: str, force_refresh: bool = False) -> Optional[List[xbmcgui.ListItem]]:
    global _return_key

    if force_refresh:
        return None

    if not is_search_cache_enabled():
        _return_key = None
        return None

    play_return = _return_key is not None and _return_key == key
    if play_return:
        _return_key = None
        entry = _get_entry(key)
        if entry is not None:
            age = int(time.time() - entry.stored_at)
            dprint(
                f'search_cache: play-return hit (ttl ignored) key={key!r} '
                f'items={entry.item_count} age={age}s'
            )
            return _entry_to_listitems(entry)
        dprint(f'search_cache: play-return miss key={key!r}')
        return None

    if g_search_cache_ttl_seconds <= 0:
        return None

    entry = _get_entry(key)
    if entry is None:
        dprint(f'search_cache: miss key={key!r} reason=empty')
        return None
    if _is_expired(entry):
        dprint(f'search_cache: miss key={key!r} reason=expired')
        return None

    age = int(time.time() - entry.stored_at)
    source = 'memory' if key in _cache else 'disk'
    dprint(
        f'search_cache: hit {source} key={key!r} '
        f'items={entry.item_count} age={age}s'
    )
    return _entry_to_listitems(entry)


def get_cached_item_count(key: str) -> Optional[int]:
    entry = _get_entry(key)
    if entry is None:
        return None
    return len(_visible_cached_items(entry))


def has_any_cache(key: str) -> bool:
    return _get_entry(key) is not None


def is_cache_enabled() -> bool:
    return is_search_cache_enabled()


def set_last_listing_key(key: str) -> None:
    global _last_listing_key
    _last_listing_key = key


def mark_play_return() -> None:
    global _return_key
    if not is_search_cache_enabled():
        return
    _return_key = _last_listing_key
    if _return_key:
        dprint(f'search_cache: play return armed for key={_return_key!r}')
