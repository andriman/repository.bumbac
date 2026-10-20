from typing import List, Optional

import xbmcgui

from common import g_quality_selector
from model.QS import QS
from model.StreamData import StreamData
from utils.listitem_infotag import apply_video_stream_info
from utils.utils import get_quality_icon


def select_stream_auto(streams: List[StreamData]) -> Optional[StreamData]:
    if not streams:
        return None
    if len(streams) == 1:
        return streams[0]
    if g_quality_selector == QS.Max:
        for stream in streams:
            if stream.is_premium:
                return stream
        return streams[-1]
    return streams[0]


def open_stream_selector(streams: List[StreamData]) -> Optional[StreamData]:
    list_items = []
    for stream in streams:
        label2 = stream.label2 or ''
        if getattr(stream, 'upload_date', None) and not label2.strip():
            label2 = f"Nahráno: {stream.upload_date}"
        item = xbmcgui.ListItem(label=stream.label, label2=label2)
        if stream.duration:
            apply_video_stream_info(item, {
                'mediatype': 'video',
                'duration': stream.duration,
            })
        icon = get_quality_icon(stream.quality)
        item.setArt({'thumb': icon})
        list_items.append(item)

    selected = xbmcgui.Dialog().select(
        heading="Vybrat kvalitu",
        list=list_items,
        useDetails=True,
    )
    if selected == -1:
        return None
    return streams[selected]


def resolve_stream(
        streams: List[StreamData],
        stream_index: Optional[int] = None,
        stream_path: str = '',
) -> Optional[StreamData]:
    if stream_index is not None and 0 <= stream_index < len(streams):
        return streams[stream_index]
    if stream_path:
        for stream in streams:
            if stream.path == stream_path:
                return stream
    return select_stream_auto(streams)


def pick_stream(streams: List[StreamData]) -> Optional[StreamData]:
    if not streams:
        return None
    if len(streams) == 1:
        return streams[0]
    return open_stream_selector(streams)
