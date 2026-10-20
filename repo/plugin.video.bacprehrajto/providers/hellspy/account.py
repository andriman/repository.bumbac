from common import addon
from model.AccountInfo import AccountInfo
from providers.hellspy.auth import account_nickname, fetch_identity, has_saved_session


def fetch_account_status(addon_ref=None) -> AccountInfo:
    """Logged in when a bearer token is still valid. Nickname comes from GET /identify."""
    del addon_ref
    identity = fetch_identity()
    if isinstance(identity, dict):
        token = identity.get('token') if isinstance(identity.get('token'), dict) else {}
        return AccountInfo(
            is_logged_in=True,
            account_name=account_nickname(identity),
            session_expires_date=str(token.get('expires') or ''),
        )
    if has_saved_session():
        return AccountInfo(is_logged_in=True)
    return AccountInfo(is_logged_in=False, account_name=(addon.getSetting('hellspy_email') or '').strip())
