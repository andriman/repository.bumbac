import xbmcgui
import xbmcplugin
from typing import Optional

from common import _ADDON_NAME, addon, icons_path, go_to_main_menu
from providers.prehrajto.account import fetch_account_status as fetch_prehrajto_status
from providers.prehrajto.auth import prehrajto_login, prehrajto_logout
from providers.sledujteto.account import fetch_account_status as fetch_sledujteto_status
from providers.sledujteto.account_listings import fetch_my_videos, fetch_watchlist
from providers.sledujteto.auth import sledujteto_login, sledujteto_logout
from utils.utils import get_url, apply_context_menu_items, build_video_context_menu_items

PROVIDER_PREHRAJTO = 'prehrajto'
PROVIDER_SLEDUJTETO = 'sledujteto'

COLOR_GREEN = 'FF46D369'
COLOR_RED = 'FFFF4444'

_PROVIDER_LABELS = {
    PROVIDER_PREHRAJTO: 'Prehraj.to',
    PROVIDER_SLEDUJTETO: 'Sledujteto.cz',
}

_PROVIDER_ICONS = {
    PROVIDER_PREHRAJTO: icons_path + 'prehrajto.png',
    PROVIDER_SLEDUJTETO: icons_path + 'sledujteto.jpg',
}

_PROVIDER_EMAIL_SETTINGS = {
    PROVIDER_PREHRAJTO: 'email',
    PROVIDER_SLEDUJTETO: 'sledujteto_email',
}


def _normalize_provider(provider: str) -> str:
    if provider == PROVIDER_SLEDUJTETO:
        return PROVIDER_SLEDUJTETO
    return PROVIDER_PREHRAJTO


def _fetch_status(provider: str):
    if provider == PROVIDER_SLEDUJTETO:
        return fetch_sledujteto_status(addon)
    return fetch_prehrajto_status(addon, fetch_profile=True)


def _premium_expiration_suffix(info) -> str:
    if info.expiration_date and info.expiration:
        return f' (Vyprší: {info.expiration_date} (za {info.expiration}))'
    if info.expiration_date:
        return f' (Vyprší: {info.expiration_date})'
    if info.expiration:
        return f' (Vyprší: za {info.expiration})'
    return ''


def _membership_status_text(info, provider: str) -> str:
    if provider == PROVIDER_SLEDUJTETO:
        return info.membership_status or 'Logged in'
    if info.membership_status:
        return info.membership_status
    if info.is_premium:
        return 'PREMIUM ČLEN'
    return 'Logged in'


def _sledujteto_premium_label(info) -> str:
    premium = (info.expiration or 'neznámý').strip()
    if info.is_premium:
        return f'Premium: [COLOR {COLOR_GREEN}]{premium}[/COLOR]'
    return f'Premium: [COLOR {COLOR_RED}]{premium}[/COLOR]'


def get_account_root_label(provider: str) -> str:
    provider = _normalize_provider(provider)
    label = _PROVIDER_LABELS[provider]
    info = _fetch_status(provider)
    if not info.is_logged_in:
        return f'{label}: Log in'
    if provider == PROVIDER_SLEDUJTETO:
        return (
            f'{label}: [COLOR {COLOR_GREEN}]Logged in[/COLOR] | '
            + _sledujteto_premium_label(info)
        )
    status = _membership_status_text(info, provider)
    colored = f'[COLOR {COLOR_GREEN}]{status}[/COLOR]'
    suffix = _premium_expiration_suffix(info)
    return f'{label}: {colored}{suffix}'


def _add_info_item(_handle, label: str) -> None:
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'false')
    xbmcplugin.addDirectoryItem(_handle, '', item, False)


def _status_label(info, provider: str) -> str:
    if info.is_logged_in:
        if provider == PROVIDER_SLEDUJTETO:
            return f'Status: [COLOR {COLOR_GREEN}]Logged in[/COLOR]'
        status = _membership_status_text(info, provider)
        suffix = _premium_expiration_suffix(info)
        return f'Status: [COLOR {COLOR_GREEN}]{status}[/COLOR]{suffix}'
    return f'Status: [COLOR {COLOR_RED}]Not logged in[/COLOR]'


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
        if provider == PROVIDER_PREHRAJTO:
            _add_info_item(_handle, _session_expires_label(info))
            if info.recurring_payment:
                _add_info_item(_handle, f'Opakovaná platba: {info.recurring_payment}')
            if info.next_payment:
                _add_info_item(_handle, f'Další platba: {info.next_payment}')
        elif provider == PROVIDER_SLEDUJTETO:
            _add_info_item(_handle, _sledujteto_premium_label(info))

        _add_info_item(_handle, f'Účet: {info.account_name}')

        if provider == PROVIDER_SLEDUJTETO:
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
    else:
        prehrajto_logout()
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Odhlášeno',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    go_to_main_menu()


def _render_sledujteto_videos(_handle, _url: str, videos) -> None:
    xbmcplugin.setContent(_handle, 'videos')
    if not videos:
        _add_info_item(_handle, 'Nebyla nalezena žádná videa')
    for list_item in videos:
        list_item.setProperty('IsPlayable', 'true')
        vid_url = list_item.getPath()
        apply_context_menu_items(list_item, build_video_context_menu_items(_url, vid_url))
        play_url = get_url(_url, action='play', link=vid_url)
        xbmcplugin.addDirectoryItem(_handle, play_url, list_item, False)
    xbmcplugin.endOfDirectory(_handle)


def show_sledujteto_my_videos(_handle, _url: str) -> None:
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
