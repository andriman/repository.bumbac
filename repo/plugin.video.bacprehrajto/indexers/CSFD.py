import requests
import xbmcgui
import xbmcplugin
from bs4 import BeautifulSoup

from common import get_user_agent
from utils.utils import get_url


def CSFDTop(_handle):
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
    articles = soup.find_all('article')
    names, logos, years = [], [], []
    for article in articles:
        year = article.find('div', {'class': 'article-content article-content-toplist'}).find('header').find('h3').find('span', {'class': 'film-title-info'}).find('span', {'class': 'info'}).text
        name = article.find('figure').find('a').find('img').get('alt')
        logo = article.find('figure').find('a').find('img').get('src').replace("//", "https://").replace("w60h85", "w140")
        years.append(year)
        names.append(name)
        logos.append(logo)

    for i in range(len(names)):
        url = get_url('search', names[i])
        addItemToScreen(_handle, f"{years[i]} {names[i]}", '', f"{logos[i]}",
                                url, True)
    xbmcplugin.endOfDirectory(_handle)


def addItemToScreen(_handle, name="", genre="", icon="", url="", is_folder=False, fanart="", plot=""):
    list_item = xbmcgui.ListItem(label=name)
    list_item.setInfo('video', {'title': name,
                                'genre': genre,
                                'plot': plot or name,
                                'mediatype': 'video'})
    list_item.setArt({'thumb': icon, 'icon': icon, 'fanart': fanart or icon})
    list_item.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(_handle, url, list_item, is_folder)