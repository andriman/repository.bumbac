import requests
import xbmc
import xbmcgui

from common import _ADDON_NAME, ICON_BIN_DELETE, ICON_COPY, ICON_DOWNLOAD, ICON_QR, ICON_REFRESH, addon, get_headers
from downloads.download_actions import (
    download_direct,
    enqueue_background_download,
    enqueue_to_queue_only,
)
from downloads.stream_select import pick_stream
from providers.UniversalProvider import UniversalProvider
from utils.action_menu import open_icon_action_menu
from utils.ClipboardUtils import ClipboardUtils
from utils.utils import dprint, get_url

_provider = UniversalProvider()


def show_video_actions_menu(_url: str, vid_url: str) -> None:
    def _play_force_selector() -> None:
        xbmc.executebuiltin(
            'RunPlugin({})'.format(get_url(_url, action='select_stream', link=vid_url)))

    def _copy_url() -> None:
        ClipboardUtils.copy_to_clipboard(vid_url)
        xbmcgui.Dialog().notification(
            _ADDON_NAME, 'URL zkopírována',
            xbmcgui.NOTIFICATION_INFO, 2500, sound=False)

    def _save_library() -> None:
        xbmc.executebuiltin('RunPlugin({})'.format(get_url(_url, action='library', url=vid_url)))

    def _show_qr() -> None:
        res = requests.get(vid_url, headers=get_headers(), allow_redirects=True)
        streams, _subs = _provider.get_streams_data(res.url, res.content)
        if streams is None or len(streams) == 0:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, 'Streamy nenalezeny',
                xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
            return
        selected = pick_stream(streams)
        if selected is None:
            return
        qr_link = 'https://quickchart.io/qr?text=' + selected.path.replace('&', '%26')
        dprint('qr: ' + qr_link)
        xbmc.executebuiltin('ShowPicture(' + qr_link + ')')

    actions = [
        ('Vybrat stream', ICON_REFRESH, _play_force_selector),
        ('Kopírovat URL', ICON_COPY, _copy_url),
        ('Uložit do knihovny', ICON_DOWNLOAD, _save_library),
        ('Stáhnout', ICON_DOWNLOAD, lambda: download_direct(vid_url)),
        ('Přidat do fronty', ICON_DOWNLOAD, lambda: enqueue_to_queue_only(vid_url)),
        ('Stáhnout na pozadí', ICON_DOWNLOAD, lambda: enqueue_background_download(vid_url)),
        ('QR kód streamu', ICON_QR, _show_qr),
    ]
    open_icon_action_menu('Akce k videu', actions)
