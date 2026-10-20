from typing import Tuple, Optional, List
from urllib.parse import quote

import time as time_module

import xbmcgui
from bs4 import BeautifulSoup
from requests.cookies import RequestsCookieJar

from common import g_prehrajto_max_searched_vids, addon, g_truncate_titles, g_max_duplicities, _ADDON_NAME, icons_path, \
    get_headers, get_prehrajto_base, g_search_page_delay_seconds, g_prehrajto_search_max_pages, g_is_nsfw_enabled, \
    is_possible_nsfw, normalize_prehrajto_url
from providers.browsing_context import remember_provider_page
from model.SearchMeta import SearchMeta
from model.StreamData import StreamData
from model.SubData import SubData
from providers._Provider import _Provider
from providers.prehrajto.auth import ensure_premium, ensure_session_for_search, refresh_premium_from_html
from providers.prehrajto.session import has_usable_auth_locally
from providers.prehrajto.search_prefetch import PagePrefetch, SEARCH_REQUEST_TIMEOUT
from providers.prehrajto.session import get_session
from providers.prehrajto.get_stream_data import get_streams_data
from utils.StrUtils import crop_time, truncate_middle, find_pattern
from utils.search_browse_log import get_search_browse_logger
from providers.prehrajto.list_items import build_prehrajto_list_item
from utils.stream_fake_hint import extract_upload_date_raw_from_listing_card
from utils.utils import dprint


def _index_upload_dates_by_href(soup: BeautifulSoup) -> dict:
    """One pass over links when fake-stream highlight needs upload dates."""
    by_href = {}
    for link_tag in soup.select('a.video--link'):
        href = (link_tag.get('href') or '').strip()
        if not href or href in by_href:
            continue
        upload_raw = extract_upload_date_raw_from_listing_card(link_tag)
        if upload_raw:
            by_href[href] = upload_raw
    return by_href


def _update_search_dialog(
        p_dialog: xbmcgui.DialogProgress,
        p_dialog_step: int,
        items: list,
        line1: str,
        line2: str,
        line3: str,
) -> None:
    pct = max(0, min(100, int(len(items) * p_dialog_step)))
    try:
        p_dialog.update(pct, line1, line2, line3)
    except TypeError:
        p_dialog.update(pct, '\n'.join([line1, line2, line3]))


def _search_status_lines(
        page_loaded: int,
        item_count: int,
        duplicities_set: list,
        dup_counter: int,
        status_line: Optional[str] = None,
) -> Tuple[str, str, str]:
    line1 = f"Strana:                {page_loaded}"
    line2 = (
        f"Video souborů:         {item_count}  |  "
        f"Duplicit: {len(duplicities_set)}  |  "
        f"Dupl. souborů: {dup_counter}"
    )
    line3 = status_line if status_line else " "
    return line1, line2, line3


def _wait_for_next_page(
        p_dialog: xbmcgui.DialogProgress,
        p_dialog_step: int,
        page_loaded: int,
        next_page: int,
        items: list,
        duplicities_set: list,
        dup_counter: int,
        delay_seconds: int,
) -> bool:
    """Wait between pages with countdown on line 3. Returns True if canceled."""
    if delay_seconds <= 0:
        return p_dialog.iscanceled()

    for remaining in range(delay_seconds, 0, -1):
        if p_dialog.iscanceled():
            return True
        _update_search_dialog(
            p_dialog, p_dialog_step, items,
            *_search_status_lines(
                page_loaded, len(items), duplicities_set, dup_counter,
                f"Načtení strany {next_page} za: {remaining} s",
            ),
        )
        end = time_module.time() + 1.0
        while time_module.time() < end:
            if p_dialog.iscanceled():
                return True
            time_module.sleep(0.1)
    return p_dialog.iscanceled()


class Prehrajto(_Provider):

    def search(
            self,
            query,
            need_listing_upload_dates: bool = False,
    ) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        skip_nsfw = not g_is_nsfw_enabled
        if skip_nsfw and is_possible_nsfw(query):
            return [], SearchMeta(pages_scraped=0, cancelled=False, is_complete=True)

        page = 1
        pages_loaded = 0
        items = []
        duplicities_set = []
        duplicities = {}
        dup_counter = 0

        p_dialog_step = max(1, int(100 / g_prehrajto_max_searched_vids))
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create(_ADDON_NAME, "Hledám video soubory...")
        _update_search_dialog(
            p_dialog, p_dialog_step, items,
            *_search_status_lines(page, len(items), duplicities_set, dup_counter),
        )

        if addon.getSetting("email") and len(addon.getSetting("email")) > 0:
            ensure_session_for_search(addon)

        stop_searching = False
        session = get_session()
        prefetch = PagePrefetch()
        site_base = get_prehrajto_base()
        while not (stop_searching or p_dialog.iscanceled()):
            dprint('search(): processing page: ' + str(page))

            if page > 1:
                if _wait_for_next_page(
                        p_dialog, p_dialog_step, pages_loaded, page, items,
                        duplicities_set, dup_counter,
                        g_search_page_delay_seconds,
                ):
                    break

            _update_search_dialog(
                p_dialog, p_dialog_step, items,
                *_search_status_lines(
                    page, len(items), duplicities_set, dup_counter,
                    "Načítám stránku...",
                ),
            )

            t_http = time_module.time()
            prefetched = prefetch.take(page)
            if prefetched is not None:
                html = prefetched
                dprint('search(): using prefetched page ' + str(page))
            else:
                search_url = site_base + '/hledej/' + quote(query) + '?vp-page=' + str(page)
                search_res = session.get(
                    search_url, headers=get_headers(), timeout=SEARCH_REQUEST_TIMEOUT,
                )
                remember_provider_page(search_res.url)
                html = search_res.content
            refresh_premium_from_html(html)
            http_ms = int((time_module.time() - t_http) * 1000)

            items_before = len(items)

            t_parse = time_module.time()
            soup = BeautifulSoup(html, "html.parser")
            title = soup.find_all('h3', attrs={'class': 'video__title'})
            size = soup.find_all('div', attrs={'class': 'video__tag--size'})
            time_tags = soup.find_all('div', attrs={'class': 'video__tag--time'})
            link = soup.find_all('a', {'class': 'video--link'})
            thumb = soup.find_all('img', attrs={'class': 'thumb thumb1'})
            next_button = soup.find_all('a', {'title': 'Zobrazit další'})
            parse_ms = int((time_module.time() - t_parse) * 1000)

            t_upload = time_module.time()
            upload_by_href = (
                _index_upload_dates_by_href(soup) if need_listing_upload_dates else {}
            )
            upload_index_ms = int((time_module.time() - t_upload) * 1000)

            t_listitems = time_module.time()
            for t, s, l, d, th in zip(title, size, link, time_tags, thumb):

                if t is None:
                    dprint('search(): Fuckup..')
                    continue

                t = t.text.strip()
                if skip_nsfw and is_possible_nsfw(t):
                    continue

                s = s.text.strip()
                duration = crop_time(d.text.strip())
                thumbnail = find_pattern(str(th), r'(?:data-)?src="([^\"]+)"') or ''

                pot_dupl_name = (t + " (" + s + " - " + duration + ")")

                duplicitiesVal = duplicities[pot_dupl_name] if pot_dupl_name in duplicities else 0
                if duplicitiesVal is None or duplicitiesVal < g_max_duplicities:
                # if not duplicities_set.__contains__(pot_dupl_name):
                    final_title = t
                    if g_truncate_titles:
                        final_title = truncate_middle(final_title)

                    # videos.append(
                    #     (
                    #         final_title,
                    #         ' (' + s + " - " + m + ')',
                    #         'https://prehraj.to:443' + l['href'],
                    #         t
                    #     )
                    # )

                    href = (l.get('href') or '').strip()
                    items.append(build_prehrajto_list_item(
                        final_title,
                        s,
                        duration,
                        normalize_prehrajto_url(site_base + href, base=site_base),
                        thumbnail,
                        upload_by_href.get(href),
                    ))

                    duplicities[pot_dupl_name] = duplicitiesVal + 1
                else:
                    dup_counter = dup_counter + 1
                    dprint('search(): duplicity: ' + pot_dupl_name + ' x ' + str(dup_counter))
                    duplicities_set.append(pot_dupl_name)

            listitem_ms = int((time_module.time() - t_listitems) * 1000)
            pages_loaded = page
            added_on_page = len(items) - items_before
            dprint(
                f'search(): prehrajto page {pages_loaded}: +{added_on_page} items, '
                f'total={len(items)}, dup_names={len(duplicities_set)}, dup_files={dup_counter} | '
                f'http_ms={http_ms} parse_ms={parse_ms} upload_index_ms={upload_index_ms} '
                f'listitem_ms={listitem_ms}'
            )
            browse_log = get_search_browse_logger()
            if browse_log is not None:
                browse_log.log_prehrajto_page(
                    page=pages_loaded,
                    video_count=len(items),
                    duplicity_names=len(duplicities_set),
                    duplicate_files=dup_counter,
                    added_on_page=added_on_page,
                    http_ms=http_ms,
                    parse_ms=parse_ms,
                    listitem_ms=listitem_ms,
                    upload_index_ms=upload_index_ms,
                )

            _update_search_dialog(
                p_dialog, p_dialog_step, items,
                *_search_status_lines(
                    pages_loaded, len(items), duplicities_set, dup_counter,
                ),
            )

            has_next_page = next_button != []
            target_reached = len(items) >= int(g_prehrajto_max_searched_vids)
            page_added_no_items = len(items) == items_before
            stop_searching = (
                not has_next_page
                or target_reached
                or page >= g_prehrajto_search_max_pages
                or page_added_no_items
            )
            if not stop_searching and not p_dialog.iscanceled():
                prefetch.start(session, query, page + 1)
            else:
                prefetch.cancel()
            page = page + 1

        prefetch.cancel()
        p_dialog.close()

        cancelled = p_dialog.iscanceled()
        is_complete = stop_searching and not cancelled
        return items, SearchMeta(
            pages_scraped=pages_loaded,
            cancelled=cancelled,
            is_complete=is_complete,
        )

    def get_streams_data(
            self, url: str, src_bytes: bytes, show_progress: bool = True,
            progress_dialog=None,
    ) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
        return get_streams_data(src_bytes, show_progress=show_progress, progress_dialog=progress_dialog)

    def get_premium(self) -> Tuple[bool, Optional[RequestsCookieJar]]:
        is_premium, cookies = ensure_premium(addon)
        if not has_usable_auth_locally():
            return is_premium, None
        return is_premium, cookies