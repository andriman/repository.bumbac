import xbmc
import xbmcgui
import xbmcplugin
from typing import Dict, Optional

from common import _ADDON_NAME, addon, icons_path, go_to_main_menu, is_prehrajto_account_listing_enabled, \
    is_prehrajto_account_name_visible, is_sledujteto_account_name_visible, is_sledujteto_my_videos_enabled, \
    is_hellspy_account_name_visible, is_hellspy_my_videos_enabled, \
    is_sledujteto_watchlist_enabled, ICON_REFRESH, g_truncate_titles, set_list_icon
from providers.hellspy.account import fetch_account_status as fetch_hellspy_status
from providers.hellspy.account_videos import fetch_my_videos as fetch_hellspy_my_videos, set_video_public
from providers.hellspy.auth import hellspy_login, hellspy_logout
from providers.prehrajto.account import fetch_account_status as fetch_prehrajto_status
from providers.prehrajto.account_listings import (
    LISTING_FAVORITES,
    LISTING_LIKED,
    LISTING_PLAYED,
    LISTING_UPLOADED,
    LISTING_LABELS,
    fetch_listing_page,
)
from providers.prehrajto.auth import ensure_session_for_search, prehrajto_login, prehrajto_logout
from providers.prehrajto.list_items import build_prehrajto_list_item
from providers.sledujteto.account import fetch_account_status as fetch_sledujteto_status
from providers.sledujteto.account_listings import fetch_my_videos, fetch_watchlist
from providers.sledujteto.auth import sledujteto_login, sledujteto_logout
from utils.StrUtils import truncate_middle
from utils.listitem_infotag import apply_art, apply_deferred_listing_stream_info, attach_listing_stream_info_property
from utils.stream_fake_hint import LISTING_THUMB_PROP
from utils.utils import dprint, get_url, apply_context_menu_items, build_video_context_menu_items

PROVIDER_PREHRAJTO = 'prehrajto'
PROVIDER_SLEDUJTETO = 'sledujteto'
PROVIDER_HELLSPY = 'hellspy'

COLOR_GREEN = 'FF46D369'
COLOR_RED = 'FFFF4444'

_PROVIDER_LABELS = {
    PROVIDER_PREHRAJTO: 'Prehraj.to',
    PROVIDER_SLEDUJTETO: 'Sledujteto.cz',
    PROVIDER_HELLSPY: 'HellSpy',
}

_PROVIDER_ICONS = {
    PROVIDER_PREHRAJTO: icons_path + 'prehrajto.png',
    PROVIDER_SLEDUJTETO: icons_path + 'sledujteto.jpg',
    PROVIDER_HELLSPY: icons_path + 'hellspy.png',
}

_PROVIDER_EMAIL_SETTINGS = {
    PROVIDER_PREHRAJTO: 'email',
    PROVIDER_SLEDUJTETO: 'sledujteto_email',
    PROVIDER_HELLSPY: 'hellspy_email',
}

_PREHRAJTO_ACCOUNT_LISTINGS = (
    (LISTING_PLAYED, LISTING_LABELS[LISTING_PLAYED]),
    (LISTING_LIKED, LISTING_LABELS[LISTING_LIKED]),
    (LISTING_UPLOADED, LISTING_LABELS[LISTING_UPLOADED]),
    (LISTING_FAVORITES, LISTING_LABELS[LISTING_FAVORITES]),
)

_LOGGED_IN_LABEL = {'cs': 'Přihlášen', 'en': 'Logged In'}
_LOG_IN_LABEL = {'cs': 'Přihlásit se', 'en': 'Log in'}
_NOT_LOGGED_IN_LABEL = {'cs': 'Nepřihlášen', 'en': 'Not logged in'}
_PREMIUM_NOT_ACTIVE = {'cs': 'Neaktivní', 'en': 'Not active'}
_PREMIUM_UNKNOWN = {'cs': 'neznámý', 'en': 'unknown'}

_LOGIN_STATUS_VALUES = frozenset({
    'logged in',
    'přihlášen',
    'prihlasen',
})


def _account_lang() -> str:
    try:
        if xbmc.getLanguage(formatt='iso639_1').lower().startswith('en'):
            return 'en'
    except Exception:
        pass
    return 'cs'


def _t(labels: Dict[str, str]) -> str:
    return labels.get(_account_lang(), labels['cs'])


def _localize_premium_value(value: str) -> str:
    text = (value or '').strip()
    if not text:
        return _t(_PREMIUM_NOT_ACTIVE)
    if text.lower() in _LOGIN_STATUS_VALUES:
        return _t(_PREMIUM_NOT_ACTIVE)
    return text


def _inactive_premium_display(info) -> str:
    return _t(_PREMIUM_NOT_ACTIVE)


def _premium_label(info) -> str:
    if info.is_premium:
        premium = (info.expiration or _t(_PREMIUM_UNKNOWN)).strip()
        return f'Premium: [COLOR {COLOR_GREEN}]{_localize_premium_value(premium)}[/COLOR]'
    return f'Premium: {_inactive_premium_display(info)}'


def _logged_in_root_label(provider: str, info) -> str:
    label = _PROVIDER_LABELS[_normalize_provider(provider)]
    return (
        f'{label}: [COLOR {COLOR_GREEN}]{_t(_LOGGED_IN_LABEL)}[/COLOR] | '
        + _premium_label(info)
    )


def _normalize_provider(provider: str) -> str:
    if provider == PROVIDER_SLEDUJTETO:
        return PROVIDER_SLEDUJTETO
    if provider == PROVIDER_HELLSPY:
        return PROVIDER_HELLSPY
    return PROVIDER_PREHRAJTO


def _fetch_status(provider: str):
    if provider == PROVIDER_SLEDUJTETO:
        return fetch_sledujteto_status(addon)
    if provider == PROVIDER_HELLSPY:
        return fetch_hellspy_status(addon)
    return fetch_prehrajto_status(addon, fetch_profile=True)


def get_account_root_label(provider: str) -> str:
    provider = _normalize_provider(provider)
    label = _PROVIDER_LABELS[provider]
    info = _fetch_status(provider)
    if not info.is_logged_in:
        return f'{label}: {_t(_LOG_IN_LABEL)}'
    if provider == PROVIDER_HELLSPY:
        if is_hellspy_account_name_visible() and info.account_name:
            return (
                f'{label}: [COLOR {COLOR_GREEN}]{_t(_LOGGED_IN_LABEL)}[/COLOR] | '
                f'{info.account_name}'
            )
        return f'{label}: [COLOR {COLOR_GREEN}]{_t(_LOGGED_IN_LABEL)}[/COLOR]'
    return _logged_in_root_label(provider, info)


def _add_info_item(_handle, label: str) -> None:
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'false')
    xbmcplugin.addDirectoryItem(_handle, '', item, False)


def _status_label(info, provider: str) -> str:
    if info.is_logged_in:
        if provider == PROVIDER_HELLSPY:
            return f'Status: [COLOR {COLOR_GREEN}]{_t(_LOGGED_IN_LABEL)}[/COLOR]'
        return (
            f'Status: [COLOR {COLOR_GREEN}]{_t(_LOGGED_IN_LABEL)}[/COLOR] | '
            + _premium_label(info)
        )
    return f'Status: [COLOR {COLOR_RED}]{_t(_NOT_LOGGED_IN_LABEL)}[/COLOR]'


def _session_expires_label(info) -> str:
    if info.session_expires_date and info.session_expires_days:
        return f'Session expires: {info.session_expires_date} ({info.session_expires_days})'
    if info.session_expires_date:
        return f'Session expires: {info.session_expires_date}'
    return 'Session expires: unknown'


def _count_label(base: str, count: Optional[int]) -> str:
    if count is None:
        return base
    return f'{base} ({count})'


def show_account_menu(_handle, _url: str, provider: str) -> None:
    provider = _normalize_provider(provider)
    info = _fetch_status(provider)
    icon = _PROVIDER_ICONS[provider]

    _add_info_item(_handle, _status_label(info, provider))

    if info.is_logged_in:
        if provider == PROVIDER_HELLSPY and is_hellspy_my_videos_enabled():
            my_videos_item = xbmcgui.ListItem(
                label=_count_label('Moje videa', _hellspy_video_count()))
            my_videos_item.setProperty('IsPlayable', 'false')
            my_videos_item.setArt({'icon': icon})
            xbmcplugin.addDirectoryItem(
                _handle,
                get_url(_url, action='account_my_videos', provider=provider),
                my_videos_item,
                True,
            )
        elif provider == PROVIDER_PREHRAJTO:
            for kind, label in _PREHRAJTO_ACCOUNT_LISTINGS:
                if not is_prehrajto_account_listing_enabled(kind):
                    continue
                folder_item = xbmcgui.ListItem(label=label)
                folder_item.setProperty('IsPlayable', 'false')
                folder_item.setArt({'icon': icon})
                xbmcplugin.addDirectoryItem(
                    _handle,
                    get_url(_url, action='account_listing', listing=kind, provider=provider),
                    folder_item,
                    True,
                )

        if provider == PROVIDER_PREHRAJTO:
            _add_info_item(_handle, _session_expires_label(info))
            if info.recurring_payment:
                _add_info_item(_handle, f'Opakovaná platba: {info.recurring_payment}')
            if info.next_payment:
                _add_info_item(_handle, f'Další platba: {info.next_payment}')
        elif provider == PROVIDER_SLEDUJTETO:
            _add_info_item(_handle, _premium_label(info))

        if (provider == PROVIDER_PREHRAJTO and is_prehrajto_account_name_visible()) or (
                provider == PROVIDER_SLEDUJTETO and is_sledujteto_account_name_visible()) or (
                provider == PROVIDER_HELLSPY and is_hellspy_account_name_visible()):
            _add_info_item(_handle, f'Účet: {info.account_name}')

        if provider == PROVIDER_SLEDUJTETO:
            if is_sledujteto_my_videos_enabled():
                my_videos_item = xbmcgui.ListItem(
                    label=_count_label('Moje videa', info.my_videos_count))
                my_videos_item.setProperty('IsPlayable', 'false')
                my_videos_item.setArt({'icon': icon})
                xbmcplugin.addDirectoryItem(
                    _handle,
                    get_url(_url, action='account_my_videos', provider=provider),
                    my_videos_item,
                    True,
                )

            if is_sledujteto_watchlist_enabled():
                watchlist_item = xbmcgui.ListItem(
                    label=_count_label('Přehrát později', info.watchlist_count))
                watchlist_item.setProperty('IsPlayable', 'false')
                watchlist_item.setArt({'icon': icon})
                xbmcplugin.addDirectoryItem(
                    _handle,
                    get_url(_url, action='account_watchlist', provider=provider),
                    watchlist_item,
                    True,
                )

        logout_item = xbmcgui.ListItem(label='Odhlásit se')
        logout_item.setProperty('IsPlayable', 'false')
        logout_item.setArt({'icon': icon})
        xbmcplugin.addDirectoryItem(
            _handle, get_url(_url, action='account_logout', provider=provider), logout_item, False)
    else:
        login_item = xbmcgui.ListItem(label='Přihlásit se')
        login_item.setProperty('IsPlayable', 'false')
        login_item.setArt({'icon': icon})
        xbmcplugin.addDirectoryItem(
            _handle, get_url(_url, action='account_login', provider=provider), login_item, False)

    xbmcplugin.endOfDirectory(_handle)


def handle_login(_handle, _url: str, provider: str) -> None:
    provider = _normalize_provider(provider)
    email_setting = _PROVIDER_EMAIL_SETTINGS[provider]
    email = addon.getSetting(email_setting)
    if not email:
        xbmcgui.Dialog().ok(
            _ADDON_NAME,
            'Vyplňte přihlašovací údaje v nastavení doplňku (Accounts).')
        addon.openSettings()
        show_account_menu(_handle, _url, provider)
        return

    if provider == PROVIDER_SLEDUJTETO:
        success, _ = sledujteto_login(addon, notify=True)
    elif provider == PROVIDER_HELLSPY:
        success = hellspy_login(addon, notify=True)
    else:
        _, cookies = prehrajto_login(addon, notify=True)
        success = cookies is not None

    if success:
        go_to_main_menu()
    else:
        show_account_menu(_handle, _url, provider)


def handle_logout(_handle, _url: str, provider: str) -> None:
    provider = _normalize_provider(provider)
    if provider == PROVIDER_SLEDUJTETO:
        sledujteto_logout()
    elif provider == PROVIDER_HELLSPY:
        hellspy_logout()
    else:
        prehrajto_logout()
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Odhlášeno',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    go_to_main_menu()


def _hellspy_video_count() -> Optional[int]:
    try:
        return len(fetch_hellspy_my_videos())
    except Exception as exc:
        dprint(f'hellspy my videos count: {exc}')
        return None


def _hellspy_visibility_url(_url: str, video_id: str, make_public: bool, ask: bool = False) -> str:
    return get_url(
        _url,
        action='account_hellspy_visibility',
        provider=PROVIDER_HELLSPY,
        video_id=video_id,
        public='true' if make_public else 'false',
        ask='1' if ask else '0',
    )


def _render_hellspy_my_videos(_handle, _url: str, videos) -> None:
    try:
        xbmcplugin.setContent(_handle, 'videos')
        xbmcplugin.setPluginCategory(_handle, 'Moje videa')
    except (AttributeError, RuntimeError, TypeError):
        pass
    if not videos:
        _add_info_item(_handle, 'Nebyla nalezena žádná videa')
    icon = _PROVIDER_ICONS[PROVIDER_HELLSPY]
    for entry in (videos or []):
        if not isinstance(entry, dict):
            continue
        title = (entry.get('title') or '').strip()
        video_id = (entry.get('id') or '').strip()
        page_url = (entry.get('page_url') or '').strip()
        if not title or not video_id or not page_url:
            continue
        if g_truncate_titles:
            title = truncate_middle(title)
        is_public = bool(entry.get('public'))
        if not is_public:
            title = f'[P] {title}'
        size_label = (entry.get('size_label') or '').strip()
        if size_label:
            title = f'{title} | {size_label}'
        list_item = xbmcgui.ListItem(
            label=title,
            label2=(entry.get('duration_label') or '').strip(),
            path=page_url,
            offscreen=True,
        )
        list_item.setProperty('IsPlayable', 'false')
        stream_info = {'mediatype': 'video'}
        if entry.get('duration_seconds'):
            stream_info['duration'] = entry['duration_seconds']
        if entry.get('size_bytes'):
            stream_info['size'] = entry['size_bytes']
        attach_listing_stream_info_property(list_item, stream_info)
        apply_deferred_listing_stream_info(list_item)
        thumb = (entry.get('thumb') or '').strip()
        art = {'icon': icon}
        if thumb:
            art['thumb'] = thumb
            art['poster'] = thumb
        apply_art(list_item, art)
        if is_public:
            menu = build_video_context_menu_items(_url, page_url)
            menu.append((
                'Nastavit jako soukromé',
                'RunPlugin({})'.format(_hellspy_visibility_url(_url, video_id, False)),
            ))
            apply_context_menu_items(list_item, menu)
            item_url = get_url(_url, action='resume_or_play', link=page_url)
        else:
            apply_context_menu_items(list_item, [(
                'Zveřejnit',
                'RunPlugin({})'.format(_hellspy_visibility_url(_url, video_id, True)),
            )])
            item_url = get_url(_url, action='resume_or_play', link=page_url, publish='1')
        xbmcplugin.addDirectoryItem(_handle, item_url, list_item, False)
    xbmcplugin.endOfDirectory(_handle)


def show_hellspy_my_videos(_handle, _url: str) -> None:
    if not is_hellspy_my_videos_enabled():
        show_account_menu(_handle, _url, PROVIDER_HELLSPY)
        return
    info = fetch_hellspy_status(addon)
    if not info.is_logged_in:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Pro Moje videa se musíte přihlásit',
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_HELLSPY)
        return
    try:
        videos = fetch_hellspy_my_videos()
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, str(exc),
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_HELLSPY)
        return
    _render_hellspy_my_videos(_handle, _url, videos)


def handle_hellspy_visibility(_handle, _url: str, video_id: str, make_public: bool, ask: bool) -> None:
    if ask and make_public:
        if not xbmcgui.Dialog().yesno(
                _ADDON_NAME,
                'Video není veřejné. Bez zveřejnění ho nelze přehrát. Zveřejnit?',
                nolabel='Ne',
                yeslabel='Ano',
        ):
            list_url = get_url(_url, action='account_my_videos', provider=PROVIDER_HELLSPY)
            xbmc.executebuiltin('Container.Update("%s")' % list_url)
            xbmcplugin.endOfDirectory(_handle, succeeded=False)
            return
    try:
        changed = set_video_public(video_id, make_public)
    except Exception as exc:
        dprint(f'hellspy visibility: {exc}')
        changed = False
    if changed:
        message = 'Video je veřejné' if make_public else 'Video je soukromé'
        xbmcgui.Dialog().notification(
            _ADDON_NAME, message,
            xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
        list_url = get_url(_url, action='account_my_videos', provider=PROVIDER_HELLSPY)
        xbmc.executebuiltin('Container.Update("%s")' % list_url)
    else:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Změna se nezdařila',
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
    xbmcplugin.endOfDirectory(_handle, succeeded=False)


def _render_sledujteto_videos(_handle, _url: str, videos) -> None:
    try:
        xbmcplugin.setContent(_handle, 'videos')
    except (AttributeError, RuntimeError, TypeError):
        pass
    if not videos:
        _add_info_item(_handle, 'Nebyla nalezena žádná videa')
    for list_item in (videos or []):
        if not list_item:
            continue
        list_item.setProperty('IsPlayable', 'false')
        try:
            thumb = (list_item.getArt('thumb') or '').strip()
            poster = (list_item.getArt('poster') or '').strip()
        except (AttributeError, RuntimeError, TypeError):
            thumb, poster = '', ''
        if thumb and not poster:
            apply_art(list_item, {'poster': thumb})
        vid_url = list_item.getPath()
        if not vid_url:
            continue
        apply_context_menu_items(list_item, build_video_context_menu_items(_url, vid_url))
        play_url = get_url(_url, action='resume_or_play', link=vid_url)
        xbmcplugin.addDirectoryItem(_handle, play_url, list_item, False)
    xbmcplugin.endOfDirectory(_handle)


def show_sledujteto_my_videos(_handle, _url: str) -> None:
    if not is_sledujteto_my_videos_enabled():
        show_account_menu(_handle, _url, PROVIDER_SLEDUJTETO)
        return
    info = fetch_sledujteto_status(addon)
    if not info.is_logged_in:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Pro Moje videa se musíte přihlásit',
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_SLEDUJTETO)
        return
    try:
        videos = fetch_my_videos()
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, str(exc),
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_SLEDUJTETO)
        return
    _render_sledujteto_videos(_handle, _url, videos)


def show_sledujteto_watchlist(_handle, _url: str) -> None:
    if not is_sledujteto_watchlist_enabled():
        show_account_menu(_handle, _url, PROVIDER_SLEDUJTETO)
        return
    info = fetch_sledujteto_status(addon)
    if not info.is_logged_in:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Pro Přehrát později se musíte přihlásit',
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_SLEDUJTETO)
        return
    try:
        videos = fetch_watchlist()
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, str(exc),
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_SLEDUJTETO)
        return
    _render_sledujteto_videos(_handle, _url, videos)


def _apply_prehrajto_listing_metadata(list_item: xbmcgui.ListItem) -> None:
    if not list_item:
        return
    existing_thumb = ''
    try:
        existing_thumb = (list_item.getArt('thumb') or '').strip()
    except (AttributeError, RuntimeError, TypeError):
        existing_thumb = ''
    if not existing_thumb:
        art = {'icon': icons_path + 'prehrajto.png'}
        thumb = (list_item.getProperty(LISTING_THUMB_PROP) or '').strip()
        if thumb:
            art['thumb'] = thumb
            art['poster'] = thumb
        apply_art(list_item, art)
    else:
        try:
            if not (list_item.getArt('poster') or '').strip():
                apply_art(list_item, {'poster': existing_thumb})
        except (AttributeError, RuntimeError, TypeError):
            pass
    apply_deferred_listing_stream_info(list_item)


def _render_prehrajto_account_listing(
        _handle, _url: str, listing_kind: str, page_url: Optional[str] = None,
) -> None:
    if not is_prehrajto_account_listing_enabled(listing_kind):
        show_account_menu(_handle, _url, PROVIDER_PREHRAJTO)
        return

    info = fetch_prehrajto_status(addon)
    if not info.is_logged_in:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Pro tento seznam se musíte přihlásit',
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_PREHRAJTO)
        return

    ensure_session_for_search(addon)

    label = LISTING_LABELS.get(listing_kind, 'Videa')
    p_dialog = xbmcgui.DialogProgress()
    p_dialog.create(_ADDON_NAME, label)
    try:
        listing_page = fetch_listing_page(
            listing_kind, page_url=page_url, progress=p_dialog,
        )
    except Exception as exc:
        p_dialog.close()
        xbmcgui.Dialog().notification(
            _ADDON_NAME, str(exc),
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        show_account_menu(_handle, _url, PROVIDER_PREHRAJTO)
        return
    finally:
        p_dialog.close()

    entries = listing_page.items
    next_page_url = listing_page.next_page_url

    try:
        xbmcplugin.setContent(_handle, 'videos')
        xbmcplugin.setPluginCategory(_handle, label)
    except (AttributeError, RuntimeError, TypeError):
        pass
    if not entries:
        _add_info_item(_handle, 'Nebyla nalezena žádná videa')
    for entry in (entries or []):
        if not isinstance(entry, dict):
            continue
        link = (entry.get('link') or '').strip()
        title = (entry.get('title') or '').strip()
        if not link or not title:
            continue
        list_item = build_prehrajto_list_item(
            title,
            entry.get('size', '') or '',
            entry.get('duration', '') or '',
            link,
            entry.get('thumb', '') or '',
        )
        _apply_prehrajto_listing_metadata(list_item)
        list_item.setProperty('IsPlayable', 'false')
        vid_url = list_item.getPath()
        if not vid_url:
            continue
        apply_context_menu_items(list_item, build_video_context_menu_items(_url, vid_url))
        play_url = get_url(_url, action='resume_or_play', link=vid_url)
        xbmcplugin.addDirectoryItem(_handle, play_url, list_item, False)

    if next_page_url:
        next_item = xbmcgui.ListItem(label='Další stránka')
        next_item.setProperty('IsPlayable', 'false')
        set_list_icon(next_item, ICON_REFRESH)
        next_folder_url = get_url(
            _url,
            action='account_listing',
            listing=listing_kind,
            provider=PROVIDER_PREHRAJTO,
            page_url=next_page_url,
        )
        xbmcplugin.addDirectoryItem(_handle, next_folder_url, next_item, True)

    xbmcplugin.endOfDirectory(_handle)


def show_prehrajto_account_listing(
        _handle, _url: str, listing_kind: str, page_url: Optional[str] = None,
) -> None:
    _render_prehrajto_account_listing(_handle, _url, listing_kind, page_url=page_url)
