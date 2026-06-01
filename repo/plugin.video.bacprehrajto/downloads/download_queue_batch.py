import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import xbmcgui

from common import _ADDON_NAME, g_download_max_simultaneous
from downloads.download_progress import format_batch_dialog_message
from downloads.download_queue import (
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    can_start_job,
    clear_queue_halt,
    get_job,
    is_service_enabled,
    load_jobs,
    remove_job,
    request_cancel,
    running_jobs,
    start_download_service,
    stop_download_service,
    update_job,
)
from downloads.download_worker import reset_stale_running_jobs, run_job
from utils.utils import dprint


@dataclass
class _BatchJobState:
    job_id: str
    display_name: str
    status: str = STATUS_PENDING
    progress_bytes: int = 0
    total_bytes: int = 0
    start_time: float = 0.0
    terminal_counted: bool = False


class BatchDownloadSession:
    """In-memory batch state; UI reads only this during blocking batch download."""

    def __init__(self, job_ids: List[str]) -> None:
        self.total = len(job_ids)
        self._lock = threading.Lock()
        self._order: List[str] = list(job_ids)
        self._states: Dict[str, _BatchJobState] = {}
        self.counts: Dict[str, int] = {'done': 0, 'failed': 0, 'canceled': 0}
        self.completed: int = 0

        jobs_by_id = {job.id: job for job in load_jobs()}
        for job_id in self._order:
            job = jobs_by_id.get(job_id)
            name = job_id
            if job:
                name = job.target_filename or job.display_name or job.page_url
            self._states[job_id] = _BatchJobState(job_id=job_id, display_name=name)

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if state is None or state.terminal_counted:
                return
            state.status = STATUS_RUNNING
            if state.start_time <= 0:
                state.start_time = time.time()

    def revert_to_pending(self, job_id: str) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if state is None or state.terminal_counted:
                return
            state.status = STATUS_PENDING
            state.progress_bytes = 0
            state.total_bytes = 0
            state.start_time = 0.0

    def update_progress(self, job_id: str, downloaded: int, total: int) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if state is None or state.status != STATUS_RUNNING:
                return
            state.progress_bytes = downloaded
            state.total_bytes = total

    def mark_terminal(self, job_id: str, status: str) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if state is None or state.terminal_counted:
                return
            state.terminal_counted = True
            state.status = status
            self.completed += 1
            if status == STATUS_DONE:
                self.counts['done'] += 1
            elif status == STATUS_FAILED:
                self.counts['failed'] += 1
            elif status == STATUS_CANCELED:
                self.counts['canceled'] += 1

    def pending_job_ids(self) -> List[str]:
        with self._lock:
            return [
                job_id for job_id in self._order
                if not self._states[job_id].terminal_counted
                and self._states[job_id].status == STATUS_PENDING
            ]

    def running_count(self) -> int:
        with self._lock:
            return sum(
                1 for job_id in self._order
                if self._states[job_id].status == STATUS_RUNNING
                and not self._states[job_id].terminal_counted
            )

    def is_all_terminal(self) -> bool:
        with self._lock:
            return self.completed >= self.total

    def snapshot_for_ui(self) -> Tuple[List[str], Dict[str, dict]]:
        with self._lock:
            order = list(self._order)
            states = {
                job_id: {
                    'display_name': s.display_name,
                    'status': s.status,
                    'progress_bytes': s.progress_bytes,
                    'total_bytes': s.total_bytes,
                    'start_time': s.start_time or time.time(),
                }
                for job_id, s in self._states.items()
            }
            return order, states


def _eligible_batch_jobs() -> List[str]:
    job_ids = []
    for job in load_jobs():
        if job.cancel_requested:
            continue
        if job.status in (STATUS_PENDING, STATUS_FAILED):
            job_ids.append(job.id)
    return job_ids


def _build_batch_session() -> Optional[BatchDownloadSession]:
    jobs = load_jobs()
    eligible = [
        job for job in jobs
        if not job.cancel_requested and job.status in (STATUS_PENDING, STATUS_FAILED)
    ]
    if not eligible:
        return None
    ordered = sorted(eligible, key=lambda item: item.added_at)
    return BatchDownloadSession([job.id for job in ordered])


def _reset_failed_jobs(job_ids: Set[str]) -> None:
    for job_id in job_ids:
        job = get_job(job_id)
        if job is None or job.status != STATUS_FAILED:
            continue
        update_job(
            job_id,
            status=STATUS_PENDING,
            error=None,
            progress_bytes=0,
            total_bytes=0,
            cancel_requested=False,
        )


def run_job_for_batch(job_id: str, session: BatchDownloadSession) -> bool:
    session.mark_running(job_id)

    def progress_cb(downloaded: int, total: int) -> None:
        session.update_progress(job_id, downloaded, total)
        update_job(job_id, progress_bytes=downloaded, total_bytes=total)

    success = run_job(
        job_id,
        notify=False,
        progress_notify=False,
        progress_callback=progress_cb,
    )

    if success:
        session.mark_terminal(job_id, STATUS_DONE)
        remove_job(job_id)
        return True

    job = get_job(job_id)
    if job is None:
        session.mark_terminal(job_id, STATUS_CANCELED)
    elif job.status in (STATUS_FAILED, STATUS_CANCELED):
        session.mark_terminal(job_id, job.status)
    else:
        session.revert_to_pending(job_id)
    return False


def _wait_for_threads(threads: Dict[str, threading.Thread]) -> None:
    for thread in list(threads.values()):
        if thread.is_alive():
            thread.join(timeout=0.5)
    deadline = time.time() + 30
    while time.time() < deadline:
        alive = [t for t in threads.values() if t.is_alive()]
        if not alive:
            break
        for thread in alive:
            thread.join(timeout=0.5)


def download_queue_blocking() -> None:
    was_service_enabled = is_service_enabled()
    stop_download_service()
    clear_queue_halt()
    reset_stale_running_jobs()

    session = _build_batch_session()
    if session is None:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'Fronta neobsahuje soubory ke stažení',
            xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
        if was_service_enabled:
            start_download_service()
        return

    batch_ids: Set[str] = set(session._order)
    _reset_failed_jobs(batch_ids)

    active_threads: Dict[str, threading.Thread] = {}
    threads_lock = threading.Lock()

    dialog = xbmcgui.DialogProgress()
    dialog.create(_ADDON_NAME, 'Stahování fronty...')

    canceled = False
    try:
        while True:
            if dialog.iscanceled():
                canceled = True
                for job_id in session._order:
                    state = session._states.get(job_id)
                    if state and not state.terminal_counted:
                        if state.status in (STATUS_PENDING, STATUS_RUNNING):
                            request_cancel(job_id)
                break

            jobs = load_jobs()
            running = [job for job in running_jobs(jobs) if job.id in batch_ids]

            with threads_lock:
                for job_id in list(active_threads.keys()):
                    if not active_threads[job_id].is_alive():
                        active_threads.pop(job_id, None)

            for job_id in session.pending_job_ids():
                with threads_lock:
                    if job_id in active_threads:
                        continue
                job = get_job(job_id)
                if job is None:
                    continue
                if not can_start_job(job, running):
                    continue

                def _worker(jid: str, sess: BatchDownloadSession) -> None:
                    run_job_for_batch(jid, sess)

                thread = threading.Thread(
                    target=_worker, args=(job_id, session), daemon=True)
                with threads_lock:
                    active_threads[job_id] = thread
                thread.start()
                running = list(running_jobs(load_jobs()))
                running = [j for j in running if j.id in batch_ids]
                dprint(f'download_queue_blocking: started job {job_id}')

            order, states = session.snapshot_for_ui()
            overall_pct, message = format_batch_dialog_message(
                session.completed,
                session.total,
                session.running_count(),
                g_download_max_simultaneous,
                order,
                states,
                g_download_max_simultaneous,
            )
            dialog.update(overall_pct, message)

            with threads_lock:
                threads_alive = any(t.is_alive() for t in active_threads.values())

            if session.is_all_terminal() and not threads_alive:
                break
            if not session.pending_job_ids() and not threads_alive:
                break

            time.sleep(0.25)

        _wait_for_threads(active_threads)
    finally:
        dialog.close()
        if was_service_enabled:
            start_download_service()

    parts = []
    if session.counts['done']:
        parts.append(f"{session.counts['done']} staženo")
    if session.counts['failed']:
        parts.append(f"{session.counts['failed']} chyba")
    if session.counts['canceled'] or canceled:
        parts.append(f"{session.counts['canceled']} zrušeno")
    summary = ', '.join(parts) if parts else 'Hotovo'
    xbmcgui.Dialog().notification(
        _ADDON_NAME, summary,
        xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
