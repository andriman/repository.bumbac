import json
from urllib.parse import quote
from urllib.request import urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from utils.utils import get_url
from common import gid, language
from utils.utils import dprint
from datetime import datetime

def tmdb_episodes(_handle, _url, sname, params):
    type = params["type"]
    ses_num = params["ses_num"]
    fanart = params.get("fanart", "")
    thumb = params.get("thumb", "")  ### Some series do not have thumb, ex: Secret Lives series

    dprint(f'sname(): ' + sname)

    html = urlopen(
        'https://api.themoviedb.org/3/tv/' + type + '/season/' + ses_num + '?api_key=1f0150a5f78d4adc2407911989fdb66c').read()
    res = json.loads(html)
    #dprint(f'tmdb_episodes(): ' + str(res))

    for category in res['episodes']:
        if not category['name']: category['name'] = "Neznámo"
        if category['name'] != 'Speciály' and category['name'] != 'Specials':
            epNo = 'E' + str(category['episode_number'])
            list_item = xbmcgui.ListItem(label=epNo + ': ' + category['name'])

            plot = category['overview']
            if plot == "":
                plot = "~ empty ~"

            ####

            # Extract director(s)
            directors = [
                member['name'] for member in category.get('crew', [])
                if member.get('job') == 'Director'
            ]

            # Extract main cast (guest_stars + top-billed actors)
            main_cast = []
            # for actor in category.get('guest_stars', [])[:10]:  # Limit to top 10
            #     main_cast.append({
            #         'name': actor.get('name', ''),
            #         'role': actor.get('character', ''),
            #         'thumbnail': f"https://image.tmdb.org/t/p/original{actor.get('profile_path', '')}" if actor.get(
            #             'profile_path') else ''
            #     })

            # Create castandrole list (tuple of name,character)
            castandrole = [
                (star['name'], star['character'])
                for star in category.get('guest_stars', [])[:20]  # First 20 guest stars
                if star.get('name') and star.get('character')
            ]
            # Build extended plot with director info
            extended_plot = plot
            if directors:
                extended_plot += f"\n\nDirectors: {', '.join(directors)}"

            videoInfo = {
                'title': category['name'],
                # 'genre': genre,
                'plot': extended_plot,
                'plotoutline': plot,  # Keep original plot for brief view
                'year': category['air_date'],
                'rating': category["vote_average"],
                # 'director': directors,
                # 'cast': main_cast,
                'castandrole': castandrole,
                # Additional metadata
                # 'writer': [
                #     member['name'] for member in category.get('crew', [])
                #     if member.get('job') == 'Writer'
                # ],
                'premiered': category.get('air_date', ''),
                'episode': category.get('episode_number', 0),
                'status': category.get('status', 'Released')
            }

            # videoInfo = {
            #     'title': category['name'],
            #     'plot': plot,
            #     'plotoutline': plot,
            #     'year': category['air_date'],
            #     'rating': category["vote_average"],
            # }

            list_item.setInfo('video', videoInfo)

            #dprint("tmdb_episodes(): " + str(category))
            #dprint("tmdb_episodes(): " + str(videoInfo))

            # Set cast thumbnails if available
            # if main_cast:
            #     dprint("tmdb_episodes cast(): "+main_cast)
            #     list_item.setCast(main_cast)

            ###

            ####

            # videoInfo = {
            #     'title': category['name'],
            #     'plot': plot,
            #     'plotoutline': plot,
            #     'year': category['air_date'],
            #     'rating': category["vote_average"],
            # }
            #

            art = {'thumb': thumb, 'icon': thumb, 'fanart': fanart}

            list_item.setInfo('video', videoInfo)
            list_item.setArt(art)

            full_name = sname + ' S' + str(category['season_number']).zfill(2) + 'E' + str(
                category['episode_number']).zfill(2)
            url = get_url(_url, action='listing_search', name=full_name, type=type, videoInfo=json.dumps(videoInfo),
                          art=json.dumps(art))
            xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def tmdb_seasons(_handle, _url, name, type):
    html = urlopen(
        'https://api.themoviedb.org/3/tv/' + type + '?api_key=1f0150a5f78d4adc2407911989fdb66c&language=' + language).read()
    res = json.loads(html)
    dprint(f'tmdb_seasons(): ' + str(res))
    try:
        fanart = "https://image.tmdb.org/t/p/w1280" + res["backdrop_path"]
    except:
        fanart = ""
    for category in res['seasons']:
        if category['name'] != 'Speciály' and category['name'] != 'Specials':
            list_item = xbmcgui.ListItem(label=category['name'])
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""
            list_item.setArt({'thumb': thumb, 'icon': thumb, 'fanart': fanart})

            plot = category['overview']
            if plot == "":
                plot = "~ empty ~"

            list_item.setInfo('video', {
                'title': category['name'],
                'plot': plot,
                'plotoutline': plot,
                'year': category['air_date'],
                'rating': category["vote_average"],
            })

            url = get_url(_url, action='listing_episodes', name=name, type=type, ses_num=str(category['season_number']),
                          fanart=fanart, thumb=thumb)
            xbmcplugin.addDirectoryItem(_handle, url, list_item, True)

    xbmcplugin.endOfDirectory(_handle)


def tmdb_serie(_handle, _url, page, type):
    p = int(page)
    html = urlopen(
        'https://api.themoviedb.org/3/tv/' + type + '?api_key=1f0150a5f78d4adc2407911989fdb66c&language=' + language + '&page=' + str(
            p)).read()
    res = json.loads(html)
    dprint(f'tmdb_serie(): ' + str(res))

    res["results"].append({"name": "Další"})
    xbmcplugin.setContent(_handle, 'videos')
    for category in res['results']:
        list_item = xbmcgui.ListItem(label=category['name'])
        if category['name'] == "Další":
            url = get_url(_url, action='listing_tmdb_serie', name=str(p + 1), type=type)
        else:
            gl = []
            for g in category["genre_ids"]:
                gl.append(gid[g])
            genre = " / ".join(gl)
            list_item.setInfo('video', {'mediatype': 'movie', 'title': category['name'], "plot": category['overview'],
                                        "year": category['first_air_date'].split('-')[0], 'genre': genre,
                                        'rating': str(category["vote_average"])[:3]})
            try:
                fanart = "https://image.tmdb.org/t/p/w1280" + category["backdrop_path"]
            except:
                fanart = ""
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""
            list_item.setArt({'thumb': thumb, 'icon': thumb, 'fanart': fanart})
            url = get_url(_url, action='listing_seasons', name=category['name'], type=category["id"])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def tmdb_movie(_handle, _url, page, type):
    dprint("tmdb_movie()")

    p = int(page)
    html = urlopen(
        'https://api.themoviedb.org/3/movie/' + type + '?api_key=1f0150a5f78d4adc2407911989fdb66c&language=' + language + '&page=' + str(
            p)).read()
    res = json.loads(html)
    res["results"].append({"title": "Další"})
    res["results"].append({"title": "Domů"})
    xbmcplugin.setContent(_handle, 'videos')
    for category in res['results']:
        list_item = xbmcgui.ListItem(label=category['title'])
        if category['title'] == "Další":
            url = get_url(_url, action='listing_tmdb_movie', name=str(p + 1), type=type)
        elif category['title'] == "Domů":
            url = get_url(_url, action='home', name=str(p + 1), type=type)
        else:
            gl = []
            for g in category["genre_ids"]:
                gl.append(gid[g])
            genre = " / ".join(gl)
            try:
                year = category['release_date'].split('-')[0]
            except:
                year = ''

            ##########
            # plot = category['overview']
            # if plot == "":
            #     plot = "~ empty ~"
            #
            # videoInfo = {
            #     'mediatype': 'movie',
            #     'title': category['title'],
            #     'genre': genre,
            #     'plot': plot,
            #     'plotoutline': plot,
            #     'year': year,
            #     'rating': category["vote_average"],
            # }
            #
            # list_item.setInfo('video', videoInfo)

            ###

            plot = category['overview']
            if plot == "":
                plot = "~ empty ~"

            # Extract director(s)
            directors = [
                member['name'] for member in category.get('crew', [])
                if member.get('job') == 'Director'
            ]

            # Extract main cast (guest_stars + top-billed actors)
            main_cast = []
            for actor in category.get('guest_stars', [])[:10]:  # Limit to top 10
                main_cast.append({
                    'name': actor.get('name', ''),
                    'role': actor.get('character', ''),
                    'thumbnail': f"https://image.tmdb.org/t/p/original{actor.get('profile_path', '')}" if actor.get(
                        'profile_path') else ''
                })

            # Build extended plot with director info
            extended_plot = plot
            if directors:
                extended_plot += f"\n\nDirectors: {', '.join(directors)}"

            videoInfo = {
                'mediatype': 'movie',
                'title': category['title'],
                'genre': genre,
                'plot': extended_plot,
                'plotoutline': plot,  # Keep original plot for brief view
                'year': year,
                'rating': category["vote_average"],
                'director': directors,
                'cast': main_cast,
                # Additional metadata
                'writer': [
                    member['name'] for member in category.get('crew', [])
                    if member.get('job') == 'Writer'
                ],
                'premiered': category.get('air_date', ''),
                'episode': category.get('episode_number', 0),
                'status': category.get('status', 'Released')
            }

            list_item.setInfo('video', videoInfo)

            dprint("tmdb_movie(): " + str(category))
            dprint("tmdb_movie(): " + str(videoInfo))

            # Set cast thumbnails if available
            if main_cast:
                dprint("tmdb_movie cast(): " + main_cast)
                list_item.setCast(main_cast)

            ###

            try:
                fanart = "https://image.tmdb.org/t/p/w1280" + category["backdrop_path"]
            except:
                fanart = ""
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""

            art = {'thumb': thumb, 'icon': thumb, 'fanart': fanart}

            list_item.setArt(art)
            url = get_url(
                url=_url,
                action='listing_search',
                name=category['title'] + " " + year,
                type=type,
                videoInfo=json.dumps(videoInfo),
                art=json.dumps(art)
            )
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def tmdb_serie_genre(_handle, _url, page, type, id):
    p = int(page)
    html = urlopen(
        'https://api.themoviedb.org/3/discover/' + type + '?api_key=1f0150a5f78d4adc2407911989fdb66c&with_genres=' + id + '&language=' + language + '&page=' + str(
            p)).read()
    res = json.loads(html)
    res["results"].append({"name": "Další"})
    res["results"].append({"name": "Domů"})
    xbmcplugin.setContent(_handle, 'videos')
    for category in res['results']:
        list_item = xbmcgui.ListItem(label=category['name'])
        if category['name'] == "Další":
            url = get_url(_url, action='listing_genre', id=id, type=type, page=str(p + 1))
        elif category['name'] == "Domů":
            url = get_url(_url, action='home', id=id, type=type, page=str(p + 1))
        else:
            gl = []
            for g in category["genre_ids"]:
                gl.append(gid[g])
            genre = " / ".join(gl)
            try:
                year = category['first_air_date'].split('-')[0]
            except:
                year = ''
            list_item.setInfo('video', {'mediatype': 'movie', 'title': category['name'], "plot": category['overview'],
                                        "year": year, 'genre': genre, 'rating': str(category["vote_average"])[:3]})
            try:
                fanart = "https://image.tmdb.org/t/p/w1280" + category["backdrop_path"]
            except:
                fanart = ""
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""
            list_item.setArt({'thumb': thumb, 'icon': thumb, 'fanart': fanart})
            url = get_url(_url, action='listing_seasons', name=category['name'], type=category["id"])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def tmdb_movie_genre(_handle, _url, page, type, id):
    p = int(page)
    html = urlopen(
        'https://api.themoviedb.org/3/discover/' + type + '?api_key=1f0150a5f78d4adc2407911989fdb66c&with_genres=' + id + '&language=' + language + '&page=' + str(
            p)).read()
    res = json.loads(html)
    res["results"].append({"title": "Další"})
    res["results"].append({"title": "Domů"})
    xbmcplugin.setContent(_handle, 'videos')
    for category in res['results']:
        list_item = xbmcgui.ListItem(label=category['title'])
        if category['title'] == "Další":
            url = get_url(_url, action='listing_genre', id=id, type=type, page=str(p + 1))
        elif category['title'] == "Domů":
            url = get_url(_url, action='home', id=id, type=type, page=str(p + 1))
        else:
            gl = []
            for g in category["genre_ids"]:
                gl.append(gid[g])
            genre = " / ".join(gl)
            try:
                year = category['release_date'].split('-')[0]
            except:
                year = ''

            plot = category['overview']
            if plot == "":
                plot = "~ empty ~"

            videoInfo = {
                'mediatype': 'movie',
                'title': category['title'],
                'genre': genre,
                'plot': plot,
                'plotoutline': plot,
                'year': year,
                'rating': category["vote_average"],
            }

            list_item.setInfo('video', videoInfo)

            try:
                fanart = "https://image.tmdb.org/t/p/w1280" + category["backdrop_path"]
            except:
                fanart = ""
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""

            art = {'thumb': thumb, 'icon': thumb, 'fanart': fanart}

            list_item.setArt(art)
            url = get_url(
                url=_url,
                action='listing_search',
                name=category['title'] + " " + year,
                type=type,
                videoInfo=json.dumps(videoInfo),
                art=json.dumps(art)
            )

        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def genres_category(_handle, _url, type):
    html = urlopen(
        'https://api.themoviedb.org/3/genre/' + type + '/list?api_key=1f0150a5f78d4adc2407911989fdb66c&language=' + language).read()
    res = json.loads(html)
    for category in res['genres']:
        list_item = xbmcgui.ListItem(label=category['name'])
        url = get_url(_url, action='listing_genre', id=str(category['id']), type=type, page='1')
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def tmdb_year(_handle, _url, page, type, id):
    if type == 'movie':
        title = 'title'
        rd = 'release_date'
        fy = 'primary_release_year'
    else:
        title = 'name'
        rd = 'first_air_date'
        fy = 'first_air_date_year'
    p = int(page)
    html = urlopen(
        'https://api.themoviedb.org/3/discover/' + type + '?api_key=1f0150a5f78d4adc2407911989fdb66c&' + fy + '=' + id + '&language=' + language + '&page=' + str(
            p)).read()
    res = json.loads(html)
    res["results"].append({title: "Další"})
    xbmcplugin.setContent(_handle, 'videos')
    for category in res['results']:
        list_item = xbmcgui.ListItem(label=category[title])
        if category[title] == "Další":
            url = get_url(_url, action='listing_year', id=id, type=type, page=str(p + 1))
        else:
            gl = []
            for g in category["genre_ids"]:
                gl.append(gid[g])
            genre = " / ".join(gl)
            try:
                year = category[rd].split('-')[0]
            except:
                year = ''

            plot = category['overview']
            if plot == "":
                plot = "~ empty ~"

            dprint("tmdb_year: " + str(category))
            videoInfo = {
                'mediatype': 'movie',
                'title': category.get('name', category.get('title', '#ERROR#')),
                'genre': genre,
                'plot': plot,
                'plotoutline': plot,
                'year': year,
                'rating': category["vote_average"],
            }
            list_item.setInfo('video', videoInfo)

            try:
                fanart = "https://image.tmdb.org/t/p/w1280" + category["backdrop_path"]
            except:
                fanart = ""
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""

            art = {'thumb': thumb, 'icon': thumb, 'fanart': fanart}
            list_item.setArt(art)

            if type == 'movie':
                url = get_url(
                    url=_url,
                    action='listing_search',
                    name=category['title'] + " " + year,
                    type=type,
                    videoInfo=json.dumps(videoInfo),
                    art=json.dumps(art)
                )
            else:
                url = get_url(_url, action='listing_seasons', name=category[title], type=category["id"])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)

def years_category(_handle, _url, type):
    year = datetime.today().year
    YEARS = [year - i for i in range(101)]
    for category in YEARS:
        list_item = xbmcgui.ListItem(label=str(category))
        url = get_url(_url, action='listing_year', type=type, id=str(category), page='1')
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)

def search_tmdb(_handle, _url, name, type):
    if name == "movie":
        stitle = "filmu"
    else:
        stitle = "seriálu"
    kb = xbmc.Keyboard("", 'Zadejte název ' + stitle)
    kb.doModal()
    if not kb.isConfirmed():
        return
    q = kb.getText()
    if q == "":
        return
    url = 'https://api.themoviedb.org/3/search/' + name + '?api_key=1f0150a5f78d4adc2407911989fdb66c&language=' + language + '&page=1&include_adult=false&query=' + quote(
        q)
    html = urlopen(url).read()
    res = json.loads(html)
    xbmcplugin.setContent(_handle, 'videos')

    if name == "movie":
        for category in res['results']:
            list_item = xbmcgui.ListItem(label=category['title'])
            gl = []
            for g in category["genre_ids"]:
                gl.append(gid[g])
            genre = " / ".join(gl)
            try:
                year = category['release_date'].split('-')[0]
            except:
                year = ''
            list_item.setInfo('video', {'mediatype': 'movie', 'title': category['title'], "plot": category['overview'],
                                        "year": year, 'genre': genre, 'rating': str(category["vote_average"])[:3]})
            try:
                fanart = "https://image.tmdb.org/t/p/w1280" + category["backdrop_path"]
            except:
                fanart = ""
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""
            list_item.setArt({'thumb': thumb, 'icon': thumb, 'fanart': fanart})
            url = get_url(_url, action='listing_search', name=category['title'] + " " + year, type=type)
            xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    else:
        for category in res['results']:
            list_item = xbmcgui.ListItem(label=category['name'])
            gl = []
            for g in category["genre_ids"]:
                gl.append(gid[g])
            genre = " / ".join(gl)
            try:
                year = category['first_air_date'].split('-')[0]
            except:
                year = ''
            list_item.setInfo('video', {'mediatype': 'movie', 'title': category['name'], "plot": category['overview'],
                                        "year": year, 'genre': genre, 'rating': str(category["vote_average"])[:3]})
            try:
                fanart = "https://image.tmdb.org/t/p/w1280" + category["backdrop_path"]
            except:
                fanart = ""
            try:
                thumb = "http://image.tmdb.org/t/p/w342" + category["poster_path"]
            except:
                thumb = ""
            list_item.setArt({'thumb': thumb, 'icon': thumb, 'fanart': fanart})
            url = get_url(_url, action='listing_seasons', name=category['name'], type=category["id"])
            xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def movie_category(_handle, _url):
    name_list = [("Nejlépe hodnocené", "listing_tmdb_movie", "1", "top_rated"),
                 ("Oblíbené", "listing_tmdb_movie", "1", "popular"), ("Novinky", "listing_tmdb_movie", "1", "upcoming"),
                 ("Žánry", "listing_genre_category", "movie", ""), ("Rok", "listing_year_category", "movie", ""),
                 ("Hledat", "search_tmdb", "movie", "1")]
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category[0])
        url = get_url(_url, action=category[1], name=category[2], type=category[3])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)


def serie_category(_handle, _url):
    name_list = [("Nejlépe hodnocené", "listing_tmdb_serie", "1", "top_rated"),
                 ("Oblíbené", "listing_tmdb_serie", "1", "popular"),
                 ("Vysílané", "listing_tmdb_serie", "1", "on_the_air"), ("Žánry", "listing_genre_category", "tv", ""),
                 ("Rok", "listing_year_category", "tv", ""), ("Hledat", "search_tmdb", "tv", "1")]
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category[0])
        url = get_url(_url, action=category[1], name=category[2], type=category[3])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    xbmcplugin.endOfDirectory(_handle)
