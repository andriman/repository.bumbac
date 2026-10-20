"""Persist and restore container view modes per content type.

Saves view IDs for movies/tvshows/seasons/episodes (and videos) so Years pages,
Další pagination, and different series share the same layout.

Saving happens:
  - while browsing (service poll) — catches skin view changes without leaving
  - when building a new plugin directory — backup path

Restoring happens after endOfDirectory via Container.SetViewMode with retries.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

import xbmc
import xbmcaddon
import xbmcplugin
import xbmcvfs

_ADDON_ID = 'plugin.video.bacprehrajto'

_CONTENT_TYPES = ('movies', 'tvshows', 'seasons', 'episodes', 'videos')

_SETTING_ENABLED = 'viewmode_remember'
_SETTING_PREFIX = 'viewmode_'

# Pending content for the current plugin directory build (handle -> content).
_pending_content: Dict[int, str] = {}

# Last seen view per content (avoids repeated setSetting; used if settings lag).
_last_seen: Dict[str, int] = {}
_file_state: Optional[Dict[str, int]] = None


def _addon() -> xbmcaddon.Addon:
    return xbmcaddon.Addon(id=_ADDON_ID)


def is_remember_enabled() -> bool:
    try:
        return _addon().getSetting(_SETTING_ENABLED) != 'false'
    except Exception:
        return True


def _setting_id(content: str) -> str:
    return _SETTING_PREFIX + str(content or '').strip().lower()


def _state_path() -> str:
    profile = xbmcvfs.translatePath(f'special://profile/addon_data/{_ADDON_ID}/')
    try:
        if profile and not os.path.isdir(profile):
            os.makedirs(profile, exist_ok=True)
    except OSError:
        pass
    return os.path.join(profile, 'viewmodes.json')


def _load_file_state() -> Dict[str, int]:
    global _file_state
    if _file_state is not None:
        return _file_state
    _file_state = {}
    path = _state_path()
    try:
        if path and os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for key, value in data.items():
                    try:
                        view_id = int(value)
                    except (TypeError, ValueError):
                        continue
                    if key in _CONTENT_TYPES and view_id > 0:
                        _file_state[str(key)] = view_id
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        _file_state = {}
    return _file_state


def _save_file_state() -> None:
    state = _load_file_state()
    path = _state_path()
    if not path:
        return
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(state, fh)
    except OSError:
        pass


def get_saved_view_id(content: str) -> Optional[int]:
    if not content or content not in _CONTENT_TYPES:
        return None
    if content in _last_seen and _last_seen[content] > 0:
        return _last_seen[content]
    file_state = _load_file_state()
    if content in file_state and file_state[content] > 0:
        return file_state[content]
    try:
        raw = (_addon().getSetting(_setting_id(content)) or '').strip()
    except Exception:
        return None
    if not raw or not raw.isdigit():
        return None
    view_id = int(raw)
    return view_id if view_id > 0 else None


def save_view_id(content: str, view_id: int) -> None:
    if not content or content not in _CONTENT_TYPES:
        return
    try:
        view_id = int(view_id)
    except (TypeError, ValueError):
        return
    if view_id <= 0:
        return
    if _last_seen.get(content) == view_id:
        # Still ensure disk/settings catch up if empty.
        file_state = _load_file_state()
        if file_state.get(content) == view_id:
            return
    _last_seen[content] = view_id
    file_state = _load_file_state()
    if file_state.get(content) != view_id:
        file_state[content] = view_id
        _save_file_state()
    try:
        current_setting = (_addon().getSetting(_setting_id(content)) or '').strip()
        if current_setting != str(view_id):
            _addon().setSetting(_setting_id(content), str(view_id))
    except Exception:
        pass


def _parse_viewmode_label(raw: str) -> Optional[int]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        return value if value > 0 else None
    digits = ''.join(ch if ch.isdigit() else ' ' for ch in text).split()
    for token in reversed(digits):
        try:
            value = int(token)
            if value > 0:
                return value
        except ValueError:
            continue
    return None


def current_container_content() -> Optional[str]:
    for content in _CONTENT_TYPES:
        try:
            if xbmc.getCondVisibility('Container.Content(%s)' % content):
                return content
        except Exception:
            continue
    return None


def current_container_view_id() -> Optional[int]:
    labels = (
        'Container.Viewmode',
        'Container.Property(viewmode)',
        'Container.Property(ViewMode)',
    )
    for label in labels:
        try:
            raw = xbmc.getInfoLabel(label)
        except Exception:
            continue
        view_id = _parse_viewmode_label(raw)
        if view_id:
            return view_id
    return None


def remember_current_container_view() -> None:
    """Save view mode of the currently displayed container."""
    if not is_remember_enabled():
        return
    content = current_container_content()
    if not content:
        return
    view_id = current_container_view_id()
    if view_id:
        save_view_id(content, view_id)


def poll_and_remember() -> None:
    """Called from the addon service — persist view while the user stays on a listing."""
    if not is_remember_enabled():
        return
    try:
        if not xbmc.getCondVisibility('Window.IsVisible(Videos)'):
            return
    except Exception:
        return
    try:
        path = (xbmc.getInfoLabel('Container.FolderPath') or '').lower()
    except Exception:
        path = ''
    # Only track our plugin (or unknown path with an active media content type).
    if path:
        if _ADDON_ID not in path and 'bacprehrajto' not in path:
            return
    elif not current_container_content():
        return
    remember_current_container_view()


def apply_saved_view(content: str) -> None:
    if not is_remember_enabled() or not content:
        return
    view_id = get_saved_view_id(content)
    if not view_id:
        return

    matched = False
    try:
        for _ in range(60):
            if xbmc.getCondVisibility('Container.Content(%s)' % content):
                matched = True
                break
            xbmc.sleep(50)
    except Exception:
        matched = False
    if not matched:
        xbmc.sleep(150)

    # Skins often apply path-based views after endOfDirectory; retry SetViewMode.
    try:
        for _ in range(10):
            xbmc.executebuiltin('Container.SetViewMode(%d)' % view_id)
            xbmc.sleep(100)
            try:
                if not xbmc.getCondVisibility('Container.Content(%s)' % content):
                    continue
            except Exception:
                pass
            current = current_container_view_id()
            if current == view_id:
                break
    except Exception:
        try:
            xbmc.executebuiltin('Container.SetViewMode(%d)' % view_id)
        except Exception:
            pass


def set_pending_content(handle: int, content: str) -> None:
    if handle is None:
        return
    # Capture current view before this listing replaces the container.
    try:
        remember_current_container_view()
    except Exception:
        pass
    _pending_content[int(handle)] = (content or '').strip().lower()


def end_of_directory(
        handle: int,
        succeeded: bool = True,
        update_listing: bool = False,
        cache_to_disc: bool = True,
) -> None:
    """Remember previous view, finish directory, apply saved view for pending content."""
    content = _pending_content.pop(int(handle), '') if handle is not None else ''
    try:
        remember_current_container_view()
    except Exception:
        pass
    try:
        xbmcplugin.endOfDirectory(handle, succeeded, update_listing, cache_to_disc)
    except TypeError:
        try:
            xbmcplugin.endOfDirectory(handle, succeeded, update_listing)
        except TypeError:
            xbmcplugin.endOfDirectory(handle)
    if succeeded and content:
        try:
            apply_saved_view(content)
        except Exception:
            pass
