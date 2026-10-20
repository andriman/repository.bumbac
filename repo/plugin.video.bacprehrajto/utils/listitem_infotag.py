"""InfoTagVideo helpers with fallback to deprecated ListItem.setInfo / addStreamInfo."""
import json
from typing import Any, Dict, List, Optional

import xbmcgui

LISTING_STREAM_INFO_PROP = 'PrehrajListingStreamInfo'
IMDB_ID_PROP = 'imdb_id'
PLAYBACK_INFO_PROP = 'PrehrajPlaybackInfo'
_PLAYBACK_INFO_KEYS = (
    'title', 'tvshowtitle', 'year', 'premiered', 'mediatype', 'season', 'episode', 'imdbnumber',
    'plot', 'plotoutline', 'rating',
)


def _video_tag(list_item: xbmcgui.ListItem):
    try:
        return list_item.getVideoInfoTag()
    except (AttributeError, RuntimeError):
        return None


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and v != '']
    if value is None or value == '':
        return []
    return [str(value)]


def _normalize_cast(value: Any) -> List[Dict[str, Any]]:
    cast_list: List[Dict[str, Any]] = []
    if not value:
        return cast_list
    if not isinstance(value, list):
        return cast_list
    for entry in value:
        if isinstance(entry, dict):
            name = entry.get('name')
            if not name:
                continue
            item = {'name': str(name)}
            role = entry.get('role') or entry.get('character') or ''
            if role:
                item['role'] = str(role)
            if entry.get('thumbnail'):
                item['thumbnail'] = str(entry['thumbnail'])
            if entry.get('order') is not None:
                try:
                    item['order'] = int(entry['order'])
                except (TypeError, ValueError):
                    pass
            cast_list.append(item)
        elif isinstance(entry, (list, tuple)) and len(entry) >= 1:
            name = entry[0]
            if not name:
                continue
            role = entry[1] if len(entry) > 1 else ''
            cast_list.append({'name': str(name), 'role': str(role or '')})
        elif entry:
            cast_list.append({'name': str(entry), 'role': ''})
    return cast_list


def apply_art(list_item: xbmcgui.ListItem, art: Optional[Dict[str, Any]]) -> None:
    """Apply artwork, omitting empty values and ensuring poster falls back from thumb."""
    if not list_item or not art:
        return
    cleaned: Dict[str, str] = {}
    for key, value in art.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    if not cleaned:
        return
    if 'poster' not in cleaned and cleaned.get('thumb'):
        cleaned['poster'] = cleaned['thumb']
    try:
        list_item.setArt(cleaned)
    except (AttributeError, RuntimeError, TypeError):
        pass


def apply_video_stream_info(list_item: xbmcgui.ListItem, stream_info: Optional[Dict[str, Any]]) -> None:
    if not stream_info:
        return

    tag = _video_tag(list_item)
    if tag is not None:
        try:
            if hasattr(tag, 'addVideoStream'):
                payload = {
                    k: v for k, v in stream_info.items()
                    if k != 'mediatype' and v is not None and v != ''
                }
                if payload:
                    tag.addVideoStream(dict(payload))
                mediatype = stream_info.get('mediatype')
                if mediatype and hasattr(tag, 'setMediaType'):
                    tag.setMediaType(str(mediatype))
                return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        try:
            mediatype = stream_info.get('mediatype')
            if mediatype is not None and mediatype != '' and hasattr(tag, 'setMediaType'):
                tag.setMediaType(str(mediatype))

            duration = stream_info.get('duration')
            if duration is not None and duration != '' and hasattr(tag, 'setDuration'):
                try:
                    tag.setDuration(int(duration))
                except (TypeError, ValueError):
                    pass

            size = stream_info.get('size')
            if size is not None and size != '':
                try:
                    size_int = int(size)
                except (TypeError, ValueError):
                    size_int = None
                if size_int is not None:
                    if hasattr(tag, 'setFileSize'):
                        tag.setFileSize(size_int)
                    elif hasattr(tag, 'setSize'):
                        tag.setSize(size_int)

            width = stream_info.get('width')
            height = stream_info.get('height')
            if width is not None and width != '' and hasattr(tag, 'setVideoWidth'):
                try:
                    tag.setVideoWidth(int(width))
                except (TypeError, ValueError):
                    pass
            if height is not None and height != '' and hasattr(tag, 'setVideoHeight'):
                try:
                    tag.setVideoHeight(int(height))
                except (TypeError, ValueError):
                    pass

            codec = stream_info.get('codec')
            if codec is not None and codec != '' and hasattr(tag, 'setVideoCodec'):
                tag.setVideoCodec(str(codec))

            aspect = stream_info.get('aspect')
            if aspect is not None and aspect != '' and hasattr(tag, 'setVideoAspect'):
                try:
                    tag.setVideoAspect(float(aspect))
                except (TypeError, ValueError):
                    pass
            return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    try:
        list_item.addStreamInfo('video', stream_info)
    except (AttributeError, RuntimeError, TypeError):
        pass


def apply_audio_stream_info(list_item: xbmcgui.ListItem, stream_info: Optional[Dict[str, Any]]) -> None:
    if not stream_info:
        return

    tag = _video_tag(list_item)
    if tag is not None:
        try:
            if hasattr(tag, 'addAudioStream'):
                tag.addAudioStream(dict(stream_info))
                return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    try:
        list_item.addStreamInfo('audio', stream_info)
    except (AttributeError, RuntimeError, TypeError):
        pass


def _imdb_from_info(info: Dict[str, Any]) -> str:
    unique = info.get('uniqueid')
    if isinstance(unique, dict):
        imdb = str(unique.get('imdb') or '').strip()
        if imdb.startswith('tt'):
            return imdb
    elif isinstance(unique, str):
        imdb = unique.strip()
        if imdb.startswith('tt'):
            return imdb
    imdb = str(info.get('imdbnumber') or '').strip()
    if imdb.startswith('tt'):
        return imdb
    return ''


def _remember_imdb_id(list_item: xbmcgui.ListItem, info: Dict[str, Any]) -> None:
    """Keep ids on properties. Plugin list items sometimes drop the info tag on play."""
    imdb = _imdb_from_info(info)
    compact: Dict[str, Any] = {}
    for key in _PLAYBACK_INFO_KEYS:
        value = info.get(key)
        if value is None or value == '':
            continue
        compact[key] = value
    unique = info.get('uniqueid')
    if isinstance(unique, dict):
        stored_unique = {}
        for uid_type in ('imdb', 'tmdb'):
            uid_val = unique.get(uid_type)
            if uid_val is None or uid_val == '':
                continue
            stored_unique[uid_type] = str(uid_val)
        if stored_unique:
            compact['uniqueid'] = stored_unique
    if imdb:
        compact['imdbnumber'] = imdb
    try:
        if imdb:
            list_item.setProperty(IMDB_ID_PROP, imdb)
        if compact:
            list_item.setProperty(PLAYBACK_INFO_PROP, json.dumps(compact))
    except (AttributeError, RuntimeError, TypeError):
        pass


def apply_video_info(list_item: xbmcgui.ListItem, info: Optional[Dict[str, Any]]) -> None:
    if not info or not list_item:
        return

    _remember_imdb_id(list_item, info)
    tag = _video_tag(list_item)
    if tag is not None:
        try:
            _SETTERS = (
                ('title', 'setTitle'),
                ('tvshowtitle', 'setTvShowTitle'),
                ('plot', 'setPlot'),
                ('plotoutline', 'setPlotOutline'),
                ('year', 'setYear'),
                ('premiered', 'setPremiered'),
                ('aired', 'setFirstAired'),
                ('firstaired', 'setFirstAired'),
                ('genre', 'setGenres'),
                ('rating', 'setRating'),
                ('imdbnumber', 'setIMDBNumber'),
                ('uniqueid', 'setUniqueID'),
                ('mediatype', 'setMediaType'),
                ('trailer', 'setTrailer'),
                ('duration', 'setDuration'),
                ('cast', 'setCast'),
                ('castandrole', 'setCast'),
                ('director', 'setDirectors'),
                ('writer', 'setWriters'),
                ('studio', 'setStudios'),
                ('country', 'setCountries'),
                ('tagline', 'setTagLine'),
                ('status', 'setTvShowStatus'),
                ('season', 'setSeason'),
                ('episode', 'setEpisode'),
            )
            applied = False
            for key, method_name in _SETTERS:
                if key not in info:
                    continue
                value = info.get(key)
                if value is None or value == '':
                    continue
                method = getattr(tag, method_name, None)
                if method is None:
                    continue
                try:
                    if key == 'genre':
                        genres = _as_str_list(value)
                        if not genres:
                            continue
                        method(genres)
                    elif key == 'year':
                        try:
                            year_str = str(value).split('-')[0].strip()
                            if year_str:
                                method(int(year_str))
                        except (ValueError, TypeError):
                            pass
                    elif key in ('duration', 'season', 'episode'):
                        try:
                            method(int(value))
                        except (ValueError, TypeError):
                            pass
                    elif key == 'rating':
                        try:
                            method(float(value))
                        except (ValueError, TypeError):
                            pass
                    elif key in ('cast', 'castandrole'):
                        cast_list = _normalize_cast(value)
                        if cast_list:
                            method(cast_list)
                    elif key in ('director', 'writer', 'studio', 'country'):
                        values = _as_str_list(value)
                        if values:
                            method(values)
                    elif key == 'uniqueid':
                        if isinstance(value, dict):
                            pairs = []
                            for uid_type, uid_val in value.items():
                                if uid_val is None or uid_val == '':
                                    continue
                                pairs.append((str(uid_type), str(uid_val)))
                            has_imdb = any(uid_type == 'imdb' for uid_type, _ in pairs)
                            imdb_val = ''
                            for uid_type, uid_val in pairs:
                                # IMDb is the default id. TMDB stays typed, and is the
                                # default only when no IMDb id is present.
                                is_default = uid_type == 'imdb' or not has_imdb
                                if uid_type == 'imdb':
                                    imdb_val = uid_val
                                try:
                                    method(uid_val, uid_type, is_default)
                                except TypeError:
                                    try:
                                        method(uid_val, uid_type)
                                    except TypeError:
                                        method(uid_val)
                            if imdb_val:
                                set_imdb = getattr(tag, 'setIMDBNumber', None)
                                if set_imdb is not None:
                                    try:
                                        set_imdb(imdb_val)
                                    except (AttributeError, RuntimeError, TypeError, ValueError):
                                        pass
                        else:
                            method(str(value))
                    else:
                        method(str(value))
                    applied = True
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    continue
            if applied:
                return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    try:
        fallback = {}
        for key, value in info.items():
            if value is None or value == '':
                continue
            if key == 'uniqueid' and isinstance(value, dict):
                # setInfo takes one id. Prefer the tt id so legacy IMDBNumber is IMDb.
                imdb = value.get('imdb')
                uid = imdb or value.get('tmdb') or next(iter(value.values()), None)
                if imdb:
                    fallback['imdbnumber'] = str(imdb)
                if uid:
                    fallback['uniqueid'] = str(uid)
                continue
            if key == 'castandrole':
                fallback['castandrole'] = value
                continue
            fallback[key] = value
        if fallback:
            list_item.setInfo('video', fallback)
    except (AttributeError, RuntimeError, TypeError):
        pass


def attach_listing_stream_info_property(list_item: xbmcgui.ListItem, stream_info: Dict[str, Any]) -> None:
    """Store stream metadata for deferred apply at directory render (fast scrape)."""
    if stream_info:
        list_item.setProperty(LISTING_STREAM_INFO_PROP, json.dumps(stream_info))


def stream_info_from_listing_property(list_item: xbmcgui.ListItem) -> Optional[Dict[str, Any]]:
    raw = (list_item.getProperty(LISTING_STREAM_INFO_PROP) or '').strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def apply_deferred_listing_stream_info(list_item: xbmcgui.ListItem) -> None:
    """Apply stream metadata stored on the item during scrape (property only)."""
    stream_info = stream_info_from_listing_property(list_item)
    if stream_info:
        apply_video_stream_info(list_item, stream_info)
