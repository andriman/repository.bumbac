from typing import Optional

import xbmcgui

from utils.listitem_infotag import attach_listing_stream_info_property
from providers.prehrajto.duration_to_seconds import duration_to_seconds
from utils.stream_fake_hint import LISTING_THUMB_PROP, LISTING_UPLOAD_PROP
from utils.utils import size_str_to_bytes


def build_prehrajto_list_item(
        final_title: str,
        size_str: str,
        duration_str: str,
        page_path: str,
        thumbnail: str,
        upload_raw: Optional[str] = None,
) -> xbmcgui.ListItem:
    """Minimal ListItem for search/account listings — art/stream at directory render."""
    list_item = xbmcgui.ListItem(
        label=final_title,
        label2=f'{size_str} - {duration_str}',
        path=page_path,
        offscreen=True,
    )
    stream_info = {'mediatype': 'video'}
    if duration_str:
        try:
            stream_info['duration'] = duration_to_seconds(duration_str)
        except ValueError:
            pass
    if size_str:
        try:
            stream_info['size'] = size_str_to_bytes(size_str)
        except (ValueError, TypeError):
            pass
    attach_listing_stream_info_property(list_item, stream_info)
    if thumbnail:
        list_item.setProperty(LISTING_THUMB_PROP, thumbnail)
    if upload_raw:
        list_item.setProperty(LISTING_UPLOAD_PROP, upload_raw)
    list_item.setProperty('IsPlayable', 'true')
    return list_item
