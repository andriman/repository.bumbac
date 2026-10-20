import os
import shutil

from cache.paths import (
    ensure_cache_dirs,
    get_legacy_profile_subtitle_cache_dir,
    get_legacy_search_cache_dir,
    get_legacy_subtitles_dir,
    get_migration_flag_path,
    get_search_cache_dir,
    get_subtitle_cache_dir,
)
from utils.utils import dprint


def _move_files(src_dir: str, dst_dir: str) -> int:
    if not os.path.isdir(src_dir):
        return 0
    os.makedirs(dst_dir, exist_ok=True)
    moved = 0
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(dst_dir, name)
        if os.path.exists(dst):
            try:
                os.remove(src)
            except OSError as exc:
                dprint(f'cache migrate: could not remove duplicate {src}: {exc}')
            continue
        try:
            shutil.move(src, dst)
            moved += 1
        except OSError as exc:
            dprint(f'cache migrate: move failed {src} -> {dst}: {exc}')
    return moved


def _remove_dir_if_empty(path: str) -> None:
    if not os.path.isdir(path):
        return
    try:
        if not os.listdir(path):
            os.rmdir(path)
    except OSError as exc:
        dprint(f'cache migrate: could not remove dir {path}: {exc}')


def _delete_legacy_subtitle_txts(path: str) -> int:
    if not os.path.isdir(path):
        return 0
    removed = 0
    for name in os.listdir(path):
        if not name.lower().endswith('.txt'):
            continue
        file_path = os.path.join(path, name)
        if not os.path.isfile(file_path):
            continue
        try:
            os.remove(file_path)
            removed += 1
        except OSError as exc:
            dprint(f'cache migrate: could not remove legacy subtitle {file_path}: {exc}')
    return removed


def migrate_cache_layout_if_needed() -> None:
    """One-time move from legacy cache locations to profile/cache/."""
    ensure_cache_dirs()
    flag = get_migration_flag_path()
    if os.path.isfile(flag):
        return

    search_moved = _move_files(get_legacy_search_cache_dir(), get_search_cache_dir())
    subtitle_moved = _move_files(
        get_legacy_profile_subtitle_cache_dir(),
        get_subtitle_cache_dir(),
    )
    legacy_txt_removed = _delete_legacy_subtitle_txts(get_legacy_subtitles_dir())

    _remove_dir_if_empty(get_legacy_search_cache_dir())
    _remove_dir_if_empty(get_legacy_profile_subtitle_cache_dir())

    try:
        with open(flag, 'w', encoding='utf-8') as handle:
            handle.write('1\n')
    except OSError as exc:
        dprint(f'cache migrate: could not write flag {flag}: {exc}')

    if search_moved or subtitle_moved or legacy_txt_removed:
        dprint(
            f'cache migrate: search={search_moved} subtitles={subtitle_moved} '
            f'legacy_txt={legacy_txt_removed}'
        )
