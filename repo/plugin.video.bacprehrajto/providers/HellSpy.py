from typing import List, Optional, Tuple

import xbmcgui
from requests.cookies import RequestsCookieJar

from common import g_is_nsfw_enabled, is_possible_nsfw
from model.SearchMeta import SearchMeta
from model.StreamData import StreamData
from model.SubData import SubData
from providers._Provider import _Provider
from providers.hellspy.get_stream_data import get_streams_data
from providers.hellspy.parse_search import fetch_search


class HellSpy(_Provider):

    def search(self, query) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        skip_nsfw = not g_is_nsfw_enabled
        if skip_nsfw and is_possible_nsfw(query):
            return [], SearchMeta(pages_scraped=0, cancelled=False, is_complete=True)
        return fetch_search(query, skip_nsfw=skip_nsfw)

    def get_streams_data(
            self, url: str, src_bytes: bytes,
    ) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
        return get_streams_data(url, src_bytes)

    def get_premium(self) -> Tuple[bool, Optional[RequestsCookieJar]]:
        return False, None
