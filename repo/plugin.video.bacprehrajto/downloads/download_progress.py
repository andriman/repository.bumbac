import time
from typing import List, Optional, Tuple

from downloads.download_queue import STATUS_RUNNING
from utils.StrUtils import convert_size, truncate_middle
from utils.TimeUtils import format_eta_and_finish


def format_single_file_progress(
        downloaded: int,
        total: int,
        filename: str,
        start_time: float,
        is_compressed: bool = False,
        size_label: Optional[str] = None,
) -> Tuple[int, str]:
    """Returns (progress_percent, dialog_message) for a single active download."""
    conv_size = size_label or ('?' if total <= 0 else convert_size(total))
    compressed_str = '      (komprimováno)' if is_compressed else ''
    truncated_name = truncate_middle(filename)

    if total > 0:
        status = r'%3.2f%%' % (downloaded * 100. / total)
        progress_pct = int(downloaded * 100 / total)
    else:
        status = convert_size(downloaded)
        progress_pct = 0

    elapsed = time.time() - start_time
    speed = '0.0' if elapsed <= 0 else f'{(downloaded / elapsed) / 100000:.1f}'
    if elapsed > 0 and downloaded > 0 and total > 0:
        bytes_per_sec = downloaded / elapsed
        remaining_bytes = total - downloaded
        eta_seconds = remaining_bytes / bytes_per_sec if bytes_per_sec > 0 else None
    else:
        eta_seconds = None

    eta_str, finish_str = format_eta_and_finish(eta_seconds)
    message = (
        'Velikost:  ' + conv_size + compressed_str + '\n'
        + 'Staženo:  ' + status + '     Rychlost: ' + speed + ' Mb/s\n'
        + 'Hotovo za: ' + eta_str + '       Hotovo v:  ' + finish_str + '\n'
        + truncated_name
    )
    return progress_pct, message


def format_batch_header(
        finished_count: int,
        batch_total: int,
        active_count: int,
        max_simultaneous: int,
) -> str:
    return (
        f'Hotovo: {finished_count} / {batch_total}\n'
        f'Současně: {active_count} / {max_simultaneous}'
    )


def format_batch_multi_active(active_lines: List[str]) -> str:
    if not active_lines:
        return 'Čekám na další soubor...'
    return '\n'.join(f'• {line}' for line in active_lines)


def format_compact_file_progress(
        downloaded: int,
        total: int,
        filename: str,
        start_time: float,
) -> str:
    """Single-line progress for multi-download batch view."""
    truncated_name = truncate_middle(filename, 48)
    if total > 0:
        pct = int(downloaded * 100 / total)
        status = f'{pct}%'
    else:
        status = convert_size(downloaded)

    elapsed = time.time() - start_time
    speed = '0.0' if elapsed <= 0 else f'{(downloaded / elapsed) / 100000:.1f}'
    if elapsed > 0 and downloaded > 0 and total > 0:
        bytes_per_sec = downloaded / elapsed
        remaining_bytes = total - downloaded
        eta_seconds = remaining_bytes / bytes_per_sec if bytes_per_sec > 0 else None
    else:
        eta_seconds = None

    eta_str, finish_str = format_eta_and_finish(eta_seconds)
    return (
        f'{truncated_name}  |  {status}  |  {speed} Mb/s  |  za {eta_str}  ({finish_str})'
    )


def format_batch_dialog_message(
        finished_count: int,
        batch_total: int,
        active_count: int,
        max_simultaneous: int,
        job_order: List[str],
        job_states: dict,
        max_simultaneous_setting: int,
) -> Tuple[int, str]:
    """Build full dialog text and overall percent from session snapshot."""
    header = format_batch_header(
        finished_count, batch_total, active_count, max_simultaneous_setting)

    progress_pairs = []
    active_running = []
    for job_id in job_order:
        state = job_states.get(job_id)
        if state is None:
            continue
        if state.get('status') == STATUS_RUNNING:
            active_running.append((job_id, state))

    if len(active_running) == 1:
        _jid, state = active_running[0]
        pct, file_msg = format_single_file_progress(
            state['progress_bytes'],
            state['total_bytes'],
            state['display_name'],
            state['start_time'],
        )
        overall_pct = compute_batch_progress_percent(
            finished_count, batch_total, [(state['progress_bytes'], state['total_bytes'])])
        return overall_pct, header + '\n' + file_msg

    if active_running:
        lines = []
        for _jid, state in active_running:
            lines.append(format_compact_file_progress(
                state['progress_bytes'],
                state['total_bytes'],
                state['display_name'],
                state['start_time'],
            ))
            progress_pairs.append((state['progress_bytes'], state['total_bytes']))
        body = '\n'.join(lines)
    else:
        body = 'Čekám na další soubor...' if finished_count < batch_total else ''

    overall_pct = compute_batch_progress_percent(
        finished_count, batch_total, progress_pairs)
    message = header + ('\n' + body if body else '')
    return overall_pct, message


def compute_batch_progress_percent(
        finished_count: int,
        batch_total: int,
        active_jobs_progress: List[Tuple[int, int]],
) -> int:
    if batch_total <= 0:
        return 0
    base = finished_count / batch_total
    in_flight = 0.0
    if active_jobs_progress:
        partials = []
        for downloaded, total in active_jobs_progress:
            if total > 0:
                partials.append(downloaded / total)
            elif downloaded > 0:
                partials.append(0.0)
        if partials:
            in_flight = sum(partials) / len(partials) / batch_total
    return min(100, int((base + in_flight) * 100))
