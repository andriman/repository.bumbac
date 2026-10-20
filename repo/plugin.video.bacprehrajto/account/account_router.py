from typing import Dict

from common import (
    is_hellspy_my_videos_enabled,
    is_sledujteto_my_videos_enabled,
    is_sledujteto_watchlist_enabled,
)
from account.account_menu import (
    PROVIDER_HELLSPY,
    PROVIDER_PREHRAJTO,
    PROVIDER_SLEDUJTETO,
    handle_hellspy_visibility,
    handle_login,
    handle_logout,
    show_account_menu,
    show_hellspy_my_videos,
    show_sledujteto_my_videos,
    show_sledujteto_watchlist,
    show_prehrajto_account_listing,
)


def account_router(_handle: int, _url: str, params: Dict) -> None:
    action = params.get('action', '')
    provider = params.get('provider', PROVIDER_PREHRAJTO)
    if action == 'account_menu':
        show_account_menu(_handle, _url, provider)
    elif action == 'account_login':
        handle_login(_handle, _url, provider)
    elif action == 'account_logout':
        handle_logout(_handle, _url, provider)
    elif action == 'account_my_videos' and provider == PROVIDER_SLEDUJTETO:
        if is_sledujteto_my_videos_enabled():
            show_sledujteto_my_videos(_handle, _url)
        else:
            show_account_menu(_handle, _url, provider)
    elif action == 'account_my_videos' and provider == PROVIDER_HELLSPY:
        if is_hellspy_my_videos_enabled():
            show_hellspy_my_videos(_handle, _url)
        else:
            show_account_menu(_handle, _url, provider)
    elif action == 'account_hellspy_visibility' and provider == PROVIDER_HELLSPY:
        handle_hellspy_visibility(
            _handle,
            _url,
            params.get('video_id', ''),
            params.get('public') == 'true',
            params.get('ask') == '1',
        )
    elif action == 'account_watchlist' and provider == PROVIDER_SLEDUJTETO:
        if is_sledujteto_watchlist_enabled():
            show_sledujteto_watchlist(_handle, _url)
        else:
            show_account_menu(_handle, _url, provider)
    elif action == 'account_listing' and provider == PROVIDER_PREHRAJTO:
        listing = params.get('listing', '')
        if listing:
            page_url = params.get('page_url') or None
            show_prehrajto_account_listing(_handle, _url, listing, page_url=page_url)
