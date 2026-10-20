# -*- coding: utf-8 -*- 

import os
import sys
import urllib, urllib.parse, urllib.request
import xbmc, xbmcvfs, xbmcaddon, xbmcgui, xbmcplugin
import shutil
import re
import unicodedata

__addon__      = xbmcaddon.Addon()
__author__     = __addon__.getAddonInfo('author')
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')
__version__    = __addon__.getAddonInfo('version')
__language__   = __addon__.getLocalizedString

__cwd__        = xbmcvfs.translatePath( __addon__.getAddonInfo('path') )
__profile__    = xbmcvfs.translatePath( __addon__.getAddonInfo('profile') )
__resource__   = xbmcvfs.translatePath( os.path.join( __cwd__, 'resources', 'lib' ) )
__temp__       = xbmcvfs.translatePath( os.path.join( __profile__, 'temp', '') )
__playback__   = xbmcvfs.translatePath( os.path.join( __profile__, 'playback-subs', '') )

sys.path.append (__resource__)

from utilities import log, extract_subtitles, select_file_menu
from titulky_client import TitulkyClient as SubtitlesClient

def _playing_file():
  player = xbmc.Player()
  if not player.isPlaying():
    return ""
  return player.getPlayingFile() or ""

def _prepare_playback_subs():
  xbmcvfs.mkdirs(__playback__)
  marker = os.path.join(__playback__, ".playing")
  current = _playing_file()
  previous = ""
  if os.path.isfile(marker):
    try:
      with open(marker, "r", encoding="utf-8") as handle:
        previous = handle.read()
    except OSError:
      previous = ""
  if previous == current:
    return
  for entry in os.listdir(__playback__):
    path = os.path.join(__playback__, entry)
    if os.path.isfile(path):
      try:
        os.remove(path)
      except OSError:
        pass
  try:
    with open(marker, "w", encoding="utf-8") as handle:
      handle.write(current)
  except OSError:
    pass

def _is_language_token(token):
  try:
    return bool(xbmc.convertLanguage(token, xbmc.ISO_639_2))
  except Exception:
    return False

def _kodi_subtitle_name(subtitle_path, video_path):
  video_name = os.path.splitext(os.path.basename(urllib.parse.unquote((video_path or "").split("?", 1)[0].split("#", 1)[0])))[0]
  to_parse = os.path.splitext(os.path.basename(subtitle_path))[0]
  if video_name and to_parse.lower().startswith(video_name.lower()):
    to_parse = to_parse[len(video_name):]
  start = re.search(r"[A-Za-z0-9]", to_parse)
  tokens = re.split(r"[ .\-]+", to_parse[start.start():]) if start else []
  kept = []
  found_language = False
  for token in reversed([token for token in tokens if token]):
    if token.lower() in ("none", "default", "forced"):
      continue
    if not found_language and _is_language_token(token):
      found_language = True
      continue
    kept.append(token)
  kept.reverse()
  external = xbmc.getLocalizedString(21602) or "External"
  return re.sub(r"\s+", " ", ("%s %s" % (" ".join(kept), external)).strip())

def _loaded_subtitle_names():
  player = xbmc.Player()
  if not player.isPlaying():
    return set()
  try:
    names = player.getAvailableSubtitleStreams() or []
  except Exception:
    return set()
  return set(name.strip().lower() for name in names if name)

def _playback_filename(path, lang):
  stem, ext = os.path.splitext(os.path.basename(path))
  ext = ext or ".srt"
  lang = (lang or "").strip().lower()
  if len(lang) == 2 and lang.isalpha() and not stem.lower().endswith("." + lang):
    stem = "%s.%s" % (stem, lang)
  stem = re.sub(r'[<>:"/\\|?*]', "_", stem).strip().strip(".")
  if not stem:
    stem = "subtitle"
    if lang:
      stem = "%s.%s" % (stem, lang)
  return stem + ext

def _add_playback_subtitles(subtitle_list, lang):
  if not subtitle_list or not xbmc.Player().isPlaying():
    return
  _prepare_playback_subs()
  loaded = _loaded_subtitle_names()
  video = _playing_file()
  for path in subtitle_list:
    filename = _playback_filename(path, lang)
    dest = os.path.join(__playback__, filename)
    display = _kodi_subtitle_name(dest, video).lower()
    if display in loaded:
      log(__scriptname__, ["subtitle already in player", display])
      continue
    try:
      shutil.copyfile(path, dest)
      xbmc.Player().setSubtitles(dest)
      loaded.add(display)
      log(__scriptname__, ["added subtitle", dest])
    except Exception as exc:
      log(__scriptname__, ["could not add subtitle", dest, exc])

def _add_search_action(label, query):
  # Arctic Zephyr prints "label • label2". Leave label empty so the action is shown once.
  # 98bbbbbb is the subtitle-row color (#bbbbbb) at 85% of its usual opacity.
  listitem = xbmcgui.ListItem(label="", label2="[COLOR 98bbbbbb]%s[/COLOR]" % label)
  listitem.setProperty("sync", "false")
  listitem.setProperty("hearing_imp", "false")
  url = "plugin://%s/?action=search&%s" % (__scriptid__, query)
  xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def Search(item):
  _prepare_playback_subs()

  cli = SubtitlesClient(__addon__)
  found_subtitles = cli.search(item) or []

  for subtitle in found_subtitles:
    listitem = xbmcgui.ListItem(label=subtitle['lang'], label2=subtitle['filename'])  # language name for the found subtitle # file name for the found subtitle
    listitem.setArt({ "icon": subtitle['rating'], "thumb": subtitle['lang_flag'] }) # rating for the subtitle, string 0-5 # language flag, ISO_639_1 language + gif extention, e.g - "en.gif"
    listitem.setProperty("sync", ("false", "true")[int(subtitle['sync'])])  # set to "true" if subtitle is matched by hash,
    listitem.setProperty("hearing_imp", "false") # set to "true" if subtitle is for hearing impared

    url = "plugin://%s/?action=download&link=%s&lang=%s&name=%s" % (__scriptid__, urllib.parse.quote(subtitle['link']), subtitle['lang'], urllib.parse.quote(subtitle.get('filename') or ''))
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),url=url,listitem=listitem,isFolder=False)

  _add_search_action(__language__(32948) or "...Custom search...", "refine=1")
  _add_search_action(__language__(32949) or "...Addon settings...", "settings=1") 


def _rename_subtitle(path, name):
  ext = os.path.splitext(path)[1] or ".srt"
  cleaned = re.sub(r'[<>:"/\\|?*]', "_", name or "").strip().strip(".")
  if not cleaned:
    return path
  if not cleaned.lower().endswith(ext.lower()):
    cleaned += ext
  dest = os.path.join(os.path.dirname(path), cleaned)
  if os.path.normcase(os.path.abspath(dest)) == os.path.normcase(os.path.abspath(path)):
    return path
  if os.path.exists(dest):
    os.remove(dest)
  os.replace(path, dest)
  return dest

def Download(link, lang, name=""):
  log(__scriptname__,["DL Link", link])

  subtitle_list = []
  ## Cleanup temp dir, we recomend you download/unzip your subs in temp folder and
  ## pass that to XBMC to copy and activate
  if xbmcvfs.exists(__temp__):
    shutil.rmtree(__temp__)
  xbmcvfs.mkdirs(__temp__)

  cli = SubtitlesClient(__addon__)
  downloaded_file = cli.download(link, name)
  if not downloaded_file:
    return []

  if downloaded_file.lower().endswith((".rar",".zip")):
    log(__scriptname__,"Extracting subtitles")
    subtitle_list = extract_subtitles(downloaded_file)
  else:
    subtitle_list = [downloaded_file]

  if len(subtitle_list) == 1 and name:
    subtitle_list = [_rename_subtitle(subtitle_list[0], name)]

  log(__scriptname__,subtitle_list)

  subtitle_list = select_file_menu(subtitle_list, __language__(32004))
  _add_playback_subtitles(subtitle_list, lang)

  return subtitle_list
 
def normalizeString(str_input):
  return unicodedata.normalize('NFKD', str_input).encode('ascii','ignore').decode("utf-8")
 
def get_params():
  param=[]
  paramstring=sys.argv[2]
  if len(paramstring)>=2:
    params=paramstring
    cleanedparams=params.replace('?','')
    if (params[len(params)-1]=='/'):
      params=params[0:len(params)-2]
    pairsofparams=cleanedparams.split('&')
    param={}
    for i in range(len(pairsofparams)):
      splitparams={}
      splitparams=pairsofparams[i].split('=')
      if (len(splitparams))==2:
        param[splitparams[0]]=splitparams[1]
                                
  return param

params = get_params()
log(__scriptname__, ["action", params['action']])

if params['action'] == 'search' or params['action'] == 'manualsearch':
  # prepare mac_addr
  xbmc.getInfoLabel('Network.MacAddress')

  item = {}
  item['temp']               = False
  item['rar']                = False
  item['mansearch']          = False
  item['year']               = xbmc.getInfoLabel("VideoPlayer.Year")                           # Year
  item['season']             = str(xbmc.getInfoLabel("VideoPlayer.Season"))                    # Season
  item['episode']            = str(xbmc.getInfoLabel("VideoPlayer.Episode"))                   # Episode
  item['tvshow']             = normalizeString(xbmc.getInfoLabel("VideoPlayer.TVshowtitle"))   # Show
  item['title']              = normalizeString(xbmc.getInfoLabel("VideoPlayer.OriginalTitle")) # try to get original title
  item['file_original_path'] = urllib.parse.unquote(xbmc.Player().getPlayingFile())  # Full path of a playing file
  item['3let_language']      = []

  if params.get('settings') == '1':
    __addon__.openSettings()

  item['refine'] = params.get('refine') == '1'

  if 'searchstring' in params:
    item['mansearch'] = True
    item['mansearchstr'] = urllib.parse.unquote(params['searchstring'])
  
  if 'languages' in params:
    for lang in urllib.parse.unquote(params['languages']).split(","):
      item['3let_language'].append(xbmc.convertLanguage(lang,xbmc.ISO_639_2))
  
  if item['title'] == "":
    item['title']  = normalizeString(xbmc.getInfoLabel("VideoPlayer.Title"))      # no original title, get just Title
    
  if item['episode'].lower().find("s") > -1:                                      # Check if season is "Special"
    item['season'] = "0"                                                          #
    item['episode'] = item['episode'][-1:]
  
  if ( item['file_original_path'].find("http") > -1 ):
    item['temp'] = True

  elif ( item['file_original_path'].find("rar://") > -1 ):
    item['rar']  = True
    item['file_original_path'] = os.path.dirname(item['file_original_path'][6:])

  elif ( item['file_original_path'].find("stack://") > -1 ):
    stackPath = item['file_original_path'].split(" , ")
    item['file_original_path'] = stackPath[0][8:]

  log(__scriptname__,["Input", item])
  Search(item)  

elif params['action'] == 'download':
  ## we pickup all our arguments sent from def Search()
  subs = Download(urllib.parse.unquote(params["link"]), params["lang"], urllib.parse.unquote(params.get("name") or ""))
  ## we can return more than one subtitle for multi CD versions, for now we are still working out how to handle that in XBMC core
  for sub in subs:
    listitem = xbmcgui.ListItem(label=sub)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),url=sub,listitem=listitem,isFolder=False)
  
  
xbmcplugin.endOfDirectory(int(sys.argv[1])) ## send end of directory to XBMC
  
  
  
  
  
  
  
  
  
    
