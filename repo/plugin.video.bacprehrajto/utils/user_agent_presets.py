"""Preset and custom User-Agent resolution for HTTP requests."""
from typing import List, Tuple

import xbmcaddon

_ADDON_ID = 'plugin.video.bacprehrajto'

# (label for settings enum, User-Agent string)
USER_AGENT_PRESETS: List[Tuple[str, str]] = [
    (
        'Firefox (Windows)',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0',
    ),
    (
        'Firefox (Linux)',
        'Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0',
    ),
    (
        'Chrome (Windows)',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Safari/537.36',
    ),
    (
        'Chrome (macOS)',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Safari/537.36',
    ),
    (
        'Chrome (Android)',
        'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Mobile Safari/537.36',
    ),
    (
        'Safari (iOS)',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
        '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    ),
    (
        'Edge (Windows)',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
    ),
]

USER_AGENT_PRESET_LABELS = '|'.join(label for label, _ in USER_AGENT_PRESETS)

DEFAULT_USER_AGENT = USER_AGENT_PRESETS[0][1]


def _preset_index(addon: xbmcaddon.Addon) -> int:
    raw = addon.getSetting('user_agent_preset') or ''
    if str(raw).strip().isdigit():
        idx = int(str(raw).strip())
        if 0 <= idx < len(USER_AGENT_PRESETS):
            return idx
    label = str(raw).strip()
    for i, (preset_label, _) in enumerate(USER_AGENT_PRESETS):
        if preset_label == label:
            return i
    return 0


def _addon_instance(addon: xbmcaddon.Addon = None) -> xbmcaddon.Addon:
    """Fresh instance so getSetting sees changes made in the settings UI."""
    if addon is not None:
        return addon
    return xbmcaddon.Addon(id=_ADDON_ID)


def get_preset_user_agent(addon: xbmcaddon.Addon = None) -> str:
    addon = _addon_instance(addon)
    return USER_AGENT_PRESETS[_preset_index(addon)][1]


def is_user_agent_override_enabled(addon: xbmcaddon.Addon = None) -> bool:
    addon = _addon_instance(addon)
    return addon.getSetting('user_agent_override') == 'true'


def resolve_user_agent(addon: xbmcaddon.Addon = None) -> str:
    addon = _addon_instance(addon)
    if is_user_agent_override_enabled(addon):
        custom = (addon.getSetting('user_agent') or '').strip()
        return custom or DEFAULT_USER_AGENT
    return get_preset_user_agent(addon)


def refresh_user_agent_setting(addon: xbmcaddon.Addon = None) -> str:
    """Update the User-Agent text field to match the selected preset (when not overriding)."""
    addon = _addon_instance(addon)
    effective = resolve_user_agent(addon)
    if not is_user_agent_override_enabled(addon):
        preset_ua = get_preset_user_agent(addon)
        effective = preset_ua
        try:
            current = (addon.getSetting('user_agent') or '').strip()
            if current != preset_ua:
                addon.setSetting('user_agent', preset_ua)
        except Exception:
            pass
    return effective
