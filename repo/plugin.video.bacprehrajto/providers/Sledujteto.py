from typing import List, Tuple, Optional
import xbmcgui
from requests.cookies import RequestsCookieJar

from common import g_is_nsfw_enabled, g_is_sledujteto_enabled, addon, is_sledujteto_auto_login_enabled, is_possible_nsfw
from model.SearchMeta import SearchMeta
from model.StreamData import StreamData
from model.SubData import SubData
from providers._Provider import _Provider
from providers.sledujteto.auth import ensure_login, is_session_valid
from providers.sledujteto.get_stream_data import get_streams_data
from providers.sledujteto.parse_search import fetch_search


class Sledujteto(_Provider):

    def search(self, query) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        skip_nsfw = not g_is_nsfw_enabled
        if skip_nsfw and is_possible_nsfw(query):
            return [], SearchMeta(pages_scraped=0, cancelled=False, is_complete=True)

        if addon.getSetting('sledujteto_email') and g_is_sledujteto_enabled:
            if not is_session_valid() and is_sledujteto_auto_login_enabled():
                ensure_login(addon)

        return fetch_search(query, skip_nsfw=skip_nsfw)

    def get_streams_data(
            self, url: str, src_bytes: bytes,
    ) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
        return get_streams_data(url, src_bytes)

    def get_premium(self) -> Tuple[bool, Optional[RequestsCookieJar]]:
        if not g_is_sledujteto_enabled:
            return False, None
        logged_in, cookies = ensure_login(addon)
        return logged_in, cookies
