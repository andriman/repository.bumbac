from typing import Tuple, Optional, List
from urllib.parse import quote

import time as time_module

import xbmcgui
from bs4 import BeautifulSoup
from requests.cookies import RequestsCookieJar

from common import g_max_searched_vids, addon, g_truncate_titles, g_max_duplicities, _ADDON_NAME, icons_path, \
    get_headers, get_prehrajto_base, g_search_page_delay_seconds, g_search_max_pages, g_is_nsfw_enabled, \
    is_possible_nsfw, normalize_prehrajto_url
from providers.browsing_context import remember_provider_page
from model.SearchMeta import SearchMeta
from utils.stream_fake_hint import LISTING_UPLOAD_PROP, extract_upload_date_raw_from_listing_card
from model.StreamData import StreamData
from model.SubData import SubData
from providers._Provider import _Provider
from providers.prehrajto.auth import ensure_premium, is_session_valid
from providers.prehrajto.search_prefetch import PagePrefetch, SEARCH_REQUEST_TIMEOUT
from providers.prehrajto.session import get_session
from providers.prehrajto.duration_to_seconds import duration_to_seconds
from providers.prehrajto.get_stream_data import get_streams_data
from utils.StrUtils import crop_time, truncate_middle, find_pattern
from utils.utils import dprint, size_str_to_bytes


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

    def search(self, query) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        skip_nsfw = not g_is_nsfw_enabled
        if skip_nsfw and is_possible_nsfw(query):
            return [], SearchMeta(pages_scraped=0, cancelled=False, is_complete=True)

        page = 1
        pages_loaded = 0
        items = []
        duplicities_set = []
        duplicities = {}
        dup_counter = 0

        p_dialog_step = max(1, int(100 / g_max_searched_vids))
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create(_ADDON_NAME, "Hledám video soubory...")
        _update_search_dialog(
            p_dialog, p_dialog_step, items,
            *_search_status_lines(page, len(items), duplicities_set, dup_counter),
        )

        if addon.getSetting("email") and len(addon.getSetting("email")) > 0:
            from common import g_is_prehrajto_enabled, is_prehrajto_auto_login_enabled
            if g_is_prehrajto_enabled and not is_session_valid() and is_prehrajto_auto_login_enabled():
                ensure_premium(addon)

        stop_searching = False
        session = get_session()
        prefetch = PagePrefetch()
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

            prefetched = prefetch.take(page)
            if prefetched is not None:
                html = prefetched
                dprint('search(): using prefetched page ' + str(page))
            else:
                search_url = get_prehrajto_base() + '/hledej/' + quote(query) + '?vp-page=' + str(page)
                search_res = session.get(
                    search_url, headers=get_headers(), timeout=SEARCH_REQUEST_TIMEOUT,
                )
                remember_provider_page(search_res.url)
                html = search_res.content

            items_before = len(items)

            soup = BeautifulSoup(html, "html.parser")
            title = soup.find_all('h3', attrs={'class': 'video__title'})
            size = soup.find_all('div', attrs={'class': 'video__tag--size'})
            time_tags = soup.find_all('div', attrs={'class': 'video__tag--time'})
            link = soup.find_all('a', {'class': 'video--link'})
            thumb = soup.find_all('img', attrs={'class': 'thumb thumb1'})
            next_button = soup.find_all('a', {'title': 'Zobrazit další'})

            dprint('search(): titles: ' + str(title))

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

                    dprint('search(): final title: ' + final_title)

                    # videos.append(
                    #     (
                    #         final_title,
                    #         ' (' + s + " - " + m + ')',
                    #         'https://prehraj.to:443' + l['href'],
                    #         t
                    #     )
                    # )

                    list_item = xbmcgui.ListItem(
                        label = final_title,
                        label2='',
                        path = normalize_prehrajto_url(get_prehrajto_base() + l['href']),
                    )

                    dprint('THUMB: ' + thumbnail)

                    list_item.addStreamInfo('video', {
                        # 'codec': video_codec,
                        # 'width': width,
                        # 'height': height,
                        # 'aspect': aspect,
                        'duration': duration_to_seconds(duration),
                        'size': size_str_to_bytes(s),
                        # 'date': date_str_to_iso(date_added),
                        'mediatype': 'video'
                    })
                    # list_item.addStreamInfo('audio', {
                    #     'codec': item['movie_audiocodec'],
                    #     'channels': item['movie_audiochannels'],
                    # })

                    # decription = ('Uploaded: ' + date_str_to_iso(date_added)
                    #               + '\nLikes: ' + str(item['likes']))
                    # list_item.setInfo('video', {'plot': decription})
                    list_item.setArt(
                        {
                            'poster': thumbnail,
                            'thumb': thumbnail,
                            'icon': icons_path + 'prehrajto.png',
                        }
                    )

                    upload_raw = extract_upload_date_raw_from_listing_card(l)
                    if upload_raw:
                        list_item.setProperty(LISTING_UPLOAD_PROP, upload_raw)

                    list_item.setProperty('IsPlayable', 'true')
                    items.append(list_item)



                    dprint('search(): link: ' + l['href'])

                    duplicities[pot_dupl_name] = duplicitiesVal + 1
                else:
                    dup_counter = dup_counter + 1
                    dprint('search(): duplicity: ' + pot_dupl_name + ' x ' + str(dup_counter))
                    duplicities_set.append(pot_dupl_name)

            pages_loaded = page
            _update_search_dialog(
                p_dialog, p_dialog_step, items,
                *_search_status_lines(
                    pages_loaded, len(items), duplicities_set, dup_counter,
                ),
            )

            has_next_page = next_button != []
            target_reached = len(items) >= int(g_max_searched_vids)
            page_added_no_items = len(items) == items_before
            stop_searching = (
                not has_next_page
                or target_reached
                or page >= g_search_max_pages
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
        is_premium, _ = ensure_premium(addon)
        cookies = get_session().cookies if is_session_valid() else None
        return is_premium, cookies