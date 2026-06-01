import os
import threading
import time
from typing import Optional, Tuple

import xbmc
import xbmcgui

from common import _ADDON_NAME
from downloads.download_progress import format_single_file_progress
from downloads.download_queue import active_job_count, add_job_to_queue, enqueue_job
from downloads.download_subtitles import download_subtitles
from downloads.download_worker import (
    build_prepared_download,
    execute_prepared_download,
    fetch_download_context,
    run_job,
)
from downloads.downloads_utils import get_download_folder
from downloads.stream_select import pick_stream
from utils.utils import dprint


def _notify_missing_folder() -> bool:
    if get_download_folder():
        return True
    xbmcgui.Dialog().notification(
        _ADDON_NAME,
        'Nastavte složku pro stahování',
        xbmcgui.NOTIFICATION_ERROR,
        4000,
    )
    return False


def _prepare_stream_selection(page_url: str) -> Optional[Tuple[int, str]]:
    prep = xbmcgui.DialogProgress()
    prep.create(_ADDON_NAME, 'Příprava stahování...')
    prep.update(0, 'Kontrola přihlášení...')

    try:
        prep.update(15, 'Načítám stránku...')
        context = fetch_download_context(page_url)
        prep.update(35, 'Hledám streamy...')
        selected = pick_stream(context.streams)
        if selected is None:
            return None
        stream_index = context.streams.index(selected)
        stream_path = selected.path or ''
        return stream_index, stream_path
    except Exception as exc:
        dprint(f'_prepare_stream_selection(): {exc}')
        xbmcgui.Dialog().notification(
            _ADDON_NAME, str(exc),
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        return None
    finally:
        prep.close()


def _kick_background_job(job_id: str) -> None:
    """Start processing immediately from the plugin thread (service may not be running yet)."""
    def _worker() -> None:
        run_job(job_id, notify=True, progress_notify=True)

    threading.Thread(target=_worker, daemon=True).start()


def download_direct(page_url: str) -> None:
    """Blocking download with progress dialog (original Stáhnout behaviour)."""
    if not _notify_missing_folder():
        return

    prep = xbmcgui.DialogProgress()
    prep.create(_ADDON_NAME, 'Příprava stahování...')
    prep.update(0, 'Kontrola přihlášení...')

    try:
        prep.update(15, 'Načítám stránku...')
        context = fetch_download_context(page_url)
        prep.update(35, 'Hledám streamy...')
        selected = pick_stream(context.streams)
        if selected is None:
            return
        prepared = build_prepared_download(context, selected)
    except Exception as exc:
        dprint(f'download_direct(): prepare failed: {exc}')
        xbmcgui.Dialog().notification(
            _ADDON_NAME, str(exc),
            xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        return
    finally:
        prep.close()

    name = prepared.target_filename
    dprint(f'download_direct(): source url={prepared.stream_url}')
    dprint(f'download_direct(): target path={prepared.target_path}')

    dialog = xbmcgui.DialogProgress()
    dialog.create(_ADDON_NAME, 'Stahování...')

    file_size = 0
    file_size_dl = 0
    canceled = False
    failed = False
    is_compressed = not prepared.is_premium
    start = time.time()

    def _update_progress(downloaded: int, total: int) -> None:
        nonlocal file_size, file_size_dl
        file_size = total
        file_size_dl = downloaded
        progress_pct, message = format_single_file_progress(
            downloaded, total, name, start, is_compressed=is_compressed)
        dialog.update(progress_pct, message)

    try:
        file_size_dl, file_size, canceled = execute_prepared_download(
            prepared,
            cancel_check=dialog.iscanceled,
            on_progress=_update_progress,
            progress_notify=False,
        )
        if not canceled:
            if file_size_dl == 0:
                failed = True
            elif file_size > 0 and file_size_dl < file_size:
                failed = True
    except Exception as exc:
        failed = True
        dprint(f'download_direct(): exception during transfer: {exc}')
    finally:
        dialog.close()

    if canceled or failed:
        if os.path.exists(prepared.target_path):
            os.remove(prepared.target_path)
        if failed and not canceled:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Stahování se nezdařilo',
                xbmcgui.NOTIFICATION_ERROR, 4000, sound=False)
        return

    try:
        download_subtitles(prepared.subs, prepared.name_wo_ext)
    except Exception as exc:
        dprint(f'download_direct(): subtitle download failed: {exc}')

    if xbmcgui.Dialog().yesno(_ADDON_NAME, f'Soubor stažen\n{name}\n\nPřehrát?'):
        play_path = prepared.target_path.replace('\\', '/')
        xbmc.executebuiltin(f'PlayMedia("{play_path}")')


def enqueue_to_queue_only(page_url: str) -> None:
    if not _notify_missing_folder():
        return

    selection = _prepare_stream_selection(page_url)
    if selection is None:
        return
    stream_index, stream_path = selection

    job = add_job_to_queue(
        page_url,
        stream_index=stream_index,
        stream_path=stream_path,
        autostart_service=False,
        clear_halt=True,
    )
    xbmcgui.Dialog().notification(
        _ADDON_NAME,
        f'Přidáno do fronty ({active_job_count()})\n{job.display_name}',
        xbmcgui.NOTIFICATION_INFO,
        3000,
        sound=False,
    )


def enqueue_background_download(page_url: str) -> None:
    if not _notify_missing_folder():
        return

    selection = _prepare_stream_selection(page_url)
    if selection is None:
        return
    stream_index, stream_path = selection

    job = enqueue_job(page_url, stream_index=stream_index, stream_path=stream_path)
    _kick_background_job(job.id)
    xbmcgui.Dialog().notification(
        _ADDON_NAME,
        f'Přidáno do fronty ({active_job_count()})\n{job.display_name}',
        xbmcgui.NOTIFICATION_INFO,
        3000,
        sound=False,
    )
