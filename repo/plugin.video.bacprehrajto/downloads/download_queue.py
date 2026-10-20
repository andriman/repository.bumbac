import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import xbmcvfs

from common import (
    addon,
    g_download_max_simultaneous,
    g_hellspy_allow_parallel_downloads,
    g_prehrajto_allow_parallel_downloads,
    g_sledujteto_allow_parallel_downloads,
)

PROVIDER_PREHRAJTO = 'prehrajto'
PROVIDER_SLEDUJTETO = 'sledujteto'
PROVIDER_HELLSPY = 'hellspy'

STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_CANCELED = 'canceled'

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_RUNNING)
TERMINAL_STATUSES = (STATUS_DONE, STATUS_FAILED, STATUS_CANCELED)

_lock = threading.Lock()


@dataclass
class DownloadJob:
    id: str
    page_url: str
    provider: str
    status: str = STATUS_PENDING
    progress_bytes: int = 0
    total_bytes: int = 0
    target_filename: str = ''
    display_name: str = ''
    error: Optional[str] = None
    cancel_requested: bool = False
    stream_index: Optional[int] = None
    stream_path: str = ''
    added_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'DownloadJob':
        return cls(
            id=data['id'],
            page_url=data['page_url'],
            provider=data['provider'],
            status=data.get('status', STATUS_PENDING),
            progress_bytes=int(data.get('progress_bytes') or 0),
            total_bytes=int(data.get('total_bytes') or 0),
            target_filename=data.get('target_filename') or '',
            display_name=data.get('display_name') or '',
            error=data.get('error'),
            cancel_requested=bool(data.get('cancel_requested')),
            stream_index=data.get('stream_index'),
            stream_path=data.get('stream_path') or '',
            added_at=float(data.get('added_at') or time.time()),
            updated_at=float(data.get('updated_at') or time.time()),
        )


def detect_provider(page_url: str) -> str:
    url_lower = page_url.lower()
    if 'hellspy' in url_lower:
        return PROVIDER_HELLSPY
    if 'sledujteto' in url_lower:
        return PROVIDER_SLEDUJTETO
    return PROVIDER_PREHRAJTO


def _queue_path() -> str:
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.exists(profile):
        os.makedirs(profile)
    return os.path.join(profile, 'download_queue.json')


def load_jobs() -> List[DownloadJob]:
    path = _queue_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [DownloadJob.from_dict(item) for item in raw if isinstance(item, dict)]


def save_jobs(jobs: List[DownloadJob]) -> None:
    path = _queue_path()
    payload = [job.to_dict() for job in jobs]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _mutate(mutator) -> Optional[DownloadJob]:
    with _lock:
        jobs = load_jobs()
        result = mutator(jobs)
        save_jobs(jobs)
        return result


def get_job(job_id: str) -> Optional[DownloadJob]:
    for job in load_jobs():
        if job.id == job_id:
            return job
    return None


def add_job_to_queue(
        page_url: str,
        stream_index: Optional[int] = None,
        stream_path: str = '',
        *,
        autostart_service: bool = False,
        clear_halt: bool = True,
) -> DownloadJob:
    job = DownloadJob(
        id=str(uuid.uuid4()),
        page_url=page_url,
        provider=detect_provider(page_url),
        display_name=_display_name_from_url(page_url),
        stream_index=stream_index,
        stream_path=stream_path or '',
    )

    def mutator(jobs: List[DownloadJob]) -> DownloadJob:
        jobs.append(job)
        return job

    if clear_halt:
        clear_queue_halt()
    if autostart_service:
        start_download_service()
    return _mutate(mutator) or job


def enqueue_job(
        page_url: str,
        stream_index: Optional[int] = None,
        stream_path: str = '',
) -> DownloadJob:
    return add_job_to_queue(
        page_url,
        stream_index=stream_index,
        stream_path=stream_path,
        autostart_service=True,
        clear_halt=True,
    )


def claim_job_for_running(job_id: str) -> Optional[DownloadJob]:
    def mutator(jobs: List[DownloadJob]) -> Optional[DownloadJob]:
        for job in jobs:
            if job.id != job_id:
                continue
            if job.status != STATUS_PENDING or job.cancel_requested:
                return None
            job.status = STATUS_RUNNING
            job.error = None
            job.progress_bytes = 0
            job.total_bytes = 0
            job.updated_at = time.time()
            return job
        return None

    return _mutate(mutator)


def update_job(job_id: str, **fields) -> Optional[DownloadJob]:
    def mutator(jobs: List[DownloadJob]) -> Optional[DownloadJob]:
        for job in jobs:
            if job.id != job_id:
                continue
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = time.time()
            return job
        return None

    return _mutate(mutator)


def request_cancel(job_id: str) -> Optional[DownloadJob]:
    job = get_job(job_id)
    if job is None:
        return None
    if job.status == STATUS_PENDING:
        return update_job(job_id, status=STATUS_CANCELED, cancel_requested=True)
    return update_job(job_id, cancel_requested=True)


def remove_job(job_id: str) -> bool:
    removed = False

    def mutator(jobs: List[DownloadJob]) -> None:
        nonlocal removed
        before = len(jobs)
        jobs[:] = [job for job in jobs if job.id != job_id]
        removed = len(jobs) < before

    _mutate(mutator)
    return removed


def clear_finished_jobs() -> int:
    removed = 0

    def mutator(jobs: List[DownloadJob]) -> None:
        nonlocal removed
        before = len(jobs)
        jobs[:] = [job for job in jobs if job.status not in TERMINAL_STATUSES]
        removed = before - len(jobs)

    _mutate(mutator)
    return removed


def clear_download_queue() -> int:
    stop_download_service()

    removed = 0

    def mutator(jobs: List[DownloadJob]) -> None:
        nonlocal removed
        removed = len(jobs)
        jobs.clear()

    _mutate(mutator)
    clear_queue_halt()
    return removed


def active_job_count() -> int:
    return sum(1 for job in load_jobs() if job.status in (STATUS_PENDING, STATUS_RUNNING))


def queue_summary() -> Dict[str, int]:
    jobs = load_jobs()
    summary = {'pending': 0, 'running': 0, 'done': 0, 'failed': 0, 'canceled': 0, 'total': len(jobs)}
    for job in jobs:
        if job.status in summary:
            summary[job.status] += 1
    return summary


def pending_jobs(jobs: Optional[List[DownloadJob]] = None) -> List[DownloadJob]:
    items = jobs if jobs is not None else load_jobs()
    return [job for job in items if job.status == STATUS_PENDING and not job.cancel_requested]


def running_jobs(jobs: Optional[List[DownloadJob]] = None) -> List[DownloadJob]:
    items = jobs if jobs is not None else load_jobs()
    return [job for job in items if job.status == STATUS_RUNNING]


def provider_allows_parallel(provider: str) -> bool:
    if provider == PROVIDER_SLEDUJTETO:
        return g_sledujteto_allow_parallel_downloads
    if provider == PROVIDER_HELLSPY:
        return g_hellspy_allow_parallel_downloads
    return g_prehrajto_allow_parallel_downloads


def can_start_job(job: DownloadJob, running: Optional[List[DownloadJob]] = None) -> bool:
    active_running = running if running is not None else running_jobs()
    if len(active_running) >= g_download_max_simultaneous:
        return False
    provider_running = sum(1 for item in active_running if item.provider == job.provider)
    if not provider_allows_parallel(job.provider) and provider_running >= 1:
        return False
    return True


def is_cancel_requested(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job.cancel_requested)


def _queue_state_path() -> str:
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.exists(profile):
        os.makedirs(profile)
    return os.path.join(profile, 'download_queue_state.json')


def _load_queue_state() -> dict:
    path = _queue_state_path()
    default = {'halted': False, 'reason': '', 'service_enabled': True}
    if not os.path.exists(path):
        return dict(default)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    return {
        'halted': bool(data.get('halted')),
        'reason': data.get('reason') or '',
        'service_enabled': data.get('service_enabled', True),
    }


def _save_queue_state(state: dict) -> None:
    path = _queue_state_path()
    profile = os.path.dirname(path)
    if not os.path.exists(profile):
        os.makedirs(profile)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_queue_halt_reason() -> Optional[str]:
    state = _load_queue_state()
    if state['halted']:
        return state['reason'] or 'Fronta zastavena'
    return None


def set_queue_halted(reason: str) -> None:
    state = _load_queue_state()
    state['halted'] = True
    state['reason'] = reason
    _save_queue_state(state)


def clear_queue_halt() -> None:
    state = _load_queue_state()
    state['halted'] = False
    state['reason'] = ''
    _save_queue_state(state)


def is_service_enabled() -> bool:
    return _load_queue_state()['service_enabled']


def set_service_enabled(enabled: bool) -> None:
    state = _load_queue_state()
    state['service_enabled'] = enabled
    _save_queue_state(state)


def stop_download_service() -> int:
    set_service_enabled(False)
    stopped = 0
    for job in load_jobs():
        if job.status == STATUS_RUNNING:
            request_cancel(job.id)
            stopped += 1
    return stopped


def start_download_service() -> None:
    set_service_enabled(True)


def is_queue_halted() -> bool:
    return get_queue_halt_reason() is not None


def cancel_all_pending(reason: str) -> int:
    canceled = 0

    def mutator(jobs: List[DownloadJob]) -> None:
        nonlocal canceled
        for job in jobs:
            if job.status != STATUS_PENDING or job.cancel_requested:
                continue
            job.status = STATUS_CANCELED
            job.cancel_requested = True
            job.error = reason
            job.updated_at = time.time()
            canceled += 1

    _mutate(mutator)
    return canceled


def has_successful_jobs() -> bool:
    return any(job.status == STATUS_DONE for job in load_jobs())


def should_halt_after_failure() -> bool:
    jobs = load_jobs()
    if any(job.status == STATUS_DONE for job in jobs):
        return False
    if pending_jobs(jobs) or running_jobs(jobs):
        return False
    return any(job.status == STATUS_FAILED for job in jobs)


def halt_queue(reason: str) -> int:
    set_queue_halted(reason)
    return cancel_all_pending(reason)


def _display_name_from_url(page_url: str) -> str:
    path = page_url.rstrip('/').split('/')
    if not path:
        return page_url
    slug = path[-1]
    if slug.endswith('.html'):
        slug = slug[:-5]
    return slug.replace('-', ' ') or page_url
