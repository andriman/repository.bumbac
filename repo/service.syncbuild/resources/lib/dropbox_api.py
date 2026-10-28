import datetime
import json
import os
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

TOKEN_FILE = "tokens.json"
STATE_FILE = "state.json"
SCOPES = (
    "files.metadata.read",
    "files.content.read",
    "files.content.write",
)
SCOPE_HELP = (
    "Dropbox refused this login because the app is missing file permissions.\n\n"
    "Open the app in the Dropbox console, choose Permissions, enable these, then choose Authorize Dropbox again:\n\n"
    "files.metadata.read\n"
    "files.content.read\n"
    "files.content.write"
)
PERMISSIONS_READY = (
    "Before continuing, open this app in the Dropbox console and enable these on the Permissions tab:\n\n"
    "files.metadata.read\n"
    "files.content.read\n"
    "files.content.write\n\n"
    "Press OK when they are enabled. The next screen is the Dropbox address."
)


def addon():
    return xbmcaddon.Addon()


def log(message):
    xbmc.log("[SyncBuild] %s" % message, xbmc.LOGINFO)


def notify(message, error=False):
    icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification("SyncBuild", message, icon, 6000)


def failure_text(exc, fallback):
    text = getattr(exc, "message", None) or str(exc)
    lowered = text.lower()
    if "scope" in lowered or "not permitted" in lowered:
        return SCOPE_HELP
    if isinstance(exc, ValueError) and str(exc):
        return str(exc)
    detail = getattr(exc, "message", None)
    if detail:
        return detail
    return fallback


def show_failure(message):
    if "\n" in message:
        xbmcgui.Dialog().ok("SyncBuild", message)
    else:
        notify(message, error=True)


def data_dir():
    path = xbmcvfs.translatePath(addon().getAddonInfo("profile"))
    os.makedirs(path, exist_ok=True)
    return path


def translated(special):
    return xbmcvfs.translatePath(special).rstrip("\\/")


def setting(key):
    return addon().getSetting(key).strip()


def setting_bool(key, default=True):
    current = addon()
    getter = getattr(current, "getSettingBool", None)
    if getter is not None:
        try:
            return bool(getter(key))
        except Exception:
            pass
    value = current.getSetting(key).strip().lower()
    if value == "":
        return default
    return value == "true"


def setting_int(key, default):
    current = addon()
    getter = getattr(current, "getSettingInt", None)
    if getter is not None:
        try:
            return int(getter(key))
        except Exception:
            pass
    value = current.getSetting(key).strip()
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def device_name():
    return setting("device_name") or "This device"


def profile_name():
    from resources.lib.history import clean_profile
    return clean_profile(setting("profile"))


def _state_path():
    return os.path.join(data_dir(), STATE_FILE)


def load_state():
    path = _state_path()
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def save_state(state):
    with open(_state_path(), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def device_id():
    state = load_state()
    current = state.get("device_id")
    if not current:
        import uuid
        current = str(uuid.uuid4())
        state["device_id"] = current
        save_state(state)
    return current


def last_marker():
    return load_state().get("last_marker") or ""


def set_last_marker(snapshot_id):
    state = load_state()
    state["last_marker"] = snapshot_id
    if not state.get("device_id"):
        state["device_id"] = device_id()
    save_state(state)


def wizard_status():
    return load_state().get("wizard") or ""


def set_wizard_status(status):
    state = load_state()
    state["wizard"] = status
    save_state(state)


def set_setting(key, value):
    addon().setSetting(key, value)


def _token_path():
    return os.path.join(data_dir(), TOKEN_FILE)


def _parse_expiration(value):
    if not value:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            parts = time.strptime(value, pattern)
            return datetime.datetime(*parts[:6])
        except ValueError:
            continue
    return None


def _format_expiration(value):
    if not value:
        return ""
    if getattr(value, "tzinfo", None) is not None:
        value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def load_token():
    path = _token_path()
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def save_token(access_token, refresh_token, expiration):
    payload = {
        "access_token": access_token or "",
        "refresh_token": refresh_token or "",
        "expiration": _format_expiration(expiration),
    }
    with open(_token_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return payload


def delete_token():
    path = _token_path()
    if os.path.isfile(path):
        os.remove(path)


def authorized():
    token = load_token()
    return bool(token.get("access_token") or token.get("refresh_token"))


def app_credentials():
    key = setting("dropbox_key")
    secret = setting("dropbox_secret")
    if not key or not secret:
        return None, None
    return key, secret


def _sdk():
    from dropbox import Dropbox, DropboxOAuth2FlowNoRedirect
    from dropbox.exceptions import ApiError, AuthError
    from dropbox.files import FolderMetadata, WriteMode
    return Dropbox, DropboxOAuth2FlowNoRedirect, ApiError, AuthError, FolderMetadata, WriteMode


def _remember_refresh(client, token):
    access = getattr(client, "_oauth2_access_token", None)
    expiration = getattr(client, "_oauth2_access_token_expiration", None)
    if access and access != token.get("access_token"):
        save_token(access, token.get("refresh_token"), expiration)


def get_client():
    key, secret = app_credentials()
    token = load_token()
    if not key or not secret or not (token.get("access_token") or token.get("refresh_token")):
        return None
    Dropbox, _, ApiError, AuthError, _, _ = _sdk()
    client = Dropbox(
        oauth2_access_token=token.get("access_token") or None,
        oauth2_refresh_token=token.get("refresh_token") or None,
        oauth2_access_token_expiration=_parse_expiration(token.get("expiration")),
        app_key=key,
        app_secret=secret,
    )
    try:
        from resources.lib.history import ROOT
        client.files_list_folder(ROOT)
    except ApiError as exc:
        if "not_found" not in str(exc):
            log("Dropbox rejected the saved login: %s" % exc)
            return None
    except AuthError as exc:
        log("Dropbox login expired: %s" % exc)
        delete_token()
        return None
    except Exception as exc:
        log("Could not reach Dropbox: %s" % exc)
        raise
    _remember_refresh(client, token)
    return client


def authorize():
    key, secret = app_credentials()
    if not key or not secret:
        xbmcgui.Dialog().ok(
            "SyncBuild",
            "Add the Dropbox app key and secret in SyncBuild settings.\n\n"
            "On the app Permissions tab, enable files.metadata.read, files.content.read, and files.content.write.",
        )
        return False
    if authorized():
        if not xbmcgui.Dialog().yesno("SyncBuild", "Replace the saved Dropbox login?"):
            return False
        delete_token()
    xbmcgui.Dialog().ok("SyncBuild", PERMISSIONS_READY)
    _, Flow, _, _, _, _ = _sdk()
    flow = Flow(
        consumer_key=key,
        consumer_secret=secret,
        token_access_type="offline",
        scope=list(SCOPES),
    )
    url = flow.start()
    log("Authorize URL: %s" % url)
    from resources.lib.qrview import show_qr
    show_qr(
        url,
        "Open this address, allow SyncBuild, then press OK and paste the code.\n\n%s" % url,
    )
    code = xbmcgui.Dialog().input("Paste the Dropbox code")
    code = (code or "").strip()
    if not code:
        return False
    try:
        granted = flow.finish(code)
    except Exception as exc:
        log("Authorize failed: %s" % exc)
        notify("Dropbox did not accept that code", error=True)
        return False
    save_token(granted.access_token, granted.refresh_token, granted.expires_at)
    try:
        client = get_client()
    except Exception as exc:
        log("Saved login could not be used: %s" % exc)
        show_failure(failure_text(exc, "Dropbox did not accept the saved login"))
        return False
    if client is None:
        notify("Dropbox login could not be verified", error=True)
        return False
    notify("Dropbox authorized")
    return True


def _not_found(exc):
    return "not_found" in str(exc)


def list_folder(client, path):
    _, _, ApiError, _, _, _ = _sdk()
    try:
        result = client.files_list_folder(path)
    except ApiError as exc:
        if _not_found(exc):
            return []
        raise
    entries = list(result.entries)
    while result.has_more:
        result = client.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)
    return entries


def _folder_names(client, path):
    _, _, _, _, FolderMetadata, _ = _sdk()
    names = []
    for entry in list_folder(client, path):
        if isinstance(entry, FolderMetadata):
            names.append(entry.name)
    return names


def list_profile_devices(client, profile):
    from resources.lib.history import DEFAULT_PROFILE, ROOT, clean_profile, profile_device_entries
    profile = clean_profile(profile)
    profile_folders = _folder_names(client, "%s/%s" % (ROOT, profile))
    root_folders = _folder_names(client, ROOT) if profile == DEFAULT_PROFILE else []
    return profile_device_entries(profile, profile_folders, root_folders)


def list_profile_names(client):
    from resources.lib.history import ROOT, classify_root_folders
    return classify_root_folders(_folder_names(client, ROOT))


def download_bytes(client, path):
    _metadata, response = client.files_download(path)
    try:
        return response.content
    finally:
        response.close()


def upload_bytes(client, path, payload):
    _, _, _, _, _, WriteMode = _sdk()
    client.files_upload(payload, path, mode=WriteMode.overwrite, mute=True)


def delete_path(client, path):
    _, _, ApiError, _, _, _ = _sdk()
    try:
        client.files_delete_v2(path)
    except ApiError as exc:
        if not _not_found(exc):
            raise


def download_json(client, path):
    return json.loads(download_bytes(client, path).decode("utf-8"))


def upload_json(client, path, payload):
    upload_bytes(client, path, json.dumps(payload, indent=2).encode("utf-8"))
