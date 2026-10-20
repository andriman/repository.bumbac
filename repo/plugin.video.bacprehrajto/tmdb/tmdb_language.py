from typing import Dict, List, Optional

import xbmcgui

from common import addon

_TMDB_API_LOCALE = {
    'en': 'en-US',
    'cs': 'cs-CZ',
}

_TMDB_LANGUAGE_LABELS: Dict[str, str] = {
    'en': 'English (EN)',
    'cs': 'Čeština (CS)',
    'sk': 'Slovenčina (SK)',
    'de': 'Deutsch (DE)',
    'fr': 'Français (FR)',
    'es': 'Español (ES)',
    'it': 'Italiano (IT)',
    'pl': 'Polski (PL)',
    'hu': 'Magyar (HU)',
}

_SETTING_LANGUAGES = 'tmdb_languages'
_SETTING_DEFAULT = 'tmdb_default_language'
_SETTING_ACTIVE = 'tmdb_active_language'
_SETTING_SHOW_ROW = 'tmdb_show_language_row'


def parse_tmdb_languages() -> List[str]:
    raw = addon.getSetting(_SETTING_LANGUAGES) or 'en,cs'
    seen = set()
    langs: List[str] = []
    for part in raw.split(','):
        code = part.strip().lower()
        if code and code not in seen:
            seen.add(code)
            langs.append(code)
    return langs or ['en']


def get_tmdb_default_language() -> str:
    langs = parse_tmdb_languages()
    default = (addon.getSetting(_SETTING_DEFAULT) or 'en').strip().lower()
    if default in langs:
        return default
    return langs[0]


def _normalize_active_language() -> str:
    langs = parse_tmdb_languages()
    active = (addon.getSetting(_SETTING_ACTIVE) or '').strip().lower()
    if active in langs:
        return active
    default = get_tmdb_default_language()
    addon.setSetting(_SETTING_ACTIVE, default)
    return default


def get_tmdb_active_language() -> str:
    return _normalize_active_language()


def set_tmdb_active_language(code: str) -> None:
    code = (code or '').strip().lower()
    langs = parse_tmdb_languages()
    if code not in langs:
        code = get_tmdb_default_language()
    addon.setSetting(_SETTING_ACTIVE, code)


def get_tmdb_language_choice_label(code: str) -> str:
    code = (code or '').strip().lower()
    if not code:
        return ''
    return _TMDB_LANGUAGE_LABELS.get(code, f'{code.upper()} ({code})')


def pick_tmdb_active_language_dialog() -> Optional[str]:
    """
    Let the user pick the active TMDB language from configured languages.
    Returns the new language code, or None if cancelled / unchanged.
    """
    langs = parse_tmdb_languages()
    if not langs:
        return None

    labels = [get_tmdb_language_choice_label(code) for code in langs]
    current = get_tmdb_active_language()
    preselect = langs.index(current) if current in langs else 0

    idx = xbmcgui.Dialog().select(
        'TMDB — jazyk hledání',
        labels,
        preselect=preselect,
    )
    if idx < 0 or idx >= len(langs):
        return None

    new_code = langs[idx]
    if new_code == current:
        return None

    set_tmdb_active_language(new_code)
    return new_code


def get_tmdb_api_language_for(code: str) -> str:
    code = (code or '').strip().lower()
    if not code:
        code = get_tmdb_active_language()
    return _TMDB_API_LOCALE.get(code, f'{code}-{code.upper()}')


def get_tmdb_api_language() -> str:
    return get_tmdb_api_language_for(get_tmdb_active_language())


def get_tmdb_language_display_code() -> str:
    return get_tmdb_active_language().upper()


def get_tmdb_language_menu_label() -> str:
    return f'TMDB jazyk hledání: {get_tmdb_language_display_code()}'


def is_tmdb_language_row_enabled() -> bool:
    return addon.getSetting(_SETTING_SHOW_ROW) != 'false'
