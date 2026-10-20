# -*- coding: utf-8 -*-
import os
import sys
import xbmc
import xbmcaddon
import xbmcvfs

_addon = xbmcaddon.Addon()
sys.path.append(xbmcvfs.translatePath(os.path.join(_addon.getAddonInfo("path"), "resources", "lib")))

from cache_action import _current_action, _write_action, clear_subtitle_cache


class CacheMonitor(xbmc.Monitor):
	def __init__(self):
		self.addon_id = _addon.getAddonInfo("id")
		addon = xbmcaddon.Addon(self.addon_id)
		self.action = _current_action(addon)
		_write_action(addon, self.action)

	def onSettingsChanged(self):
		if self.waitForAbort(0.3):
			return
		addon = xbmcaddon.Addon(self.addon_id)
		current = _current_action(addon)
		if current == self.action:
			return
		self.action = current
		_write_action(addon, current)
		clear_subtitle_cache(addon, notify=True)


if __name__ == "__main__":
	monitor = CacheMonitor()
	while not monitor.abortRequested():
		if monitor.waitForAbort(3600):
			break
