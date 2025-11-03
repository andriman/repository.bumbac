import os

import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc
import xbmcvfs

_ADDON_ID = 'plugin.video.bacprehrajto'
addon = xbmcaddon.Addon(id=_ADDON_ID)

### SETTINGS
g_is_debug_logs_enabled = addon.getSetting("is_debug_logs_enabled")
g_max_searched_vids = int(addon.getSetting("ls"))
g_max_duplicities = int(addon.getSetting("max_duplicities"))
g_truncate_titles = addon.getSetting("truncate_titles")
g_download_path = addon.getSetting("download")
g_quality_selector = addon.getSetting("quality_selector") # 0 - CompressedHighest, 1 - Premium, 2 - Selector

### PATHs
translated_path = xbmcvfs.translatePath('special://home/addons/' + _ADDON_ID)
history_path = os.path.join(translated_path,'resources', 'history.txt')
subtitles_path = os.path.join(translated_path,'resources', 'subtitles\\')
cache_path = os.path.join(translated_path,'resources', 'cache\\')
qr_path = os.path.join(translated_path,'resources', 'qr.png')

gid = {28: "Akční", 12: "Dobrodružný", 16: "Animovaný", 35: "Komedie", 80: "Krimi", 99: "Dokumentární", 18: "Drama", 10751: "Rodinný", 14: "Fantasy", 36: "Historický", 27: "Horor", 10402: "Hudební", 9648: "Mysteriózní", 10749: "Romantický", 878: "Vědeckofantastický", 10770: "Televizní film", 53: "Thriller", 10752: "Válečný", 37: "Western", 10759: "Action & Adventure", 10751: "Rodinný", 10762: "Kids", 9648: "Mysteriózní", 10763: "News", 10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"}
headers = {'user-agent': 'kodi/prehraj.to'}
language = "en-US"
