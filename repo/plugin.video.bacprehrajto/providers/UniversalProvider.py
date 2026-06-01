from typing import Tuple, List, Optional, Type

import xbmcgui

from common import g_is_prehrajto_enabled, g_is_sledujteto_enabled, g_all_sources_disabled, _ADDON_NAME
from model.SearchMeta import SearchMeta
from model.StreamData import StreamData
from model.SubData import SubData
from providers.Prehrajto import Prehrajto
from providers.Sledujteto import Sledujteto
from providers._Provider import _Provider
from utils.utils import dprint


def _run_provider_search(
        provider_label: str,
        provider_cls: Type[_Provider],
        query: str,
) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
    try:
        return provider_cls().search(query)
    except Exception as exc:
        dprint(f'search(): {provider_label} failed: {exc}')
        xbmcgui.Dialog().notification(
            heading=_ADDON_NAME,
            message=f'{provider_label}: {exc}',
            icon=xbmcgui.NOTIFICATION_ERROR,
            time=4000,
            sound=False,
        )
        return [], SearchMeta(pages_scraped=0, cancelled=False, is_complete=True)


class UniversalProvider:

    @staticmethod
    def search(query) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        video_sources: List[xbmcgui.ListItem] = []
        total_pages = 0
        all_complete = True
        any_cancelled = False

        dprint('search(): ' + query)
        if g_is_prehrajto_enabled:
            dprint('search(): P: ' + query)
            items, meta = _run_provider_search('Prehrajto', Prehrajto, query)
            video_sources.extend(items)
            total_pages += meta.pages_scraped
            all_complete = all_complete and meta.is_complete
            any_cancelled = any_cancelled or meta.cancelled
        if g_is_sledujteto_enabled:
            dprint('search(): S: ' + query)
            items, meta = _run_provider_search('Sledujteto', Sledujteto, query)
            video_sources.extend(items)
            total_pages += meta.pages_scraped
            all_complete = all_complete and meta.is_complete
            any_cancelled = any_cancelled or meta.cancelled

        if len(video_sources) == 0 and g_all_sources_disabled:
            xbmcgui.Dialog().notification(
                heading=_ADDON_NAME,
                message=f"Musíte v nastavení povolit alespoň 1 zdroj.",
                icon=xbmcgui.NOTIFICATION_INFO,
                time=4000,
                sound=False
            )

        combined_meta = SearchMeta(
            pages_scraped=total_pages,
            cancelled=any_cancelled,
            is_complete=all_complete,
        )
        return video_sources, combined_meta

    @staticmethod
    def get_streams_data(
            url: str, src_bytes: bytes, show_progress: bool = True, progress_dialog=None,
    ) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
        if 'prehraj' in url:
            return Prehrajto().get_streams_data(url, src_bytes, show_progress, progress_dialog)

        if url.__contains__('sledujteto'):
            return Sledujteto().get_streams_data(url, src_bytes)

        return None, None
