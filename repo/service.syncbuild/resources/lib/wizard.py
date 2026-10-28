import xbmcgui

from resources.lib.dropbox_api import (
    addon,
    app_credentials,
    authorize,
    authorized,
    set_setting,
    set_wizard_status,
    setting,
    setting_bool,
    setting_int,
    wizard_status,
)
from resources.lib.history import clamp_keep, clean_profile
from resources.lib.qrview import CONSOLE_URL, show_qr

WELCOME = (
    "SyncBuild keeps a few snapshots of this build in Dropbox and can reset "
    "this device from another device on the same profile."
)
APP_HELP = (
    "Create a scoped app with access to the whole Dropbox.\n\n"
    "On the Permissions tab, enable:\n"
    "files.metadata.read\n"
    "files.content.read\n"
    "files.content.write\n\n"
    "%s" % CONSOLE_URL
)


def offer_wizard():
    if wizard_status() in ("skipped", "completed"):
        return False
    key, secret = app_credentials()
    if key and secret and authorized():
        return False
    return run_wizard()


def run_wizard():
    if not xbmcgui.Dialog().yesno("SyncBuild", WELCOME, nolabel="Skip", yeslabel="Continue"):
        set_wizard_status("skipped")
        return False
    if not _credentials():
        return False
    _sign_in()
    _device_name()
    _profile()
    _history()
    _recheck()
    set_wizard_status("completed")
    return _finish()


def _stop_setup():
    return xbmcgui.Dialog().yesno(
        "SyncBuild",
        "Stop setup?",
        nolabel="Try again",
        yeslabel="Stop",
    )


def _credentials():
    show_qr(CONSOLE_URL, APP_HELP)
    current = addon()
    key = ""
    secret = ""
    while not key:
        key = (xbmcgui.Dialog().input("Dropbox app key", defaultt=current.getSetting("dropbox_key")) or "").strip()
        if not key and _stop_setup():
            return False
    hide = getattr(xbmcgui, "ALPHANUM_HIDE_INPUT", 0)
    while not secret:
        secret = (xbmcgui.Dialog().input(
            "Dropbox app secret",
            defaultt=current.getSetting("dropbox_secret"),
            option=hide,
        ) or "").strip()
        if not secret and _stop_setup():
            return False
    set_setting("dropbox_key", key)
    set_setting("dropbox_secret", secret)
    return True


def _sign_in():
    while not authorize():
        if not xbmcgui.Dialog().yesno(
            "SyncBuild",
            "Dropbox is not signed in yet.",
            nolabel="Continue",
            yeslabel="Try again",
        ):
            return


def _device_name():
    xbmcgui.Dialog().ok(
        "SyncBuild",
        "Other devices show this name when a newer build is found. For example PC, TV, or Phone.",
    )
    name = (xbmcgui.Dialog().input("Device name", defaultt=setting("device_name") or "PC") or "").strip()
    set_setting("device_name", name or "PC")


def _profile():
    xbmcgui.Dialog().ok(
        "SyncBuild",
        "Devices share builds only when they use the same profile name.",
    )
    while True:
        raw = xbmcgui.Dialog().input("Profile", defaultt=setting("profile") or "default")
        try:
            profile = clean_profile(raw)
        except ValueError as exc:
            xbmcgui.Dialog().ok("SyncBuild", str(exc))
            continue
        set_setting("profile", profile)
        return


def _history():
    xbmcgui.Dialog().ok(
        "SyncBuild",
        "This is how many unmarked builds each device keeps for one skin. Builds marked with * stay as well and do not count toward this number.",
    )
    entered = xbmcgui.Dialog().input(
        "Snapshots to keep",
        defaultt=str(setting_int("history", 3)),
        type=xbmcgui.INPUT_NUMERIC,
    )
    set_setting("history", str(clamp_keep(entered)))


def _recheck():
    default_yes = setting_bool("auto_check", True)
    kwargs = {}
    yes_button = getattr(xbmcgui, "DLG_YESNO_YES_BTN", None)
    no_button = getattr(xbmcgui, "DLG_YESNO_NO_BTN", None)
    if yes_button is not None and no_button is not None:
        kwargs["defaultbutton"] = yes_button if default_yes else no_button
    enabled = xbmcgui.Dialog().yesno(
        "SyncBuild",
        "Check for a newer build when Kodi starts?",
        nolabel="No",
        yeslabel="Yes",
        **kwargs
    )
    set_setting("auto_check", "true" if enabled else "false")


def _finish():
    if not authorized():
        xbmcgui.Dialog().ok("SyncBuild", "Sign-in can be finished from Authorize Dropbox.")
        return False
    choice = xbmcgui.Dialog().select("SyncBuild", [
        "Upload this build",
        "Check for a newer build",
        "Done",
    ])
    if choice == 0:
        from resources.lib.sync import upload_current
        upload_current()
    elif choice == 1:
        from resources.lib.sync import check_newer
        check_newer(interactive=True, automatic=False)
        return True
    return False
