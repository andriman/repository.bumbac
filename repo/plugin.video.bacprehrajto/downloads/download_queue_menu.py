import xbmc
import xbmcgui
import xbmcplugin

from common import _ADDON_NAME, ICON_BIN_DELETE, ICON_DOWNLOAD, ICON_REFRESH, icons_path, set_list_icon
from downloads.download_queue import (
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    clear_queue_halt,
    clear_download_queue,
    get_job,
    get_queue_halt_reason,
    is_service_enabled,
    load_jobs,
    queue_summary,
    remove_job,
    request_cancel,
    start_download_service,
    stop_download_service,
)
from downloads.download_queue_batch import download_queue_blocking
from downloads.downloads_utils import format_list_size
from utils.StrUtils import convert_size
from utils.action_menu import open_icon_action_menu
from utils.utils import apply_context_menu_items, build_queue_job_context_menu_items, get_url


def _status_label(status: str) -> str:
    labels = {
        STATUS_PENDING: 'Ve frontě',
        STATUS_RUNNING: 'Stahuje se',
        STATUS_DONE: 'Hotovo',
        STATUS_FAILED: 'Chyba',
        STATUS_CANCELED: 'Zrušeno',
    }
    return labels.get(status, status)


def _progress_label(job) -> str:
    if job.status == STATUS_RUNNING and job.total_bytes > 0:
        pct = int(job.progress_bytes * 100 / job.total_bytes)
        return f'{pct}% ({convert_size(job.progress_bytes)} / {convert_size(job.total_bytes)})'
    if job.status == STATUS_DONE and job.total_bytes > 0:
        return format_list_size(job.total_bytes)
    if job.error:
        return job.error
    return _status_label(job.status)


def _add_action_item(_handle, _url: str, label: str, action: str, icon_filename: str) -> None:
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'false')
    set_list_icon(item, icon_filename)
    xbmcplugin.addDirectoryItem(_handle, get_url(_url, action=action), item, False)


def show_download_queue_menu(_handle, _url: str) -> None:
    jobs = load_jobs()
    summary = queue_summary()
    active = summary['pending'] + summary['running']
    halt_reason = get_queue_halt_reason()
    service_running = is_service_enabled()

    xbmcplugin.setContent(_handle, 'files')

    service_status = 'aktivní' if service_running else 'zastavena'
    header_label = f'Fronta stahování ({active} aktivních / {summary["total"]} celkem) — služba {service_status}'
    if halt_reason:
        header_label = f'Fronta zastavena — {halt_reason} — služba {service_status}'
    header = xbmcgui.ListItem(label=header_label)
    header.setProperty('IsPlayable', 'false')
    set_list_icon(header, ICON_DOWNLOAD)
    xbmcplugin.addDirectoryItem(_handle, '', header, False)

    if service_running:
        stop_item = xbmcgui.ListItem(label='Zastavit službu stahování')
        stop_item.setProperty('IsPlayable', 'false')
        stop_item.setArt({'icon': icons_path + 'prehrajto.png'})
        xbmcplugin.addDirectoryItem(
            _handle, get_url(_url, action='download_service_stop'), stop_item, False)
    else:
        start_item = xbmcgui.ListItem(label='Spustit službu stahování')
        start_item.setProperty('IsPlayable', 'false')
        start_item.setArt({'icon': icons_path + 'prehrajto.png'})
        xbmcplugin.addDirectoryItem(
            _handle, get_url(_url, action='download_service_start'), start_item, False)

    if halt_reason:
        _add_action_item(_handle, _url, 'Obnovit frontu stahování', 'download_queue_resume', ICON_REFRESH)

    has_downloadable = any(
        job.status in (STATUS_PENDING, STATUS_FAILED) and not job.cancel_requested
        for job in jobs
    )
    if has_downloadable:
        _add_action_item(_handle, _url, 'Stáhnout vše teď', 'download_queue_now', ICON_DOWNLOAD)

    if jobs:
        _add_action_item(_handle, _url, 'Smazat frontu', 'download_queue_clear', ICON_BIN_DELETE)

    if not jobs:
        empty = xbmcgui.ListItem(label='Fronta je prázdná')
        empty.setProperty('IsPlayable', 'false')
        xbmcplugin.addDirectoryItem(_handle, '', empty, False)
        xbmcplugin.endOfDirectory(_handle)
        return

    for job in sorted(jobs, key=lambda item: item.added_at, reverse=True):
        label = job.target_filename or job.display_name or job.page_url
        label2 = _progress_label(job)
        item = xbmcgui.ListItem(label=label, label2=label2)
        item.setProperty('IsPlayable', 'false')
        item.setInfo('video', {
            'title': label,
            'plot': f'{_status_label(job.status)} | {job.provider}\n{job.page_url}',
        })
        set_list_icon(item, ICON_DOWNLOAD)

        apply_context_menu_items(item, build_queue_job_context_menu_items(_url, job.id, job))

        xbmcplugin.addDirectoryItem(_handle, '', item, False)

    xbmcplugin.endOfDirectory(_handle)


def handle_queue_job_actions(_url: str, job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    actions = []
    if job.status in (STATUS_PENDING, STATUS_RUNNING):
        actions.append(('Zrušit', ICON_BIN_DELETE, lambda: handle_download_cancel(_url, job_id)))
    if job.status in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELED):
        actions.append((
            'Odstranit z fronty',
            ICON_BIN_DELETE,
            lambda: handle_download_remove(_url, job_id),
        ))
    open_icon_action_menu('Akce ve frontě', actions)


def handle_download_cancel(_url: str, job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    request_cancel(job_id)
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Stahování zrušeno',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    xbmc.executebuiltin(f'Container.Update({get_url(_url, action="listing_download_queue")},replace)')


def handle_download_remove(_url: str, job_id: str) -> None:
    remove_job(job_id)
    xbmc.executebuiltin(f'Container.Update({get_url(_url, action="listing_download_queue")},replace)')


def handle_download_queue_resume(_url: str) -> None:
    clear_queue_halt()
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Fronta stahování obnovena',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    xbmc.executebuiltin(f'Container.Update({get_url(_url, action="listing_download_queue")},replace)')


def handle_download_service_stop(_url: str) -> None:
    running_count = stop_download_service()
    message = 'Služba stahování zastavena'
    if running_count:
        message = f'{message} ({running_count} stahování rušeno)'
    xbmcgui.Dialog().notification(
        _ADDON_NAME, message,
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    xbmc.executebuiltin(f'Container.Update({get_url(_url, action="listing_download_queue")},replace)')


def handle_download_service_start(_url: str) -> None:
    start_download_service()
    xbmcgui.Dialog().notification(
        _ADDON_NAME, 'Služba stahování spuštěna',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    xbmc.executebuiltin(f'Container.Update({get_url(_url, action="listing_download_queue")},replace)')


def handle_download_queue_now(_url: str) -> None:
    download_queue_blocking()
    xbmc.executebuiltin(f'Container.Update({get_url(_url, action="listing_download_queue")},replace)')


def handle_download_queue_clear(_url: str) -> None:
    jobs = load_jobs()
    if not jobs:
        return
    active = sum(1 for job in jobs if job.status in (STATUS_PENDING, STATUS_RUNNING))
    message = f'Smazat celou frontu stahování ({len(jobs)} položek)?'
    if active:
        message = f'{message}\n({active} aktivních bude zrušeno)'
    if not xbmcgui.Dialog().yesno(_ADDON_NAME, message):
        return
    removed = clear_download_queue()
    xbmcgui.Dialog().notification(
        _ADDON_NAME, f'Fronta smazána ({removed} položek)',
        xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    xbmc.executebuiltin(f'Container.Update({get_url(_url, action="listing_download_queue")},replace)')
