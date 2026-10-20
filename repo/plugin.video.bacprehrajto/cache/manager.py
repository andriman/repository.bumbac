import os
from dataclasses import dataclass
from typing import Callable, Tuple

from common import addon
from cache.paths import (
    ensure_cache_initialized,
    get_legacy_profile_subtitle_cache_dir,
    get_legacy_search_cache_dir,
    get_legacy_subtitles_dir,
)
from utils.StrUtils import convert_size
from utils.utils import dprint


def format_cache_size_label(file_count: int, total_bytes: int) -> str:
    if file_count == 0:
        return '0 B (0 souborů)'
    size_str = convert_size(total_bytes, 1)
    if file_count == 1:
        files_word = '1 soubor'
    elif 2 <= file_count <= 4:
        files_word = f'{file_count} soubory'
    else:
        files_word = f'{file_count} souborů'
    return f'{size_str} ({files_word})'


def _clear_dir_files(
        cache_dir: str,
        file_predicate: Callable[[str], bool],
        label: str,
) -> Tuple[int, int]:
    if not os.path.isdir(cache_dir):
        return 0, 0
    removed = 0
    freed = 0
    for name in os.listdir(cache_dir):
        if not file_predicate(name):
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
            dprint(f'{label}: could not remove {path}: {exc}')
    return removed, freed


@dataclass
class ClearResult:
    search_removed: int = 0
    search_freed: int = 0
    subtitle_removed: int = 0
    subtitle_freed: int = 0
    legacy_removed: int = 0
    legacy_freed: int = 0

    @property
    def total_removed(self) -> int:
        return self.search_removed + self.subtitle_removed + self.legacy_removed

    @property
    def total_freed(self) -> int:
        return self.search_freed + self.subtitle_freed + self.legacy_freed


def get_search_cache_stats() -> Tuple[int, int]:
    from cache.search_cache import get_search_cache_stats as _stats
    return _stats()


def get_subtitle_cache_stats() -> Tuple[int, int]:
    from cache.subtitle_cache import get_subtitle_cache_stats as _stats
    return _stats()


def get_total_cache_stats() -> Tuple[int, int]:
    search_count, search_bytes = get_search_cache_stats()
    subtitle_count, subtitle_bytes = get_subtitle_cache_stats()
    return search_count + subtitle_count, search_bytes + subtitle_bytes


def format_total_cache_size_label() -> str:
    file_count, total_bytes = get_total_cache_stats()
    return format_cache_size_label(file_count, total_bytes)


def clear_memory_caches() -> None:
    from cache.search_cache import clear_search_memory_state
    from providers.browsing_context import clear_all_browsing_context
    from providers.sledujteto.dashboard import clear_dashboard_cache
    from tmdb.tmdb import clear_genre_cache

    clear_search_memory_state()
    clear_dashboard_cache()
    clear_genre_cache()
    clear_all_browsing_context()


def _clear_legacy_orphans() -> Tuple[int, int]:
    removed = 0
    freed = 0
    for legacy_dir in (
            get_legacy_search_cache_dir(),
            get_legacy_subtitles_dir(),
            get_legacy_profile_subtitle_cache_dir(),
    ):
        r, f = _clear_dir_files(legacy_dir, lambda _name: True, 'clear_legacy_cache')
        removed += r
        freed += f
        if os.path.isdir(legacy_dir):
            try:
                if not os.listdir(legacy_dir):
                    os.rmdir(legacy_dir)
            except OSError:
                pass
    return removed, freed


def clear_all_caches() -> ClearResult:
    ensure_cache_initialized()
    from cache.search_cache import clear_search_cache as _clear_search
    from cache.subtitle_cache import clear_subtitle_cache as _clear_subtitles

    result = ClearResult()
    result.search_removed, result.search_freed = _clear_search()
    result.subtitle_removed, result.subtitle_freed = _clear_subtitles()
    result.legacy_removed, result.legacy_freed = _clear_legacy_orphans()
    clear_memory_caches()
    return result


def _set_readonly_setting(setting_id: str, label: str) -> None:
    try:
        current = addon.getSetting(setting_id) or ''
        if current != label:
            addon.setSetting(setting_id, label)
    except Exception as exc:
        dprint(f'refresh_cache_setting({setting_id}): {exc}')


def refresh_all_cache_settings() -> None:
    ensure_cache_initialized()
    from cache.search_cache import refresh_search_cache_setting
    from cache.subtitle_cache import refresh_subtitle_cache_setting

    refresh_search_cache_setting()
    refresh_subtitle_cache_setting()
    _set_readonly_setting('total_cache_size_info', format_total_cache_size_label())


def refresh_total_cache_setting() -> str:
    label = format_total_cache_size_label()
    _set_readonly_setting('total_cache_size_info', label)
    return label
