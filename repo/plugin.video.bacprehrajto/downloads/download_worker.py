import os
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import requests
import xbmcgui

from common import (
    _ADDON_NAME,
    addon,
    g_is_prehrajto_enabled,
    g_quality_selector,
    get_headers,
)
from downloads.download_naming import get_name_ext
from downloads.download_queue import (
    PROVIDER_HELLSPY,
    PROVIDER_PREHRAJTO,
    PROVIDER_SLEDUJTETO,
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    claim_job_for_running,
    detect_provider,
    get_job,
    is_cancel_requested,
    load_jobs,
    update_job,
)
from downloads.download_subtitles import download_subtitles
from downloads.downloads_utils import get_download_folder
from downloads.stream_select import resolve_stream, select_stream_auto
from model.StreamData import StreamData
from model.SubData import SubData
from providers.UniversalProvider import UniversalProvider
from providers.prehrajto.auth import ensure_premium
from providers.prehrajto.download import ensure_premium_stream, resolve_premium_download_url
from providers.prehrajto.playback_context import (
    build_prehrajto_stream_context,
    resolve_subtitles_for_selection,
)
from providers.prehrajto.session import get_session as get_prehrajto_session, has_auth_cookies
from utils.utils import dprint, stream_http_download

_provider = UniversalProvider()

_PROGRESS_NOTIFY_STEP = 10


@dataclass
class DownloadContext:
    page_url: str
    content: bytes
    streams: List[StreamData]
    subs: Optional[List[SubData]]
    session: requests.Session
    cookies: Optional[dict]
    provider: str


@dataclass
class PreparedDownload:
    page_url: str
    stream_url: str
    stream_headers: dict
    download_session: requests.Session
    target_path: str
    target_filename: str
    name_wo_ext: str
    is_premium: bool
    subs: Optional[List[SubData]]


def _get_premium_cookies():
    if not g_is_prehrajto_enabled:
        return None
    ensure_premium(addon)
    session = get_prehrajto_session()
    return session.cookies if has_auth_cookies(session) else None


def _page_headers(provider: str) -> dict:
    if provider == PROVIDER_HELLSPY:
        from providers.hellspy.auth import request_headers
        return request_headers()
    return get_headers()


def _page_session(provider: str):
    if provider == PROVIDER_HELLSPY:
        from providers.hellspy.session import get_session as get_hellspy_session
        return get_hellspy_session(), None
    if provider == PROVIDER_SLEDUJTETO:
        from providers.sledujteto.session import get_session as get_sledujteto_session
        return get_sledujteto_session(), None
    cookies = _get_premium_cookies()
    return get_prehrajto_session(), cookies


def fetch_download_context(page_url: str, provider: Optional[str] = None) -> DownloadContext:
    provider = provider or detect_provider(page_url)
    session, cookies = _page_session(provider)
    res = session.get(page_url, headers=_page_headers(provider), allow_redirects=True)
    res.raise_for_status()
    if provider == PROVIDER_HELLSPY:
        from providers.hellspy.session import save_session as save_hellspy_session
        save_hellspy_session()
    content = res.content
    resolved_page_url = res.url

    streams, subs = _provider.get_streams_data(resolved_page_url, content, show_progress=False)
    if streams is None or len(streams) == 0:
        raise RuntimeError('Streamy nenalezeny')

    if cookies:
        streams = ensure_premium_stream(streams, resolved_page_url, cookies)

    return DownloadContext(
        page_url=resolved_page_url,
        content=content,
        streams=streams,
        subs=subs,
        session=session,
        cookies=cookies,
        provider=provider,
    )


def build_prepared_download(context: DownloadContext, selected: StreamData) -> PreparedDownload:
    subs = context.subs
    if context.provider == PROVIDER_PREHRAJTO:
        ctx = build_prehrajto_stream_context(
            context.page_url, context.content, context.cookies)
        subs = resolve_subtitles_for_selection(ctx, selected)

    stream_url = selected.path
    if selected.is_premium:
        resolved = resolve_premium_download_url(
            context.page_url, cookies=context.cookies, extra_headers=selected.headers)
        if not resolved:
            raise RuntimeError('Premium stream nelze stáhnout')
        stream_url = resolved

    name_wo_ext, extension = get_name_ext(context.page_url, context.content, stream_url=stream_url)
    if not name_wo_ext:
        name_wo_ext = 'downloaded'
    if not extension:
        extension = 'mp4'
    filename = f'{name_wo_ext}.{extension}'

    folder = get_download_folder()
    if folder is None:
        raise RuntimeError('Nastavte složku pro stahování')

    download_session = context.session if context.provider == PROVIDER_SLEDUJTETO else requests.Session()
    if context.cookies and context.provider != PROVIDER_SLEDUJTETO:
        download_session.cookies.update(context.cookies)

    return PreparedDownload(
        page_url=context.page_url,
        stream_url=stream_url,
        stream_headers=dict(selected.headers or {}),
        download_session=download_session,
        target_path=folder + filename,
        target_filename=filename,
        name_wo_ext=name_wo_ext,
        is_premium=selected.is_premium,
        subs=subs,
    )


def prepare_download(
        page_url: str,
        provider: str,
        stream_index: Optional[int] = None,
        stream_path: str = '',
) -> PreparedDownload:
    context = fetch_download_context(page_url, provider)
    selected = resolve_stream(context.streams, stream_index, stream_path)
    if selected is None:
        raise RuntimeError('Stream nevybrán')
    return build_prepared_download(context, selected)


def _cleanup_partial(path: str) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _notify_progress(filename: str, downloaded: int, total: int, last_pct: list) -> None:
    if total <= 0:
        return
    pct = int(downloaded * 100 / total)
    if pct < last_pct[0] + _PROGRESS_NOTIFY_STEP and pct < 100:
        return
    last_pct[0] = pct
    xbmcgui.Dialog().notification(
        _ADDON_NAME,
        f'{pct}%  {filename}',
        xbmcgui.NOTIFICATION_INFO,
        2500,
        sound=False,
    )


def execute_prepared_download(
        prepared: PreparedDownload,
        cancel_check=None,
        on_progress=None,
        progress_notify: bool = False,
) -> tuple:
    last_pct = [-1]

    def _combined_progress(downloaded: int, total: int) -> None:
        if on_progress:
            on_progress(downloaded, total)
        if progress_notify:
            _notify_progress(prepared.target_filename, downloaded, total, last_pct)

    return stream_http_download(
        prepared.stream_url,
        prepared.target_path,
        headers=prepared.stream_headers,
        session=prepared.download_session,
        cancel_check=cancel_check,
        on_progress=_combined_progress,
    )


def reset_stale_running_jobs() -> None:
    """Jobs left in 'running' after a crash are retried."""
    for job in load_jobs():
        if job.status == STATUS_RUNNING:
            update_job(job.id, status=STATUS_PENDING, progress_bytes=0, total_bytes=0)


def run_job(
        job_id: str,
        notify: bool = True,
        progress_notify: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None,
) -> bool:
    job = claim_job_for_running(job_id)
    if job is None:
        return False

    prepared: Optional[PreparedDownload] = None
    try:
        if is_cancel_requested(job_id):
            update_job(job_id, status=STATUS_CANCELED)
            return False

        prepared = prepare_download(
            job.page_url,
            job.provider,
            stream_index=job.stream_index,
            stream_path=job.stream_path,
        )
        update_job(
            job_id,
            target_filename=prepared.target_filename,
            display_name=prepared.target_filename,
        )

        if progress_notify:
            xbmcgui.Dialog().notification(
                _ADDON_NAME,
                f'Stahování: {prepared.target_filename}',
                xbmcgui.NOTIFICATION_INFO,
                3000,
                sound=False,
            )

        def cancel_check() -> bool:
            return is_cancel_requested(job_id)

        def on_progress(downloaded: int, total: int) -> None:
            if progress_callback:
                progress_callback(downloaded, total)
            else:
                update_job(job_id, progress_bytes=downloaded, total_bytes=total)

        downloaded, total, canceled = execute_prepared_download(
            prepared,
            cancel_check=cancel_check,
            on_progress=on_progress,
            progress_notify=progress_notify,
        )

        if canceled or is_cancel_requested(job_id):
            _cleanup_partial(prepared.target_path)
            update_job(job_id, status=STATUS_CANCELED, error=None)
            if notify:
                xbmcgui.Dialog().notification(
                    _ADDON_NAME, f'Stahování zrušeno\n{prepared.target_filename}',
                    xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
            return False

        if downloaded == 0 or (total > 0 and downloaded < total):
            _cleanup_partial(prepared.target_path)
            update_job(job_id, status=STATUS_FAILED, error='Neúplné stažení')
            if notify:
                xbmcgui.Dialog().notification(
                    _ADDON_NAME, f'Stahování se nezdařilo\n{prepared.target_filename}',
                    xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
            return False

        try:
            download_subtitles(
                prepared.subs, prepared.name_wo_ext, referer=prepared.page_url)
        except Exception as exc:
            dprint(f'run_job(): subtitle download failed: {exc}')

        update_job(job_id, status=STATUS_DONE, progress_bytes=downloaded, total_bytes=total or downloaded)
        if notify:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, f'Staženo\n{prepared.target_filename}',
                xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
        return True

    except Exception as exc:
        dprint(f'run_job(): {job_id}: {exc}')
        if prepared is not None:
            _cleanup_partial(prepared.target_path)
        update_job(job_id, status=STATUS_FAILED, error=str(exc))
        if notify:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, f'Stahování se nezdařilo\n{job.display_name or job_id}',
                xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        return False
