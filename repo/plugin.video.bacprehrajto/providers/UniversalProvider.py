from typing import Tuple, List, Optional, Type

import xbmcgui

from common import (
    g_is_prehrajto_enabled, g_is_sledujteto_enabled, g_is_hellspy_enabled, g_all_sources_disabled, _ADDON_NAME,
)
from model.SearchMeta import SearchMeta
from model.StreamData import StreamData
from model.SubData import SubData
from providers.HellSpy import HellSpy
from providers.Prehrajto import Prehrajto
from providers.Sledujteto import Sledujteto
from providers._Provider import _Provider
from utils.search_browse_log import begin_search_browse_log, end_search_browse_log
from utils.search_source_items import (
    PROVIDER_ID_HELLSPY,
    PROVIDER_ID_PREHRAJTO,
    PROVIDER_ID_SLEDUJTETO,
    make_source_no_results_item,
    tag_search_provider,
)
from utils.utils import dprint


def _run_provider_search(
        provider_label: str,
        provider_cls: Type[_Provider],
        query: str,
        need_listing_upload_dates: bool = False,
) -> Tuple[List[xbmcgui.ListItem], SearchMeta, bool]:
    try:
        if provider_cls is Prehrajto:
            items, meta = provider_cls().search(
                query, need_listing_upload_dates=need_listing_upload_dates,
            )
        else:
            items, meta = provider_cls().search(query)
        return items, meta, False
    except Exception as exc:
        dprint(f'search(): {provider_label} failed: {exc}')
        xbmcgui.Dialog().notification(
            heading=_ADDON_NAME,
            message=f'{provider_label}: {exc}',
            icon=xbmcgui.NOTIFICATION_ERROR,
            time=4000,
            sound=False,
        )
        return [], SearchMeta(pages_scraped=0, cancelled=False, is_complete=True), True


def _append_provider_results(
        video_sources: List[xbmcgui.ListItem],
        provider_id: str,
        items: List[xbmcgui.ListItem],
        meta: SearchMeta,
        failed: bool,
) -> Tuple[int, bool, bool]:
    """Merge provider items; add a gray placeholder when search succeeded but empty."""
    pages = meta.pages_scraped
    complete = meta.is_complete
    cancelled = meta.cancelled
    if failed:
        return pages, complete, cancelled
    if len(items) == 0:
        placeholder = make_source_no_results_item(provider_id)
        tag_search_provider(placeholder, provider_id)
        video_sources.append(placeholder)
    else:
        for item in items:
            tag_search_provider(item, provider_id)
        video_sources.extend(items)
    return pages, complete, cancelled


class UniversalProvider:

    @staticmethod
    def search(
            query,
            need_listing_upload_dates: bool = False,
    ) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        dprint('search(): ' + query)
        begin_search_browse_log(query)
        try:
            return UniversalProvider._search_impl(query, need_listing_upload_dates)
        finally:
            end_search_browse_log()

    @staticmethod
    def _search_impl(
            query,
            need_listing_upload_dates: bool = False,
    ) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        video_sources: List[xbmcgui.ListItem] = []
        total_pages = 0
        all_complete = True
        any_cancelled = False

        if g_is_prehrajto_enabled:
            dprint('search(): P: ' + query)
            items, meta, failed = _run_provider_search(
                'Prehrajto', Prehrajto, query, need_listing_upload_dates,
            )
            pages, complete, cancelled = _append_provider_results(
                video_sources, PROVIDER_ID_PREHRAJTO, items, meta, failed,
            )
            total_pages += pages
            all_complete = all_complete and complete
            any_cancelled = any_cancelled or cancelled
        if g_is_sledujteto_enabled:
            dprint('search(): S: ' + query)
            items, meta, failed = _run_provider_search('Sledujteto', Sledujteto, query)
            pages, complete, cancelled = _append_provider_results(
                video_sources, PROVIDER_ID_SLEDUJTETO, items, meta, failed,
            )
            total_pages += pages
            all_complete = all_complete and complete
            any_cancelled = any_cancelled or cancelled
        if g_is_hellspy_enabled:
            dprint('search(): H: ' + query)
            items, meta, failed = _run_provider_search('HellSpy', HellSpy, query)
            pages, complete, cancelled = _append_provider_results(
                video_sources, PROVIDER_ID_HELLSPY, items, meta, failed,
            )
            total_pages += pages
            all_complete = all_complete and complete
            any_cancelled = any_cancelled or cancelled

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

        if 'hellspy' in url.lower():
            return HellSpy().get_streams_data(url, src_bytes)

        return None, None
