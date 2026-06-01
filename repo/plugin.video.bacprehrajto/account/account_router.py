from typing import Dict

from account.account_menu import (
    PROVIDER_PREHRAJTO,
    PROVIDER_SLEDUJTETO,
    handle_login,
    handle_logout,
    show_account_menu,
    show_sledujteto_my_videos,
    show_sledujteto_watchlist,
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
        show_sledujteto_my_videos(_handle, _url)
    elif action == 'account_watchlist' and provider == PROVIDER_SLEDUJTETO:
        show_sledujteto_watchlist(_handle, _url)
