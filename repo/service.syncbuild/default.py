import xbmcgui

from resources.lib.dropbox_api import authorize
from resources.lib.sync import browse_profiles, check_newer, manage_builds, upload_current
from resources.lib.wizard import run_wizard

ACTIONS = (
    "Upload current build",
    "Check for newer builds",
    "Saved builds",
    "Other profiles",
    "Setup wizard",
    "Authorize Dropbox",
)


def main():
    choice = xbmcgui.Dialog().select("SyncBuild", list(ACTIONS))
    if choice == 0:
        upload_current()
    elif choice == 1:
        check_newer(interactive=True, automatic=False)
    elif choice == 2:
        manage_builds()
    elif choice == 3:
        browse_profiles()
    elif choice == 4:
        run_wizard()
    elif choice == 5:
        authorize()


if __name__ == "__main__":
    main()
