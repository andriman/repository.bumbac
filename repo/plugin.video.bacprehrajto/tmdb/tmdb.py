import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen

import xbmc
import xbmcgui
import xbmcplugin

from common import icons_path
from tmdb.tmdb_language import (
    get_tmdb_active_language,
    get_tmdb_api_language,
    get_tmdb_api_language_for,
    get_tmdb_language_menu_label,
    is_tmdb_language_row_enabled,
    parse_tmdb_languages,
)
from utils.listitem_infotag import apply_art, apply_video_info
from utils.utils import apply_context_menu_items, dprint, get_url
from utils.view_mode import end_of_directory, set_pending_content

TMDB_API_KEY = '1f0150a5f78d4adc2407911989fdb66c'
TMDB_IMG = 'https://image.tmdb.org/t/p/'

_gid_fallback = {
    28: "Akční", 12: "Dobrodružný", 16: "Animovaný", 35: "Komedie", 80: "Krimi", 99: "Dokumentární",
    18: "Drama", 10751: "Rodinný", 14: "Fantasy", 36: "Historický", 27: "Horor", 10402: "Hudební",
    9648: "Mysteriózní", 10749: "Romantický", 878: "Vědeckofantastický", 10770: "Televizní film",
    53: "Thriller", 10752: "Válečný", 37: "Western", 10759: "Action & Adventure", 10762: "Kids",
    10763: "News", 10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
    10768: "War & Politics",
}

_genre_cache: Dict[Tuple[str, str], Dict[int, str]] = {}
_imdb_id_cache: Dict[Tuple[str, str], str] = {}
_TITLE_CACHE_WINDOW = 10000


def clear_genre_cache() -> None:
    _genre_cache.clear()


def _tmdb_fetch(path: str, language: Optional[str] = None, **params) -> dict:
    query = dict(params)
    query['api_key'] = TMDB_API_KEY
    query['language'] = language or get_tmdb_api_language()
    url = f'https://api.themoviedb.org/3/{path}?{urlencode(query)}'
    dprint(f'tmdb fetch: {url}')
    return json.loads(urlopen(url).read())


def fetch_localized_title(media: str, tmdb_id: Any, lang_code: str) -> str:
    """Title or show name in one TMDB language. Cached on the home window for this session."""
    media_kind = 'tv' if str(media or '').strip().lower() in ('tv', 'episode', 'tvshow', 'season') else 'movie'
    tmdb_text = str(tmdb_id or '').strip()
    if not tmdb_text:
        return ''
    locale = get_tmdb_api_language_for(lang_code)
    cache_key = f'bac_tmdb_title_{media_kind}_{tmdb_text}_{locale}'
    window = None
    try:
        window = xbmcgui.Window(_TITLE_CACHE_WINDOW)
        cached = (window.getProperty(cache_key) or '').strip()
    except (AttributeError, RuntimeError, TypeError):
        window = None
        cached = ''
    if cached:
        return cached
    try:
        data = _tmdb_fetch(f'{media_kind}/{tmdb_text}', language=locale) or {}
    except Exception as exc:
        dprint(f'fetch_localized_title(): {exc}')
        return ''
    if not isinstance(data, dict):
        data = {}
    if media_kind == 'movie':
        title = str(data.get('title') or data.get('original_title') or '').strip()
    else:
        title = str(data.get('name') or data.get('original_name') or '').strip()
    if title and window is not None:
        try:
            window.setProperty(cache_key, title)
        except (AttributeError, RuntimeError, TypeError):
            pass
    return title


def _add_tmdb_language_row(_handle, _url) -> None:
    if not is_tmdb_language_row_enabled():
        return
    list_item = xbmcgui.ListItem(label=get_tmdb_language_menu_label())
    list_item.setProperty('IsPlayable', 'false')
    icon = icons_path + 'language.png'
    list_item.setArt({'thumb': icon, 'icon': icon, 'poster': icon})
    url = get_url(_url, action='pick_tmdb_language_refresh')
    xbmcplugin.addDirectoryItem(_handle, url, list_item, False)


def _apply_language_search_context(
        list_item,
        plugin_url: str,
        media: str,
        tmdb_id: Any,
        video_info: Dict[str, Any],
        art: Dict[str, str],
        year: str = '',
        season: Any = None,
        episode: Any = None,
) -> None:
    tmdb_text = str(tmdb_id or '').strip()
    if not tmdb_text or media not in ('movie', 'tv'):
        return
    info_json = json.dumps(video_info or {})
    art_json = json.dumps(art or {})
    items = []
    for code in parse_tmdb_languages():
        kwargs = {
            'action': 'search_in_language',
            'lang': code,
            'media': media,
            'tmdb_id': tmdb_text,
            'videoInfo': info_json,
            'art': art_json,
        }
        if year:
            kwargs['year'] = str(year)
        if season is not None and season != '':
            kwargs['season'] = str(season)
        if episode is not None and episode != '':
            kwargs['episode'] = str(episode)
        url = get_url(plugin_url, **kwargs)
        items.append((f'Hledat v {code.upper()}', f'RunPlugin({url})'))
    apply_context_menu_items(list_item, items)


def fetch_imdb_id(tmdb_id: Any, mediatype: str = '') -> str:
    """IMDb tt id for a TMDB movie or TV show. Episode ids use the show id with tv."""
    tmdb_text = str(tmdb_id or '').strip()
    if not tmdb_text:
        return ''
    kind = 'tv' if str(mediatype or '').strip().lower() in ('episode', 'tvshow', 'season', 'tv') else 'movie'
    cache_key = (kind, tmdb_text)
    cached = _imdb_id_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = _tmdb_fetch(f'{kind}/{tmdb_text}/external_ids') or {}
    except Exception as exc:
        dprint(f'fetch_imdb_id(): {exc}')
        return ''
    if not isinstance(data, dict):
        data = {}
    imdb = str(data.get('imdb_id') or '').strip()
    if not imdb.startswith('tt'):
        imdb = ''
    _imdb_id_cache[cache_key] = imdb
    return imdb


def _load_genre_map(media_type: str) -> Dict[int, str]:
    api_lang = get_tmdb_api_language()
    key = (media_type, api_lang)
    if key in _genre_cache:
        return _genre_cache[key]
    res = _tmdb_fetch(f'genre/{media_type}/list') or {}
    genres = res.get('genres') or []
    genre_map = {
        g['id']: g['name']
        for g in genres
        if isinstance(g, dict) and g.get('id') is not None and g.get('name')
    }
    _genre_cache[key] = genre_map
    return genre_map


def get_tmdb_genre_name(genre_id: int, media_type: str) -> str:
    genre_map = _load_genre_map(media_type)
    if genre_id in genre_map:
        return genre_map[genre_id]
    return _gid_fallback.get(genre_id, str(genre_id))


def _genre_string(genre_ids, media_type: str) -> str:
    if not genre_ids:
        return ''
    names = []
    for g in genre_ids:
        if g is None:
            continue
        try:
            names.append(get_tmdb_genre_name(int(g), media_type))
        except (TypeError, ValueError):
            continue
    return ' / '.join(names)


def _img(path: Optional[str], size: str = 'w342') -> str:
    if not path or not isinstance(path, str):
        return ''
    path = path.strip()
    if not path:
        return ''
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return f'{TMDB_IMG}{size}{path}'


def _safe_year(date_value: Any) -> str:
    if date_value is None:
        return ''
    text = str(date_value).strip()
    if not text:
        return ''
    year = text.split('-')[0].strip()
    return year if year.isdigit() else ''


def _safe_rating(value: Any) -> Any:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plot_or_empty(overview: Any) -> str:
    if overview is None:
        return '~ empty ~'
    text = str(overview).strip()
    return text if text else '~ empty ~'


def _unique_ids(*pairs: Tuple[str, Any]) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    for uid_type, uid_val in pairs:
        if uid_val is None or uid_val == '':
            continue
        ids[str(uid_type)] = str(uid_val)
    return ids


def _build_art(
        poster: str = '',
        fanart: str = '',
        landscape: str = '',
        thumb: str = '',
) -> Dict[str, str]:
    art: Dict[str, str] = {}
    poster = (poster or '').strip()
    fanart = (fanart or '').strip()
    landscape = (landscape or '').strip()
    thumb = (thumb or '').strip()

    primary = thumb or poster or landscape
    if primary:
        art['thumb'] = primary
        art['icon'] = primary
    if poster:
        art['poster'] = poster
    elif primary:
        art['poster'] = primary
    if fanart:
        art['fanart'] = fanart
    if landscape:
        art['landscape'] = landscape
    return art


def _set_directory_meta(_handle, content: str, category: str = '') -> None:
    if content:
        try:
            xbmcplugin.setContent(_handle, content)
        except (AttributeError, RuntimeError, TypeError):
            pass
        try:
            set_pending_content(_handle, content)
        except Exception:
            pass
    else:
        try:
            set_pending_content(_handle, '')
        except Exception:
            pass
    if category:
        try:
            xbmcplugin.setPluginCategory(_handle, str(category))
        except (AttributeError, RuntimeError, TypeError):
            pass


def _end(_handle, succeeded: bool = True) -> None:
    end_of_directory(_handle, succeeded=succeeded)


def _item_art_from_category(category: dict, fallback_fanart: str = '') -> Dict[str, str]:
    if not isinstance(category, dict):
        return _build_art(fanart=fallback_fanart)
    poster = _img(category.get('poster_path'), 'w342')
    fanart = _img(category.get('backdrop_path'), 'w1280') or (fallback_fanart or '')
    return _build_art(poster=poster, fanart=fanart)


def _clean_info(info: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in info.items():
        if value is None or value == '':
            continue
        if value == [] or value == {}:
            continue
        cleaned[key] = value
    return cleaned


def tmdb_episodes(_handle, _url, sname, params):
    show_id = params.get('type')
    ses_num = params.get('ses_num')
    if show_id is None or ses_num is None:
        _end(_handle)
        return

    fanart = (params.get('fanart') or '').strip()
    season_poster = (params.get('thumb') or '').strip()
    show_title = fetch_localized_title('tv', show_id, get_tmdb_active_language()) or sname or ''

    dprint(f'sname(): {show_title}')

    res = _tmdb_fetch(f'tv/{show_id}/season/{ses_num}') or {}
    episodes = res.get('episodes') or []
    _set_directory_meta(_handle, 'episodes', show_title)

    for category in episodes:
        if not isinstance(category, dict):
            continue
        ep_name = category.get('name') or 'Neznámo'
        if ep_name in ('Speciály', 'Specials'):
            continue

        ep_num = category.get('episode_number')
        season_num = category.get('season_number', ses_num)
        try:
            ep_label_num = int(ep_num) if ep_num is not None else 0
        except (TypeError, ValueError):
            ep_label_num = 0

        air_date = category.get('air_date') or ''
        air_year = _safe_year(air_date)
        date_label2 = f'Datum vysílání: {air_date}' if air_date else ''

        list_item = xbmcgui.ListItem(
            label=f'E{ep_label_num}: {ep_name}',
            label2=date_label2,
        )

        plot = _plot_or_empty(category.get('overview'))
        directors = [
            member['name'] for member in (category.get('crew') or [])
            if isinstance(member, dict) and member.get('job') == 'Director' and member.get('name')
        ]
        castandrole = [
            (star['name'], star.get('character') or '')
            for star in (category.get('guest_stars') or [])[:20]
            if isinstance(star, dict) and star.get('name')
        ]

        extended_plot = plot
        outline = plot
        if air_date:
            extended_plot = f'Datum vysílání: {air_date}\n\n{extended_plot}'
            outline = f'Datum vysílání: {air_date}\n\n{outline}'
        if directors:
            extended_plot += f"\n\nDirectors: {', '.join(directors)}"

        still = _img(category.get('still_path'), 'w780')
        art = _build_art(
            poster=season_poster or still,
            fanart=fanart,
            landscape=still,
            thumb=still or season_poster,
        )

        # Use the TV show TMDB id for uniqueid (not episode entity id).
        # Skins/helpers (e.g. AZR Next Aired / TMDbHelper) look up tmdb as a show/movie id.
        videoInfo = {
            'mediatype': 'episode',
            'title': ep_name,
            'tvshowtitle': show_title,
            'plot': extended_plot,
            'plotoutline': outline,
            'year': air_year,
            'rating': _safe_rating(category.get('vote_average')),
            'castandrole': castandrole,
            'premiered': air_date,
            'aired': air_date,
            'season': season_num,
            'episode': ep_num,
            'director': directors,
            'uniqueid': _unique_ids(('tmdb', show_id)),
        }
        videoInfo = _clean_info(videoInfo)

        apply_video_info(list_item, videoInfo)
        apply_art(list_item, art)
        try:
            list_item.setProperty('tvshow.tmdb', str(show_id))
        except (AttributeError, RuntimeError, TypeError):
            pass

        try:
            season_z = str(int(season_num)).zfill(2)
        except (TypeError, ValueError):
            season_z = str(season_num or '00').zfill(2)
        ep_z = str(ep_label_num).zfill(2)
        full_name = f'{show_title} S{season_z}E{ep_z}'.strip()
        url = get_url(
            _url,
            action='listing_search',
            name=full_name,
            type=show_id,
            videoInfo=json.dumps(videoInfo),
            art=json.dumps(art),
        )
        _apply_language_search_context(
            list_item, _url, 'tv', show_id, videoInfo, art,
            season=season_num, episode=ep_label_num,
        )
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _add_tmdb_language_row(_handle, _url)
    _end(_handle)


def tmdb_seasons(_handle, _url, name, type):
    if type is None or type == '':
        _end(_handle)
        return

    res = _tmdb_fetch(f'tv/{type}') or {}
    dprint(f'tmdb_seasons(): {res}')
    fanart = _img(res.get('backdrop_path'), 'w1280')
    show_title = name or res.get('name') or ''
    # Prefer path show id; fall back to payload id. Never use season entity ids for tmdb uniqueid.
    show_tmdb_id = type if type not in (None, '') else res.get('id')
    _set_directory_meta(_handle, 'seasons', show_title)

    for category in (res.get('seasons') or []):
        if not isinstance(category, dict):
            continue
        season_name = category.get('name') or ''
        if season_name in ('Speciály', 'Specials'):
            continue

        list_item = xbmcgui.ListItem(label=season_name or 'Neznámo')
        poster = _img(category.get('poster_path'), 'w342')
        art = _build_art(poster=poster, fanart=fanart)
        apply_art(list_item, art)

        plot = _plot_or_empty(category.get('overview'))
        season_num = category.get('season_number')
        videoInfo = {
            'mediatype': 'season',
            'title': season_name,
            'tvshowtitle': show_title,
            'plot': plot,
            'plotoutline': plot,
            'year': _safe_year(category.get('air_date')),
            'rating': _safe_rating(category.get('vote_average')),
            'season': season_num,
            'premiered': category.get('air_date') or '',
            'uniqueid': _unique_ids(('tmdb', show_tmdb_id)),
        }
        videoInfo = _clean_info(videoInfo)
        apply_video_info(list_item, videoInfo)
        if show_tmdb_id is not None and show_tmdb_id != '':
            try:
                list_item.setProperty('tvshow.tmdb', str(show_tmdb_id))
            except (AttributeError, RuntimeError, TypeError):
                pass

        if season_num is None:
            continue
        url = get_url(
            _url,
            action='listing_episodes',
            name=show_title,
            type=type,
            ses_num=str(season_num),
            fanart=fanart,
            thumb=poster,
        )
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)

    _end(_handle)


def tmdb_serie(_handle, _url, page, type):
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    res = _tmdb_fetch(f'tv/{type}', page=str(p)) or {}
    dprint(f'tmdb_serie(): {res}')

    results = list(res.get('results') or [])
    results.append({'name': 'Další'})
    _set_directory_meta(_handle, 'tvshows')

    for category in results:
        if not isinstance(category, dict):
            continue
        title = category.get('name') or ''
        list_item = xbmcgui.ListItem(label=title or 'Neznámo')
        if title == 'Další':
            url = get_url(_url, action='listing_tmdb_serie', name=str(p + 1), type=type)
        else:
            genre = _genre_string(category.get('genre_ids'), 'tv')
            year = _safe_year(category.get('first_air_date'))
            tmdb_id = category.get('id')
            videoInfo = {
                'mediatype': 'tvshow',
                'title': title,
                'tvshowtitle': title,
                'plot': category.get('overview') or '',
                'year': year,
                'genre': genre,
                'rating': _safe_rating(category.get('vote_average')),
                'premiered': category.get('first_air_date') or '',
                'uniqueid': _unique_ids(('tmdb', tmdb_id)),
            }
            videoInfo = _clean_info(videoInfo)
            apply_video_info(list_item, videoInfo)
            art = _item_art_from_category(category)
            apply_art(list_item, art)
            if tmdb_id is None:
                continue
            url = get_url(_url, action='listing_seasons', name=title, type=tmdb_id)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _end(_handle)


def tmdb_movie(_handle, _url, page, type):
    dprint('tmdb_movie()')

    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    res = _tmdb_fetch(f'movie/{type}', page=str(p)) or {}
    results = list(res.get('results') or [])
    results.append({'title': 'Další'})
    results.append({'title': 'Domů'})
    _set_directory_meta(_handle, 'movies')

    for category in results:
        if not isinstance(category, dict):
            continue
        title = category.get('title') or ''
        list_item = xbmcgui.ListItem(label=title or 'Neznámo')
        if title == 'Další':
            url = get_url(_url, action='listing_tmdb_movie', name=str(p + 1), type=type)
        elif title == 'Domů':
            url = get_url(_url, action='home', name=str(p + 1), type=type)
        else:
            genre = _genre_string(category.get('genre_ids'), 'movie')
            year = _safe_year(category.get('release_date'))
            plot = _plot_or_empty(category.get('overview'))

            directors = [
                member['name'] for member in (category.get('crew') or [])
                if isinstance(member, dict) and member.get('job') == 'Director' and member.get('name')
            ]
            writers = [
                member['name'] for member in (category.get('crew') or [])
                if isinstance(member, dict) and member.get('job') == 'Writer' and member.get('name')
            ]

            main_cast = []
            for actor in (category.get('guest_stars') or [])[:10]:
                if not isinstance(actor, dict) or not actor.get('name'):
                    continue
                cast_entry = {
                    'name': actor.get('name', ''),
                    'role': actor.get('character', '') or '',
                }
                profile = actor.get('profile_path')
                if profile:
                    cast_entry['thumbnail'] = _img(profile, 'original')
                main_cast.append(cast_entry)

            extended_plot = plot
            if directors:
                extended_plot += f"\n\nDirectors: {', '.join(directors)}"

            tmdb_id = category.get('id')
            videoInfo = {
                'mediatype': 'movie',
                'title': title,
                'genre': genre,
                'plot': extended_plot,
                'plotoutline': plot,
                'year': year,
                'rating': _safe_rating(category.get('vote_average')),
                'director': directors,
                'cast': main_cast,
                'writer': writers,
                'premiered': category.get('release_date') or '',
                'uniqueid': _unique_ids(('tmdb', tmdb_id)),
            }
            videoInfo = _clean_info(videoInfo)

            apply_video_info(list_item, videoInfo)
            dprint(f'tmdb_movie(): {category}')
            dprint(f'tmdb_movie(): {videoInfo}')

            art = _item_art_from_category(category)
            apply_art(list_item, art)
            url = get_url(
                _url,
                action='listing_search',
                name=f'{title} {year}'.strip(),
                type=type,
                videoInfo=json.dumps(videoInfo),
                art=json.dumps(art),
            )
            _apply_language_search_context(
                list_item, _url, 'movie', tmdb_id, videoInfo, art, year=year,
            )
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _add_tmdb_language_row(_handle, _url)
    _end(_handle)


def tmdb_serie_genre(_handle, _url, page, type, id):
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    res = _tmdb_fetch(f'discover/{type}', with_genres=id, page=str(p)) or {}
    results = list(res.get('results') or [])
    results.append({'name': 'Další'})
    results.append({'name': 'Domů'})
    _set_directory_meta(_handle, 'tvshows')

    for category in results:
        if not isinstance(category, dict):
            continue
        title = category.get('name') or ''
        list_item = xbmcgui.ListItem(label=title or 'Neznámo')
        if title == 'Další':
            url = get_url(_url, action='listing_genre', id=id, type=type, page=str(p + 1))
        elif title == 'Domů':
            url = get_url(_url, action='home', id=id, type=type, page=str(p + 1))
        else:
            genre = _genre_string(category.get('genre_ids'), type or 'tv')
            year = _safe_year(category.get('first_air_date'))
            tmdb_id = category.get('id')
            videoInfo = {
                'mediatype': 'tvshow',
                'title': title,
                'tvshowtitle': title,
                'plot': category.get('overview') or '',
                'year': year,
                'genre': genre,
                'rating': _safe_rating(category.get('vote_average')),
                'premiered': category.get('first_air_date') or '',
                'uniqueid': _unique_ids(('tmdb', tmdb_id)),
            }
            videoInfo = _clean_info(videoInfo)
            apply_video_info(list_item, videoInfo)
            apply_art(list_item, _item_art_from_category(category))
            if tmdb_id is None:
                continue
            url = get_url(_url, action='listing_seasons', name=title, type=tmdb_id)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _end(_handle)


def tmdb_movie_genre(_handle, _url, page, type, id):
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    res = _tmdb_fetch(f'discover/{type}', with_genres=id, page=str(p)) or {}
    results = list(res.get('results') or [])
    results.append({'title': 'Další'})
    results.append({'title': 'Domů'})
    _set_directory_meta(_handle, 'movies')

    for category in results:
        if not isinstance(category, dict):
            continue
        title = category.get('title') or ''
        list_item = xbmcgui.ListItem(label=title or 'Neznámo')
        if title == 'Další':
            url = get_url(_url, action='listing_genre', id=id, type=type, page=str(p + 1))
        elif title == 'Domů':
            url = get_url(_url, action='home', id=id, type=type, page=str(p + 1))
        else:
            genre = _genre_string(category.get('genre_ids'), type or 'movie')
            year = _safe_year(category.get('release_date'))
            plot = _plot_or_empty(category.get('overview'))
            tmdb_id = category.get('id')

            videoInfo = {
                'mediatype': 'movie',
                'title': title,
                'genre': genre,
                'plot': plot,
                'plotoutline': plot,
                'year': year,
                'rating': _safe_rating(category.get('vote_average')),
                'premiered': category.get('release_date') or '',
                'uniqueid': _unique_ids(('tmdb', tmdb_id)),
            }
            videoInfo = _clean_info(videoInfo)
            apply_video_info(list_item, videoInfo)

            art = _item_art_from_category(category)
            apply_art(list_item, art)
            url = get_url(
                _url,
                action='listing_search',
                name=f'{title} {year}'.strip(),
                type=type,
                videoInfo=json.dumps(videoInfo),
                art=json.dumps(art),
            )
            _apply_language_search_context(
                list_item, _url, 'movie', tmdb_id, videoInfo, art, year=year,
            )

        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _add_tmdb_language_row(_handle, _url)
    _end(_handle)


def genres_category(_handle, _url, type):
    res = _tmdb_fetch(f'genre/{type}/list') or {}
    _set_directory_meta(_handle, '')
    for category in (res.get('genres') or []):
        if not isinstance(category, dict):
            continue
        name = category.get('name')
        genre_id = category.get('id')
        if not name or genre_id is None:
            continue
        list_item = xbmcgui.ListItem(label=name)
        url = get_url(_url, action='listing_genre', id=str(genre_id), type=type, page='1')
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _end(_handle)


def tmdb_year(_handle, _url, page, type, id):
    if type == 'movie':
        title_key = 'title'
        rd = 'release_date'
        fy = 'primary_release_year'
        content = 'movies'
        mediatype = 'movie'
    else:
        title_key = 'name'
        rd = 'first_air_date'
        fy = 'first_air_date_year'
        content = 'tvshows'
        mediatype = 'tvshow'

    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    res = _tmdb_fetch(f'discover/{type}', **{fy: id}, page=str(p)) or {}
    results = list(res.get('results') or [])
    results.append({title_key: 'Další'})
    _set_directory_meta(_handle, content)

    for category in results:
        if not isinstance(category, dict):
            continue
        title = category.get(title_key) or ''
        list_item = xbmcgui.ListItem(label=title or 'Neznámo')
        if title == 'Další':
            url = get_url(_url, action='listing_year', id=id, type=type, page=str(p + 1))
        else:
            genre = _genre_string(category.get('genre_ids'), type or 'movie')
            year = _safe_year(category.get(rd))
            plot = _plot_or_empty(category.get('overview'))
            tmdb_id = category.get('id')

            dprint(f'tmdb_year: {category}')
            videoInfo = {
                'mediatype': mediatype,
                'title': title,
                'plot': plot,
                'plotoutline': plot,
                'year': year,
                'genre': genre,
                'rating': _safe_rating(category.get('vote_average')),
                'premiered': category.get(rd) or '',
                'uniqueid': _unique_ids(('tmdb', tmdb_id)),
            }
            if mediatype == 'tvshow':
                videoInfo['tvshowtitle'] = title
            videoInfo = _clean_info(videoInfo)
            apply_video_info(list_item, videoInfo)

            art = _item_art_from_category(category)
            apply_art(list_item, art)

            if type == 'movie':
                url = get_url(
                    _url,
                    action='listing_search',
                    name=f'{title} {year}'.strip(),
                    type=type,
                    videoInfo=json.dumps(videoInfo),
                    art=json.dumps(art),
                )
                _apply_language_search_context(
                    list_item, _url, 'movie', tmdb_id, videoInfo, art, year=year,
                )
            else:
                if tmdb_id is None:
                    continue
                url = get_url(_url, action='listing_seasons', name=title, type=tmdb_id)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    if type == 'movie':
        _add_tmdb_language_row(_handle, _url)
    _end(_handle)


def years_category(_handle, _url, type):
    year = datetime.today().year
    YEARS = [year - i for i in range(101)]
    _set_directory_meta(_handle, '')
    for category in YEARS:
        list_item = xbmcgui.ListItem(label=str(category))
        url = get_url(_url, action='listing_year', type=type, id=str(category), page='1')
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _end(_handle)


def search_tmdb(_handle, _url, name, type):
    if name == 'movie':
        stitle = 'filmu'
        content = 'movies'
        mediatype = 'movie'
    else:
        stitle = 'seriálu'
        content = 'tvshows'
        mediatype = 'tvshow'

    kb = xbmc.Keyboard('', 'Zadejte název ' + stitle)
    kb.doModal()
    if not kb.isConfirmed():
        return
    q = kb.getText()
    if not q:
        return

    res = _tmdb_fetch(f'search/{name}', page='1', include_adult='false', query=q) or {}
    _set_directory_meta(_handle, content)
    media_type = name if name in ('movie', 'tv') else 'movie'

    for category in (res.get('results') or []):
        if not isinstance(category, dict):
            continue

        if name == 'movie':
            title = category.get('title') or ''
            year = _safe_year(category.get('release_date'))
            premiered = category.get('release_date') or ''
        else:
            title = category.get('name') or ''
            year = _safe_year(category.get('first_air_date'))
            premiered = category.get('first_air_date') or ''

        if not title:
            continue

        list_item = xbmcgui.ListItem(label=title)
        genre = _genre_string(category.get('genre_ids'), media_type)
        tmdb_id = category.get('id')
        videoInfo = {
            'mediatype': mediatype,
            'title': title,
            'plot': category.get('overview') or '',
            'year': year,
            'genre': genre,
            'rating': _safe_rating(category.get('vote_average')),
            'premiered': premiered,
            'uniqueid': _unique_ids(('tmdb', tmdb_id)),
        }
        if mediatype == 'tvshow':
            videoInfo['tvshowtitle'] = title
        videoInfo = _clean_info(videoInfo)
        apply_video_info(list_item, videoInfo)

        art = _item_art_from_category(category)
        apply_art(list_item, art)

        if name == 'movie':
            url = get_url(
                _url,
                action='listing_search',
                name=f'{title} {year}'.strip(),
                type=type,
                videoInfo=json.dumps(videoInfo),
                art=json.dumps(art),
            )
            _apply_language_search_context(
                list_item, _url, 'movie', tmdb_id, videoInfo, art, year=year,
            )
        else:
            if tmdb_id is None:
                continue
            url = get_url(_url, action='listing_seasons', name=title, type=tmdb_id)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    if name == 'movie':
        _add_tmdb_language_row(_handle, _url)
    _end(_handle)


def movie_category(_handle, _url):
    name_list = [
        ('Nejlépe hodnocené', 'listing_tmdb_movie', '1', 'top_rated'),
        ('Oblíbené', 'listing_tmdb_movie', '1', 'popular'),
        ('Novinky', 'listing_tmdb_movie', '1', 'upcoming'),
        ('Žánry', 'listing_genre_category', 'movie', ''),
        ('Rok', 'listing_year_category', 'movie', ''),
        ('Hledat', 'search_tmdb', 'movie', '1'),
    ]
    _set_directory_meta(_handle, '')
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category[0])
        url = get_url(_url, action=category[1], name=category[2], type=category[3])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _end(_handle)


def serie_category(_handle, _url):
    name_list = [
        ('Nejlépe hodnocené', 'listing_tmdb_serie', '1', 'top_rated'),
        ('Oblíbené', 'listing_tmdb_serie', '1', 'popular'),
        ('Vysílané', 'listing_tmdb_serie', '1', 'on_the_air'),
        ('Žánry', 'listing_genre_category', 'tv', ''),
        ('Rok', 'listing_year_category', 'tv', ''),
        ('Hledat', 'search_tmdb', 'tv', '1'),
    ]
    _set_directory_meta(_handle, '')
    for category in name_list:
        list_item = xbmcgui.ListItem(label=category[0])
        url = get_url(_url, action=category[1], name=category[2], type=category[3])
        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)
    _end(_handle)
