import os

import xbmcvfs

from common import _ADDON_ID, addon, translated_path

_CACHE_ROOT_NAME = 'cache'
_SEARCH_DIR_NAME = 'search'
_SUBTITLE_DIR_NAME = 'subtitles'
_MIGRATION_FLAG = '.migrated'

_LEGACY_SEARCH_DIR = os.path.join(translated_path, 'resources', 'cache', 'search')
_LEGACY_SUBTITLES_DIR = os.path.join(translated_path, 'resources', 'subtitles')
_LEGACY_PROFILE_SUBTITLE_DIRNAME = 'subtitle_cache'


def get_profile_path() -> str:
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.exists(profile):
        os.makedirs(profile)
    return profile


def get_cache_root() -> str:
    return os.path.join(get_profile_path(), _CACHE_ROOT_NAME)


def get_search_cache_dir() -> str:
    return os.path.join(get_cache_root(), _SEARCH_DIR_NAME)


def get_subtitle_cache_dir() -> str:
    return os.path.join(get_cache_root(), _SUBTITLE_DIR_NAME)


def get_migration_flag_path() -> str:
    return os.path.join(get_cache_root(), _MIGRATION_FLAG)


def get_legacy_search_cache_dir() -> str:
    return _LEGACY_SEARCH_DIR


def get_legacy_subtitles_dir() -> str:
    return _LEGACY_SUBTITLES_DIR


def get_legacy_profile_subtitle_cache_dir() -> str:
    return os.path.join(get_profile_path(), _LEGACY_PROFILE_SUBTITLE_DIRNAME)


def ensure_cache_dirs() -> None:
    os.makedirs(get_search_cache_dir(), exist_ok=True)
    os.makedirs(get_subtitle_cache_dir(), exist_ok=True)


_initialized = False


def ensure_cache_initialized() -> None:
    global _initialized
    if _initialized:
        return
    from cache.migrate import migrate_cache_layout_if_needed
    migrate_cache_layout_if_needed()
    ensure_cache_dirs()
    _initialized = True
