import os
import struct
import zlib

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

CONSOLE_URL = "https://www.dropbox.com/developers/apps"


class QRDialog(xbmcgui.WindowXMLDialog):
    image_path = ""
    message = ""

    def onInit(self):
        self.getControl(200).setImage(self.image_path)
        self.getControl(201).setText(self.message)

    def onClick(self, control_id):
        if control_id == 10:
            self.close()

    def onAction(self, action):
        if action.getId() in (10, 92):
            self.close()


def _addon_path():
    return xbmcaddon.Addon().getAddonInfo("path")


def _profile_dir():
    path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
    os.makedirs(path, exist_ok=True)
    return path


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _matrix_png(matrix, scale):
    width = len(matrix[0]) * scale
    rows = []
    black = b"\x00\x00\x00" * scale
    white = b"\xff\xff\xff" * scale
    for row in matrix:
        line = b"\x00" + b"".join(black if cell else white for cell in row)
        rows.extend([line] * scale)
    raw = b"".join(rows)
    height = len(matrix) * scale
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _png_bytes(url):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=4)
    code.add_data(url)
    code.make(fit=True)
    return _matrix_png(code.get_matrix(), 8)


def _write_png(url):
    destination = os.path.join(_profile_dir(), "qr-code.png")
    with open(destination, "wb") as handle:
        handle.write(_png_bytes(url))
    return destination


def show_qr(url, instruction):
    text = instruction or ""
    if url and url not in text:
        text = (text.rstrip() + "\n\n" + url).strip()
    image_path = None
    try:
        image_path = _write_png(url)
        dialog = QRDialog("DialogQR.xml", _addon_path(), "Default", "1080i")
        dialog.image_path = image_path
        dialog.message = text
        dialog.doModal()
        del dialog
    except Exception as exc:
        xbmc.log("[SyncBuild] QR code could not be shown: %s" % exc, xbmc.LOGINFO)
        xbmcgui.Dialog().textviewer("SyncBuild", text or url)
    finally:
        if image_path and os.path.isfile(image_path):
            try:
                os.remove(image_path)
            except OSError:
                pass
