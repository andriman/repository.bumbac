# -*- coding: utf-8 -*-

import json
import os
import sys
import time
from typing import List, Optional, Tuple
from urllib.parse import quote, parse_qsl, unquote
from urllib.parse import urlparse
from urllib.request import urlopen

import requests
import unicodedata
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from bs4 import BeautifulSoup

from common import _ADDON_ID, addon, g_max_searched_vids, g_truncate_titles, g_download_path, g_quality_selector, \
    history_path, \
    headers, cache_path
from model.StreamData import StreamData
from model.SubData import SubData
from providers.prehrajto.get_stream_data import get_streams_data
from tmdb.tmdb import tmdb_episodes, tmdb_seasons, tmdb_serie, tmdb_movie, tmdb_serie_genre, tmdb_movie_genre, \
    genres_category, tmdb_year, years_category, search_tmdb, movie_category, serie_category
from utils.ClipboardUtils import ClipboardUtils
from utils.utils import truncate_middle, notify_file_size, dprint, \
    convert_size, urlencode, find_pattern, find_pattern_groups, format_eta_and_finish

_url = sys.argv[0]
_handle = int(sys.argv[1])

_last_page_content = None


def get_url(**kwargs):
    return '{0}?{1}'.format(_url, urlencode(kwargs))


def encode(string):
    line = unicodedata.normalize('NFKD', string)
    output = ''
    for c in line:
        if not unicodedata.combining(c):
            output += c
    return output


def get_premium():
    if addon.getSetting("email") != '':
        login = {"password": addon.getSetting("password"), "email": addon.getSetting("email"),
                 '_submit': 'Přihlásit+se', 'remember': 'on', '_do': 'login-loginForm-submit'}
        res = requests.post("https://prehraj.to/", login)
        soup = BeautifulSoup(res.content, "html.parser")
        title = soup.find('ul', {'class': 'header__links'})
        title = title.find('span', {'class': 'color-green'})
        if title is None:
            premium = 0
            cookies = res.cookies
            xbmcgui.Dialog().notification("Přehraj.to", "Premium účet neaktivní", xbmcgui.NOTIFICATION_INFO, 4000,
                                          sound=False)
        else:
            premium = 1
            cookies = res.cookies
            xbmcgui.Dialog().notification("Přehraj.to", "Premium: " + title.text, xbmcgui.NOTIFICATION_INFO, 4000,
                                          sound=False)
    else:
        premium = 0
        cookies = ''
    return premium, cookies


# def play_video(link):
#     data = urlparse(link)
#
#     dprint(f'play_video(): quality_selector: ' + quality_selector)
#
#     # Max Compressed
#     url = requests.get("https://prehraj.to" + data.path, headers=headers).content
#     file, sub = get_link(url)
#
#     notify_file_size(file)
#
#     listitem = xbmcgui.ListItem(path = file)
#     if sub != "":
#         subtitles = []
#         subtitles.append(sub)
#         listitem.setSubtitles(subtitles)
#
#     ############
#     # video_info = listitem.getInfo('video')
#     # video_info['plot'] = 'Stream size: '+file_size_str+'\r\n'+video_info.get('plot', '')
#     # listitem.setInfo('video', video_info)
#
#     xbmcplugin.setResolvedUrl(_handle, True, listitem)

def get_premium_link(link):
    link = "https://prehraj.to" + urlparse(link).path
    res = requests.get(link + "?do=download", headers=headers, allow_redirects=False)
    return res.headers['Location']


def play_video(link, force_selector=False):
    dprint(f'play_video(): force_selector: ' + str(force_selector) + ', quality_selector = 0')

    if g_quality_selector == "1" and force_selector == False:  # Premium.
        file = get_premium_link(link)
        notify_file_size(file)
        listitem = xbmcgui.ListItem(path=file)
        # Subtitles skipped. Premium should have them inside the file.

        xbmcplugin.setResolvedUrl(_handle, True, listitem)
    else:
        data = urlparse(link)
        content = requests.get("https://prehraj.to" + data.path, headers=headers).content

        streams: Optional[List[StreamData]]
        subs: Optional[List[SubData]]
        streams, subs = get_streams_data(content)
        if streams is None or len(streams) == 0:
            return

        if g_quality_selector == "0" and force_selector == False:  # Max Compressed

            # Find the highest quality stream (compressed)
            file = streams[0].path
            notify_file_size(file)

            listitem = xbmcgui.ListItem(path=file)

            # Download subs so they are properly named for the streamed video.
            name_wo_ext: Optional[str] = None
            extension: Optional[str] = None
            name_wo_ext, extension = get_name_ext(file, content)

            sub_paths = download_subtitles(subs, name_wo_ext, True, cache_path)

            if sub_paths is not None:
                subtitles = [item for item in sub_paths]
                listitem.setSubtitles(subtitles)

            ############
            # video_info = listitem.getInfo('video')
            # video_info['plot'] = 'Stream size: '+file_size_str+'\r\n'+video_info.get('plot', '')
            # listitem.setInfo('video', video_info)

            xbmcplugin.setResolvedUrl(_handle, True, listitem)
        elif g_quality_selector == "2" or force_selector:  # Selector
            selected_file, is_premium = open_stream_selector(link, streams)

            if selected_file is None:
                # Canceled.
                return

            notify_file_size(selected_file)

            listitem = xbmcgui.ListItem(path=selected_file)

            if not is_premium:
                # Subtitles only for non-premium link.
                name_wo_ext: Optional[str] = None
                extension: Optional[str] = None
                name_wo_ext, extension = get_name_ext(selected_file, content)

                sub_paths = download_subtitles(subs, name_wo_ext, True, cache_path)

                if sub_paths is not None:
                    subtitles = [item for item in sub_paths]
                    listitem.setSubtitles(subtitles)

            xbmcplugin.setResolvedUrl(_handle, True, listitem)


# Returns:
# str = file path
# bool = is_premium?
def open_stream_selector(link, streams) -> Tuple[Optional[str], bool]:
    # Insert premium link.
    premium_link = "https://prehraj.to" + urlparse(link).path + "?do=download"
    streams.insert(
        0,
        StreamData(
            label="Premium (Nejvyšší kvalita = Nejvyšší staž. data)",
            quality=0,
            path=premium_link
        )
    )

    # Open selector.
    label_list = [item.label for item in streams]
    selected = xbmcgui.Dialog().select(
        heading="Vybrat kvalitu",
        list=label_list,
        # preselect=
        # useDetails=True,
    )

    if selected == -1:
        return None, False

    return streams[selected].path, selected == 0


def play_video_premium(link, cookies):
    link = "https://prehraj.to" + urlparse(link).path
    url = requests.get(link, cookies=cookies).content
    file, sub = get_streams_data(url)

    res = requests.get(link + "?do=download", cookies=cookies, headers=headers, allow_redirects=False)
    file = res.headers['Location']

    notify_file_size(file)

    listitem = xbmcgui.ListItem(path=file)
    if sub != "":
        subtitles = []
        subtitles.append(sub)
        listitem.setSubtitles(subtitles)

    xbmcplugin.setResolvedUrl(_handle, True, listitem)


def history():
    name_list = open(history_path, "r", encoding="utf-8").read().splitlines()
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category)
        url = get_url(action='listing_search', name=category)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


# Expecting 01:54:22 or 00:54:41
def crop_time(time_str: str) -> str:
    if len(time_str) != 8:
        return time_str

    split_time = time_str.split(':')
    if split_time[0] != "00":
        return time_str

    return split_time[1] + ':' + split_time[2]

def search(name, params=None):
    if name == "None":
        kb = xbmc.Keyboard("", 'Zadejte název filmu nebo seriálu')
        kb.doModal()
        if not kb.isConfirmed():
            return
        q = kb.getText()
        if q == "":
            return
    else:
        q = encode(name)

    dprint(f'Search(): ' + q)

    if os.path.exists(history_path):
        lh = open(history_path, "r").read().splitlines()
        if q not in lh:
            if len(lh) == 10:
                del lh[-1]
            lh.insert(0, q)
            f = open(history_path, "w")
            for item in lh:
                f.write("%s\n" % item)
            f.close()
    else:
        f = open(history_path, "w")
        f.write(q)
        f.close()

    max_pages_to_browse = 5
    p = 1
    videos = []
    duplicities_set = []
    premium = 0

    p_dialog_step = int(100 / g_max_searched_vids)
    p_dialog = xbmcgui.DialogProgress()
    p_dialog.create("Přehraj.to", "Hledám video soubory...")
    p_dialog.update(
        int(len(videos) * p_dialog_step),
        "Strana:         " + str(p) + "\n"
        "Video souborů:  " + str(len(videos)) + "\n"
    )

    if addon.getSetting("email") and len(addon.getSetting("email")) > 0:
        premium, cookies = get_premium()

    stop_searching = False
    while not (stop_searching or p_dialog.iscanceled()):
        dprint('search(): processing page: ' + str(p))

        if p > 1:
            xbmc.Monitor().waitForAbort(3)

        if premium == 1:
            html = requests.get('https://prehraj.to:443/hledej/' + quote(q) + '?vp-page=' + str(p),
                                cookies=cookies).content
        else:
            html = requests.get('https://prehraj.to:443/hledej/' + quote(q) + '?vp-page=' + str(p)).content

        p_dialog.update(
            int(len(videos) * p_dialog_step),
            "Strana:         " + str(p) + "\n"
            "Video souborů:  " + str(len(videos)) + "\n"
        )

        soup = BeautifulSoup(html, "html.parser")
        title = soup.find_all('h3', attrs={'class': 'video__title'})
        size = soup.find_all('div', attrs={'class': 'video__tag--size'})
        time = soup.find_all('div', attrs={'class': 'video__tag--time'})
        link = soup.find_all('a', {'class': 'video--link'})
        # next = soup.find_all('div',{'class': 'pagination-more'})
        next = soup.find_all('a', {'title': 'Zobrazit další'})

        dprint('search(): titles: ' + str(title))

        for t, s, l, m in zip(title, size, link, time):

            if t is None:
                dprint('search(): Fuckup..')
                continue

            t = t.text.strip()
            s = s.text.strip()
            m = crop_time(m.text.strip())

            pot_dupl_name = t + " (" + s + " - " + m + ")"

            if not duplicities_set.__contains__(pot_dupl_name):
                final_title = t
                if g_truncate_titles:
                    final_title = truncate_middle(final_title)

                dprint('search(): final title: ' + final_title)
                videos.append(
                    (
                        final_title,
                        ' (' + s + " - " + m + ')',
                        'https://prehraj.to:443' + l['href'],
                        t
                    )
                )

                duplicities_set.append(pot_dupl_name)
            else:
                dprint('search(): duplicity: ' + pot_dupl_name)

        p = p + 1

        stop_searching = next == [] or len(videos) >= int(g_max_searched_vids) or p == max_pages_to_browse

    p_dialog.close()
    if not videos:
        xbmcgui.Dialog().notification("Přehraj.to", "Nenalezeno:\r\n" + q, xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
        # TODO - possibly let user change the searched string.
        return

    xbmcplugin.setContent(_handle, 'videos')

    dprint('search(): found: ' + str(len(videos)))
    for category in videos[:int(g_max_searched_vids)]:
        #dprint('search(): found item: ' + str(category))
        list_item = xbmcgui.ListItem(label=category[0] + category[1])

        if params is not None and len(params) > 0:
            art = params.get("art", None)
            if art is not None:
                art = json.loads(art)
                list_item.setArt(art)

            video_info = params.get("videoInfo", None)
            if video_info is not None:
                video_info = json.loads(video_info)
                # video_info['title'] = category[0] + category[1]
                video_info['title'] = category[3]
                list_item.setInfo('video', video_info)

        list_item.setProperty('IsPlayable', 'true')
        list_item.addContextMenuItems(
            [
                ('Vybrat stream',
                 'RunPlugin({})'.format(
                     get_url(action="play", link=category[2], force_selector=True))
                 ),
                ('Kopírovat URL', 'RunPlugin({})'.format(get_url(action="copy_url", url=category[2]))),
                ('Uložit do knihovny', 'RunPlugin({})'.format(get_url(action="library", url=category[2]))),
                ('Stáhnout', 'RunPlugin({})'.format(get_url(action="download", url=category[2]))),
                ('QR kód streamu', 'RunPlugin({})'.format(get_url(action="qr", url=category[2])))
            ]
        )
        url = get_url(action='play', link=category[2])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, False)
    xbmcplugin.endOfDirectory(_handle)


def menu():
    if os.path.exists(history_path):
        name_list = [("Hledat", "listing_search", "None", ""), ("Historie hledání", "listing_history", "None", ""),
                     ("Filmy", "listing_movie_category", "", ""), ("Seriály", "listing_serie_category", "", "")]
    else:
        name_list = [("Hledat", "listing_search", "None", ""), ("Filmy", "listing_movie_category", "", ""),
                     ("Seriály", "listing_serie_category", "", "")]
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category[0])
        url = get_url(action=category[1], name=category[2], type=category[3])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def home():
    xbmc.executebuiltin("Dialog.Close(all, true)")  # Zavře všechna okna/dialogy
    xbmc.executebuiltin(f"RunPlugin(plugin://{_ADDON_ID}/)")  # Spustí kořenovou stránku doplňku
    # xbmc.executebuiltin("ActivateWindow(Home)")  # Go to Kodi's main menu
    # xbmc.executebuiltin("Container.Update(plugin://plugin.video.bacprehrajto/, replace)")  # Go to root


def copy_to_clipboard(text: str) -> None:
    dprint(f'copy_to_clipboard(): ' + text)
    ClipboardUtils.copy_to_clipboard(text)


def get_name_ext(download_url: str, content: bytes) -> Tuple[Optional[str], Optional[str]]:
    name_wo_ext: Optional[str] = None
    extension: Optional[str] = None

    filename_groups = find_pattern_groups(download_url, r'filename=(([^&\?]+)\.([^&\?]+))')
    if filename_groups is not None:
        name_wo_ext = filename_groups.group(2)
        extension = filename_groups.group(3)

    if content is not None and (name_wo_ext is None or extension is None):
        content_str = content.decode('utf-8')
        # Non-premium link does looks like:
        if name_wo_ext is None:
            name_wo_ext = find_pattern(content_str, r'N.zev souboru:<\/span>\s*?<span>([^<]+?)<\/span>')
            name_wo_ext = unquote(name_wo_ext.strip()).replace(' ', '.')

        # .....f5DfDqhRyiVeuZxf9gteE.mp4?token=....
        if extension is None:
            extension = find_pattern(download_url, r'\.([a-zA-Z0-9]+)[&\?]token')
            if extension is None:
                extension = find_pattern(content_str, r'Form.t:</span>\s*?<span>([^<]+?)</span>')

    # name = parsed1.split("/")[1] + "." + parsed2.split(".")[-1]
    if name_wo_ext is None:
        parsed1 = urlparse(download_url).path
        name_wo_ext = parsed1.split("/")[1]

    return name_wo_ext, extension


def download_subtitles(
        subs: Optional[List[SubData]], name_wo_ext: str,
        use_name_as_subfolder: bool = False, path: str = g_download_path
) -> Optional[List[str]]:
    if subs is None or len(subs) == 0:
        return None

    # TODO: Delete cache.
    delete_subtitles(subs, name_wo_ext, use_name_as_subfolder, True, path)

    sub_paths: List[str] = []

    if use_name_as_subfolder:
        path = path + "/" + name_wo_ext + "/"
        dprint('download_subtitles(): ' + path)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    for sub in subs:
        name_prefix = "" if use_name_as_subfolder else (name_wo_ext + "-")
        #name_size_suffix = (name_wo_ext + "-") if use_name_as_subfolder else ""
        name_subtitles = name_prefix + sub.label + ".srt"
        us = urlopen(sub.path).read()
        fs = open(path + name_subtitles, "wb")
        sub_paths.append(path + name_subtitles)
        fs.write(us)
        fs.close()

    return sub_paths

def delete_subtitles(
        subs: List[SubData], name_wo_ext: str,
        use_name_as_subfolder: bool = False,
        all_except_name: bool = False,
        path: str = g_download_path
):
    if subs is None or len(subs) == 0:
        return

    if use_name_as_subfolder:
        path = path + "/" + name_wo_ext + "/"

    try:
        if all_except_name:
            # TODO.
            os.chdir(path)
            for item in os.listdir(os.getcwd()):
                if item != name_wo_ext:
                    os.remove(item)
        else:
            for sub in subs:
                name_prefix = "" if use_name_as_subfolder else (name_wo_ext + "-")
                #name_size_suffix = (name_wo_ext + "-") if use_name_as_subfolder else ""
                name_subtitles = name_prefix + sub.label + ".srt"
                os.remove(path + name_subtitles)
            os.remove(path)
    except Exception as e:
        dprint('delete_subtitles(): could not delete subtitles:\n' + str(e))
        return


def download(download_url: str) -> None:
    if addon.getSetting("download") == "":
        xbmcgui.Dialog().notification(
            "Přehraj.to",
            "Nastavte složku pro stahování",
            xbmcgui.NOTIFICATION_ERROR,
            4000
        )
        return

    content = requests.get(download_url).content

    # 'N.zev souboru:</span>\s*?<span>([^<]+?)</span>'
    # 'Velikost:</span>\s*?<span>([^<]+?)</span>'
    # 'Form.t:</span>\s*?<span>([^<]+?)</span>'

    streams: Optional[List[StreamData]]
    subs: Optional[List[SubData]]
    streams, subs = get_streams_data(content)
    if streams is None or len(streams) == 0:
        return

    file, selected_premium = open_stream_selector(download_url, streams)

    premium, cookies = get_premium()
    # if premium == 1 or selected_premium:
    if selected_premium:
        res = requests.get(download_url + "?do=download", cookies=cookies, allow_redirects=False)
        file = res.headers['Location']
        dprint('download(): premium file: ' + file)

    name_wo_ext: Optional[str] = None
    extension: Optional[str] = None
    name_wo_ext, extension = get_name_ext(file, content)

    name = (name_wo_ext if name_wo_ext is not None else "downloaded") + (
                "." + extension) if extension is not None else ""

    # Save subtitles.
    download_subtitles(subs, name_wo_ext)

    # Prepare video download file.
    download_file_path = g_download_path + name
    u = urlopen(file)
    f = open(download_file_path, "wb")
    file_size = int(u.getheader("Content-Length"))

    dialog = xbmcgui.DialogProgress()
    dialog.create("Přehraj.to", "Stahování...")

    start = time.time()
    file_size_dl = 0
    block_sz = 4096
    canceled = False

    # Prepare data for update dialog:
    # Velikost, komprese.
    du_conv_size = convert_size(file_size)
    is_compressed = not selected_premium
    du_compressed_str = "      (komprimováno)" if is_compressed else ""
    du_truncated_name = truncate_middle(name)

    while True:
        if dialog.iscanceled():
            canceled = True
            break

        buffer = u.read(block_sz)
        if not buffer: break
        file_size_dl += len(buffer)
        f.write(buffer)

        # 1. Progress percentage
        status = r"%3.2f%%" % (file_size_dl * 100. / file_size)
        status = status + chr(8) * (len(status) + 1)  # erase old line

        # 3. Speed + ETA + čas dokončení
        elapsed = time.time() - start
        speed = "0.0" if elapsed <= 0 else f"{(file_size_dl / elapsed) / 100000:.1f}"
        if elapsed > 0 and file_size_dl > 0:
            bytes_per_sec = file_size_dl / elapsed
            remaining_bytes = file_size - file_size_dl
            eta_seconds = remaining_bytes / bytes_per_sec if bytes_per_sec > 0 else None
        else:
            eta_seconds = None

        eta_str, finish_str = format_eta_and_finish(eta_seconds)

        # 4. Aktualizace dialogu
        dialog.update(
            int(file_size_dl * 100 / file_size),
            "Velikost:  " + du_conv_size + du_compressed_str + "\n"
            + "Staženo:  " + status + "     Rychlost: " + speed + " Mb/s\n"
            + "Hotovo za: " + eta_str + "       Hotovo v:  " + finish_str + "\n"
            + du_truncated_name
        )

    f.close()
    dialog.close()

    if not canceled:
        dialog = xbmcgui.Dialog()
        dialog.ok('Přehraj.to', 'Soubor stažen\n' + name)
    else:
        os.remove(download_file_path)
        delete_subtitles(subs, name_wo_ext)


def router(paramstring):
    params = dict(parse_qsl(paramstring))
    if params:
        if params["action"] == "home":
            home()
        if params["action"] == "listing_search":
            search(params["name"], params)
        elif params["action"] == "listing_history":
            history()
        elif params["action"] == "listing_episodes":
            tmdb_episodes(_handle, _url, params["name"], params)
        elif params["action"] == "listing_seasons":
            tmdb_seasons(_handle, _url, params["name"], params["type"])
        elif params["action"] == "listing_year":
            tmdb_year(_handle, _url, params["page"], params["type"], params["id"])
        elif params["action"] == "listing_year_category":
            years_category(_handle, _url, params["name"])
        elif params["action"] == "listing_movie_category":
            movie_category(_handle, _url)
        elif params["action"] == "listing_serie_category":
            serie_category(_handle, _url)
        elif params["action"] == "listing_genre_category":
            genres_category(_handle, _url, params["name"])
        elif params["action"] == "listing_genre":
            if params["type"] == 'movie':
                tmdb_movie_genre(_handle, _url, params["page"], params["type"], params["id"])
            else:
                tmdb_serie_genre(_handle, _url, params["page"], params["type"], params["id"])
        elif params["action"] == "listing_tmdb_movie":
            tmdb_movie(_handle, _url, params["name"], params["type"])
        elif params["action"] == "listing_tmdb_serie":
            tmdb_serie(_handle, _url, params["name"], params["type"])
        elif params["action"] == "search_tmdb":
            search_tmdb(_handle, _url, params["name"], params["type"])
        elif params["action"] == "play":
            premium, cookies = get_premium()
            if premium == 1:  ## Not necessary...
                play_video_premium(params["link"], cookies)
            else:
                force_selector = params.__contains__("force_selector") and params["force_selector"] == 'True'
                play_video(params["link"], force_selector)
        elif params["action"] == "library":
            if addon.getSetting("library") == "":
                xbmcgui.Dialog().notification(
                    "Přehraj.to", "Nastavte složku pro knihovnu",
                    xbmcgui.NOTIFICATION_ERROR, 3000
                )
                return
            parsed1 = urlparse(params["url"]).path
            name = parsed1.split("/")[1]
            kb = xbmc.Keyboard(name.replace("-", " "), 'Zadejte název a rok filmu')
            kb.doModal()
            if not kb.isConfirmed():
                return
            q = kb.getText()
            if q == "":
                return
            f = open(addon.getSetting("library") + q + ".strm", "w")
            f.write("plugin://plugin.video.bacprehrajto/?action=play&link=" + params["url"])
            f.close()
            xbmcgui.Dialog().notification("Přehraj.to", "Uloženo", xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
        elif params["action"] == "qr":
            u = requests.get(params["url"]).content
            streams, subs = get_streams_data(u)
            selected_file, is_premium = open_stream_selector(params["url"], streams)
            if selected_file is None:
                # Canceled.
                return

            qr_link = "https://quickchart.io/qr?text=" + selected_file.replace('&', '%26')
            dprint("qr: " + qr_link)
            xbmc.executebuiltin('ShowPicture(' + qr_link + ')')
        elif params["action"] == "copy_url":
            copy_to_clipboard(params["url"])
        elif params["action"] == "download":
            download(params["url"])
    else:
        menu()


if __name__ == '__main__':
    router(sys.argv[2][1:])
