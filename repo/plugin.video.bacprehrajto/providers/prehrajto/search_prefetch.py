import threading
from typing import Optional
from urllib.parse import quote

from common import get_headers, get_prehrajto_base
from providers.browsing_context import remember_provider_page
from utils.utils import dprint

SEARCH_REQUEST_TIMEOUT = 25


class PagePrefetch:
    """Fetch the next search page HTML in a background thread during inter-page delay."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._page: Optional[int] = None
        self._html: Optional[bytes] = None

    def start(self, session, query: str, page_num: int) -> None:
        self.cancel()

        def _worker() -> None:
            try:
                url = get_prehrajto_base() + '/hledej/' + quote(query) + '?vp-page=' + str(page_num)
                res = session.get(
                    url, headers=get_headers(), timeout=SEARCH_REQUEST_TIMEOUT,
                )
                remember_provider_page(res.url)
                html = res.content
                with self._lock:
                    self._page = page_num
                    self._html = html
                dprint(f'search prefetch: page {page_num} ready')
            except Exception as exc:
                dprint(f'search prefetch: page {page_num} failed: {exc}')

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()
        dprint(f'search prefetch: started page {page_num}')

    def take(self, page_num: int) -> Optional[bytes]:
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=SEARCH_REQUEST_TIMEOUT + 5)
        with self._lock:
            if self._page == page_num and self._html is not None:
                html = self._html
                self._page = None
                self._html = None
                self._thread = None
                return html
        return None

    def cancel(self) -> None:
        with self._lock:
            self._page = None
            self._html = None
            self._thread = None
