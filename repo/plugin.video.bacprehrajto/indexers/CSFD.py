import sys

import requests
import xbmcgui
import xbmcplugin
from bs4 import BeautifulSoup

from common import get_user_agent
from utils.listitem_infotag import apply_art, apply_video_info
from utils.utils import get_url


def CSFDTop(_handle):
    plugin_url = sys.argv[0] if len(sys.argv) > 0 else ''
    url = "https://www.csfd.cz/zebricky/filmy/nejlepsi/"
    headers = {
        'User-Agent': get_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://www.csfd.cz/',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Sec-GPC': '1'
    }
    html = requests.get(url, headers=headers).text
    soup = BeautifulSoup(html, 'html.parser')
    articles = soup.find_all('article') or []
    try:
        xbmcplugin.setContent(_handle, 'movies')
        xbmcplugin.setPluginCategory(_handle, 'ČSFD Top')
    except (AttributeError, RuntimeError, TypeError):
        pass

    for article in articles:
        try:
            year_node = (
                article.find('div', {'class': 'article-content article-content-toplist'})
                .find('header').find('h3')
                .find('span', {'class': 'film-title-info'})
                .find('span', {'class': 'info'})
            )
            img = article.find('figure').find('a').find('img')
            if year_node is None or img is None:
                continue
            year = (year_node.text or '').strip()
            name = (img.get('alt') or '').strip()
            src = (img.get('src') or '').strip()
            if not name or not src:
                continue
            logo = src.replace('//', 'https://').replace('w60h85', 'w140')
            label = f'{year} {name}'.strip() if year else name
            if not plugin_url:
                continue
            item_url = get_url(plugin_url, action='listing_search', name=name)
            addItemToScreen(_handle, label, '', logo, item_url, True, fanart=logo, plot=name)
        except (AttributeError, TypeError, ValueError):
            continue
    xbmcplugin.endOfDirectory(_handle)


def addItemToScreen(_handle, name="", genre="", icon="", url="", is_folder=False, fanart="", plot=""):
    if not name or not url:
        return
    list_item = xbmcgui.ListItem(label=name)
    info = {
        'title': name,
        'plot': plot or name,
        'mediatype': 'movie',
    }
    if genre:
        info['genre'] = genre
    apply_video_info(list_item, info)
    apply_art(list_item, {
        'thumb': icon,
        'icon': icon,
        'poster': icon,
        'fanart': fanart or icon,
    })
    list_item.setProperty('IsPlayable', 'false' if is_folder else 'true')
    xbmcplugin.addDirectoryItem(_handle, url, list_item, is_folder)