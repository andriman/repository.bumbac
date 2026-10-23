import traceback

import xbmc

if __name__ == "__main__":
    monitor = xbmc.Monitor()
    ready = False
    for _ in range(30):
        if monitor.abortRequested():
            break
        if xbmc.getCondVisibility("Window.IsVisible(home)"):
            ready = True
            break
        if monitor.waitForAbort(1):
            break
    else:
        ready = not monitor.abortRequested()
    if ready:
        try:
            from resources.lib.sync import startup_check
            startup_check(monitor)
        except Exception:
            xbmc.log("[SyncBuild] startup failed:\n%s" % traceback.format_exc(), xbmc.LOGERROR)
