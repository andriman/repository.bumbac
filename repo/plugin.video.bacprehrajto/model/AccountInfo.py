from dataclasses import dataclass
from typing import Optional

@dataclass
class AccountInfo:
    is_logged_in: bool
    account_name: str = ''
    membership_status: str = ''
    expiration: str = ''
    expiration_date: str = ''
    expiration_days: str = ''
    recurring_payment: str = ''
    next_payment: str = ''
    is_premium: bool = False
    session_expires_date: str = ''
    session_expires_days: str = ''
    my_videos_count: Optional[int] = None
    watchlist_count: Optional[int] = None
