# -*- coding: utf-8 -*-
import os
import xbmcaddon
import xbmcgui
import xbmcvfs

from subtitle_cache import SubtitleCache
from utilities import log

_ADDON_ID = "service.subtitles.bb.edna.cz"
_ACTION_NAME = "titulky-link-action.txt"


def _profile(addon):
	return xbmcvfs.translatePath(addon.getAddonInfo("profile"))


def _action_path(addon):
	return os.path.join(_profile(addon), _ACTION_NAME)


def _current_action(addon):
	value = addon.getSetting("titulky_link_action")
	if value in ("0", "1", "2"):
		return value
	return "2"


def _read_action(addon):
	try:
		with open(_action_path(addon), "r", encoding="utf-8") as handle:
			return handle.read().strip()
	except OSError:
		return None


def _write_action(addon, value):
	profile = _profile(addon)
	os.makedirs(profile, exist_ok=True)
	with open(_action_path(addon), "w", encoding="utf-8") as handle:
		handle.write(value)


def clear_subtitle_cache(addon, notify=False):
	root = os.path.join(_profile(addon), "subtitle-cache")
	SubtitleCache(root, 1).clear_all()
	log(__name__, "Cleared subtitle cache")
	if notify:
		message = addon.getLocalizedString(32958) or "Cache cleared."
		xbmcgui.Dialog().notification(
			addon.getAddonInfo("name"),
			message,
			xbmcgui.NOTIFICATION_INFO,
			3000,
		)


def clear_if_titulky_action_changed(addon, notify=False):
	current = _current_action(addon)
	previous = _read_action(addon)
	if previous is None:
		_write_action(addon, current)
		return False
	if previous == current:
		return False
	log(__name__, "Titulky.com action changed from %s to %s" % (previous, current))
	clear_subtitle_cache(addon, notify=notify)
	_write_action(addon, current)
	return True


if __name__ == "__main__":
	clear_subtitle_cache(xbmcaddon.Addon(_ADDON_ID), notify=True)
