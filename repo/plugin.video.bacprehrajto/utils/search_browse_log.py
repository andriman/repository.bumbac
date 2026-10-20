"""Debug logging while browsing search result pages (when debug logging is enabled)."""
import time
from datetime import datetime
from typing import Optional

from utils.utils import dprint


class SearchBrowseLogger:
    def __init__(self, query: str) -> None:
        self.query = query
        self.start_time = time.time()
        self.prehrajto_page = 0
        self.sledujteto_page = 0
        self.hellspy_page = 0
        self.video_count = 0
        self.duplicity_names = 0
        self.duplicate_files = 0

    def log_prehrajto_page(
            self,
            page: int,
            video_count: int,
            duplicity_names: int,
            duplicate_files: int,
            added_on_page: int,
            http_ms: Optional[int] = None,
            parse_ms: Optional[int] = None,
            listitem_ms: Optional[int] = None,
            upload_index_ms: Optional[int] = None,
    ) -> None:
        self.prehrajto_page = page
        self.video_count = video_count
        self.duplicity_names = duplicity_names
        self.duplicate_files = duplicate_files
        self._emit(
            provider='prehrajto',
            page=page,
            added_on_page=added_on_page,
            http_ms=http_ms,
            parse_ms=parse_ms,
            listitem_ms=listitem_ms,
            upload_index_ms=upload_index_ms,
        )

    def log_sledujteto_page(
            self,
            page: int,
            video_count: int,
            added_on_page: int,
            total_api_pages: int = 0,
            http_ms: Optional[int] = None,
            parse_ms: Optional[int] = None,
            listitem_ms: Optional[int] = None,
    ) -> None:
        self.sledujteto_page = page
        self.video_count = video_count
        self._emit(
            provider='sledujteto',
            page=page,
            added_on_page=added_on_page,
            total_api_pages=total_api_pages,
            http_ms=http_ms,
            parse_ms=parse_ms,
            listitem_ms=listitem_ms,
        )

    def log_hellspy_page(
            self,
            page: int,
            video_count: int,
            added_on_page: int,
            http_ms: Optional[int] = None,
            parse_ms: Optional[int] = None,
            listitem_ms: Optional[int] = None,
    ) -> None:
        self.hellspy_page = page
        self.video_count = video_count
        self._emit(
            provider='hellspy',
            page=page,
            added_on_page=added_on_page,
            http_ms=http_ms,
            parse_ms=parse_ms,
            listitem_ms=listitem_ms,
        )

    def _emit(
            self,
            provider: str,
            page: int,
            added_on_page: int,
            total_api_pages: int = 0,
            http_ms: Optional[int] = None,
            parse_ms: Optional[int] = None,
            listitem_ms: Optional[int] = None,
            upload_index_ms: Optional[int] = None,
    ) -> None:
        elapsed = time.time() - self.start_time
        start_str = datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')
        extra = f' | api_pages_total={total_api_pages}' if total_api_pages else ''
        timing = ''
        if any(x is not None for x in (http_ms, parse_ms, upload_index_ms, listitem_ms)):
            timing = (
                f' | http_ms={http_ms if http_ms is not None else "-"}'
                f' | parse_ms={parse_ms if parse_ms is not None else "-"}'
                f' | upload_index_ms={upload_index_ms if upload_index_ms is not None else "-"}'
                f' | listitem_ms={listitem_ms if listitem_ms is not None else "-"}'
            )
        dprint(
            f'search_browse: provider={provider} | page={page} | start={start_str} | '
            f'elapsed={elapsed:.1f}s | prehrajto_page={self.prehrajto_page} | '
            f'sledujteto_page={self.sledujteto_page} | hellspy_page={self.hellspy_page} | '
            f'videos={self.video_count} | '
            f'new_on_page={added_on_page} | duplicities={self.duplicity_names} | '
            f'dup_files={self.duplicate_files}{timing}{extra} | query={self.query!r}'
        )


_active: Optional[SearchBrowseLogger] = None


def begin_search_browse_log(query: str) -> SearchBrowseLogger:
    global _active
    _active = SearchBrowseLogger(query)
    start_str = datetime.fromtimestamp(_active.start_time).strftime('%Y-%m-%d %H:%M:%S')
    dprint(f'search_browse: start={start_str} | query={query!r}')
    return _active


def get_search_browse_logger() -> Optional[SearchBrowseLogger]:
    return _active


def end_search_browse_log() -> None:
    global _active
    if _active is None:
        return
    elapsed = time.time() - _active.start_time
    dprint(
        f'search_browse: finished | elapsed={elapsed:.1f}s | '
        f'prehrajto_page={_active.prehrajto_page} | sledujteto_page={_active.sledujteto_page} | '
        f'hellspy_page={_active.hellspy_page} | '
        f'videos={_active.video_count} | duplicities={_active.duplicity_names} | '
        f'dup_files={_active.duplicate_files} | query={_active.query!r}'
    )
    _active = None
