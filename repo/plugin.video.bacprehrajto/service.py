import threading

import xbmc
import xbmcaddon
import xbmcgui

from cache.subtitle_cache import SubtitleCacheSettingsMonitor, refresh_subtitle_cache_setting
from utils.user_agent_presets import refresh_user_agent_setting
from common import _ADDON_NAME
from downloads.download_queue import (
    STATUS_PENDING,
    get_queue_halt_reason,
    halt_queue,
    is_queue_halted,
    is_service_enabled,
    pending_jobs,
    running_jobs,
    should_halt_after_failure,
    can_start_job,
    get_job,
    load_jobs,
)
from downloads.download_worker import reset_stale_running_jobs, run_job
from utils.utils import dprint

_addon = xbmcaddon.Addon()

_monitor = xbmc.Monitor()
_active_threads: dict = {}
_threads_lock = threading.Lock()
_halt_lock = threading.Lock()
_halt_notified = False
_subtitle_cache_settings_monitor = SubtitleCacheSettingsMonitor()


def _run_job_thread(job_id: str) -> None:
    global _halt_notified
    try:
        if not is_service_enabled() or is_queue_halted():
            return
        success = run_job(job_id, notify=True, progress_notify=True)
        if not success:
            with _halt_lock:
                if should_halt_after_failure() and not is_queue_halted():
                    reason = 'Všechna stahování ve frontě selhala'
                    halt_queue(reason)
                    if not _halt_notified:
                        _halt_notified = True
                        xbmcgui.Dialog().notification(
                            _ADDON_NAME,
                            reason,
                            xbmcgui.NOTIFICATION_ERROR,
                            5000,
                            sound=False,
                        )
        else:
            with _halt_lock:
                _halt_notified = False
    finally:
        with _threads_lock:
            _active_threads.pop(job_id, None)


def _cleanup_threads() -> None:
    with _threads_lock:
        finished = [job_id for job_id, thread in _active_threads.items() if not thread.is_alive()]
        for job_id in finished:
            _active_threads.pop(job_id, None)


def _process_queue() -> None:
    if not is_service_enabled() or is_queue_halted():
        return

    _cleanup_threads()
    jobs = load_jobs()
    running = list(running_jobs(jobs))

    with _threads_lock:
        for job_id in list(_active_threads.keys()):
            job = get_job(job_id)
            if job and job.status == STATUS_PENDING and job not in running:
                running.append(job)

    for job in pending_jobs(jobs):
        with _threads_lock:
            if job.id in _active_threads:
                continue
        if not can_start_job(job, running):
            continue
        thread = threading.Thread(target=_run_job_thread, args=(job.id,), daemon=True)
        with _threads_lock:
            _active_threads[job.id] = thread
        thread.start()
        running.append(job)
        dprint(f'service: started download job {job.id}')


if __name__ == '__main__':
    dprint('service: download queue service started')
    try:
        refresh_subtitle_cache_setting()
        refresh_user_agent_setting()
    except Exception as exc:
        dprint(f'service: settings display refresh failed: {exc}')
    reset_stale_running_jobs()
    halt_reason = get_queue_halt_reason()
    if halt_reason:
        dprint(f'service: queue halted — {halt_reason}')
    _process_queue()
    while not _monitor.waitForAbort(1):
        try:
            _subtitle_cache_settings_monitor.tick()
            _process_queue()
        except Exception as exc:
            dprint(f'service: queue error: {exc}')

    dprint('service: download queue service stopped')
