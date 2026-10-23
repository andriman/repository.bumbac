import xbmcgui

from resources.lib.dropbox_api import authorize
from resources.lib.sync import check_newer, manage_builds, upload_current

ACTIONS = (
    "Upload current build",
    "Check for newer builds",
    "Saved builds",
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
        authorize()


if __name__ == "__main__":
    main()
