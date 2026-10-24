import datetime
import traceback

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import dropbox_api
from resources.lib.bundle import pack, unpack, valid_skin_id
from resources.lib.history import (
    ROOT,
    choose_newer,
    display_time,
    kept_snapshot_ids,
    manifest_path,
    snapshot_path,
    valid_device,
    valid_id,
)


def _busy(message):
    dialog = xbmcgui.DialogProgressBG()
    dialog.create("SyncBuild", message)
    return dialog


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


LEGACY_SKIN_ID = "skin.arctic.fuse.3"
LEGACY_SKIN_NAME = "Arctic Fuse 3"
PART_IDS = ("skin", "shortcuts", "tmdb", "sources", "favourites")


def current_skin():
    skin_id = xbmc.getSkinDir() or ""
    if not valid_skin_id(skin_id):
        return "", ""
    try:
        skin_name = xbmcaddon.Addon(skin_id).getAddonInfo("name")
    except Exception:
        skin_name = ""
    return skin_id, skin_name or skin_id


def _skin_fields(snapshot):
    skin_id = snapshot.get("skin_id") if isinstance(snapshot, dict) else None
    skin_name = snapshot.get("skin_name") if isinstance(snapshot, dict) else None
    if not valid_skin_id(skin_id):
        return LEGACY_SKIN_ID, LEGACY_SKIN_NAME
    return skin_id, skin_name or skin_id


def _snapshot_records(manifest):
    records = []
    if not isinstance(manifest, dict):
        return records
    for snapshot in manifest.get("snapshots") or []:
        if not isinstance(snapshot, dict) or not valid_id(snapshot.get("id")):
            continue
        skin_id, skin_name = _skin_fields(snapshot)
        records.append({
            "id": snapshot["id"],
            "skin_id": skin_id,
            "skin_name": skin_name,
        })
    return records


def _describe(item):
    line = "%s | %s | %s | %s" % (
        item["name"],
        item.get("skin_name") or LEGACY_SKIN_NAME,
        display_time(item["id"]),
        item["device_id"],
    )
    if item.get("local"):
        line += " (this device)"
    return line


def choose_parts(skin_name):
    label = skin_name or LEGACY_SKIN_NAME
    labels = [
        "%s settings" % label,
        "%s shortcuts" % label,
        "TMDbHelper settings",
        "Sources",
        "Favourites",
    ]
    picked = xbmcgui.Dialog().multiselect(
        "Overwrite",
        labels,
        preselect=list(range(len(labels))),
    )
    if not picked:
        return None
    return {PART_IDS[index] for index in picked}


def _remote_builds(client, local_id):
    found = []
    for folder in dropbox_api.list_device_folders(client):
        if folder == local_id:
            continue
        try:
            manifest = dropbox_api.download_json(client, manifest_path(folder))
        except Exception as exc:
            dropbox_api.log("Skipped %s: %s" % (folder, exc))
            continue
        if not isinstance(manifest, dict):
            continue
        records = _snapshot_records(manifest)
        if not records:
            continue
        newest = max(records, key=lambda record: record["id"])
        found.append({
            "device_id": folder,
            "name": manifest.get("device_name") or folder,
            "id": newest["id"],
            "path": snapshot_path(folder, newest["id"]),
            "skin_id": newest["skin_id"],
            "skin_name": newest["skin_name"],
        })
    return choose_newer(found, local_id, dropbox_api.last_marker())


def _apply(client, chosen, parts):
    blob = dropbox_api.download_bytes(client, chosen["path"])
    written = unpack(
        blob,
        dropbox_api.translated("special://userdata"),
        dropbox_api.translated("special://home"),
        rebuild_stamp=datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S"),
        parts=parts,
        skin_id=chosen.get("skin_id") or LEGACY_SKIN_ID,
    )
    dropbox_api.set_last_marker(chosen["id"])
    dropbox_api.log("Restored %s files from %s" % (len(written), chosen["device_id"]))
    return chosen["name"]


def _prompt(candidates, monitor=None):
    if monitor is not None and monitor.abortRequested():
        return None
    if len(candidates) == 1:
        item = candidates[0]
        message = "%s\n%s\n%s\n%s\nReset this device to that build?" % (
            item["name"],
            item.get("skin_name") or LEGACY_SKIN_NAME,
            item["device_id"],
            display_time(item["id"]),
        )
        if xbmcgui.Dialog().yesno("Newer build", message):
            return item
        return None
    index = xbmcgui.Dialog().select("Newer builds", [_describe(item) for item in candidates])
    if index is None or index < 0:
        return None
    return candidates[index]


def check_newer(interactive, automatic=False, monitor=None):
    if automatic and not dropbox_api.setting_bool("auto_check", True):
        return
    if not dropbox_api.authorized():
        if interactive and not automatic:
            dropbox_api.notify("Authorize Dropbox first", error=True)
        return
    dialog = None
    candidates = []
    notice = None
    try:
        dialog = _busy("Checking Dropbox")
        client = dropbox_api.get_client()
        if client is None:
            notice = ("Authorize Dropbox first", True)
        else:
            candidates = _remote_builds(client, dropbox_api.device_id())
    except Exception as exc:
        dropbox_api.log(traceback.format_exc())
        notice = (dropbox_api.failure_text(exc, "Could not check Dropbox"), True)
    finally:
        if dialog is not None:
            dialog.close()
    if notice:
        if interactive and not automatic:
            dropbox_api.show_failure(notice[0])
        return

    if not candidates:
        if interactive and not automatic:
            dropbox_api.notify("This device is up to date")
        return
    chosen = _prompt(candidates, monitor)
    if chosen is None:
        return
    parts = choose_parts(chosen.get("skin_name"))
    if not parts:
        return
    dialog = None
    restored = None
    notice = None
    try:
        dialog = _busy("Restoring build")
        client = dropbox_api.get_client()
        if client is None:
            notice = ("Authorize Dropbox first", True)
        else:
            restored = _apply(client, chosen, parts)
    except Exception as exc:
        dropbox_api.log(traceback.format_exc())
        notice = (dropbox_api.failure_text(exc, "Could not restore the build"), True)
    finally:
        if dialog is not None:
            dialog.close()
    if notice:
        dropbox_api.show_failure(notice[0])
        return
    if restored:
        dropbox_api.notify("Build reset from %s. Reloading the skin." % restored)
        xbmc.executebuiltin("ReloadSkin()")


def upload_current():
    if not dropbox_api.authorized():
        dropbox_api.notify("Authorize Dropbox first", error=True)
        return
    dialog = None
    notice = None
    try:
        dialog = _busy("Uploading build")
        client = dropbox_api.get_client()
        if client is None:
            notice = ("Authorize Dropbox first", True)
        else:
            skin_id, skin_name = current_skin()
            if not skin_id:
                notice = ("Kodi has no skin selected", True)
            else:
                blob = pack(
                    dropbox_api.translated("special://userdata"),
                    dropbox_api.translated("special://home"),
                    skin_id,
                )
                if not blob:
                    notice = ("No build files to upload", True)
                else:
                    local_id = dropbox_api.device_id()
                    snapshot_id = _stamp()
                    dropbox_api.upload_bytes(client, snapshot_path(local_id, snapshot_id), blob)
                    try:
                        manifest = dropbox_api.download_json(client, manifest_path(local_id))
                    except Exception as exc:
                        if "not_found" not in str(exc):
                            raise
                        manifest = {}
                    existing = _snapshot_records(manifest if isinstance(manifest, dict) else {})
                    by_id = {record["id"]: record for record in existing}
                    kept, removed = kept_snapshot_ids(list(by_id), snapshot_id, dropbox_api.setting_int("history", 3))
                    records = []
                    for kept_id in kept:
                        if kept_id == snapshot_id:
                            records.append({
                                "id": snapshot_id,
                                "skin_id": skin_id,
                                "skin_name": skin_name,
                            })
                        else:
                            records.append(by_id[kept_id])
                    dropbox_api.upload_json(client, manifest_path(local_id), {
                        "device_id": local_id,
                        "device_name": dropbox_api.device_name(),
                        "snapshots": records,
                    })
                    dropbox_api.set_last_marker(snapshot_id)
                    try:
                        for old_id in removed:
                            dropbox_api.delete_path(client, snapshot_path(local_id, old_id))
                        for entry in dropbox_api.list_folder(client, "%s/%s" % (ROOT, local_id)):
                            name = getattr(entry, "name", "")
                            if not name.endswith(".zip"):
                                continue
                            old_id = name[:-4]
                            if old_id not in kept:
                                target = getattr(entry, "path_display", None) or snapshot_path(local_id, old_id)
                                dropbox_api.delete_path(client, target)
                    except Exception:
                        dropbox_api.log(traceback.format_exc())
                    notice = ("Uploaded %s %s" % (skin_name, display_time(snapshot_id)), False)
    except Exception as exc:
        dropbox_api.log(traceback.format_exc())
        notice = (dropbox_api.failure_text(exc, "Could not upload the build"), True)
    finally:
        if dialog is not None:
            dialog.close()
    if notice:
        if notice[1]:
            dropbox_api.show_failure(notice[0])
        else:
            dropbox_api.notify(notice[0])


def startup_check(monitor):
    check_newer(interactive=True, automatic=True, monitor=monitor)


def _read_manifests(client):
    found = []
    for folder in dropbox_api.list_device_folders(client):
        try:
            manifest = dropbox_api.download_json(client, manifest_path(folder))
        except Exception as exc:
            dropbox_api.log("Skipped %s: %s" % (folder, exc))
            continue
        if isinstance(manifest, dict):
            found.append((folder, manifest))
    return found


def _all_snapshots(client, local_id):
    rows = []
    for folder, manifest in _read_manifests(client):
        name = manifest.get("device_name") or folder
        for snapshot in _snapshot_records(manifest):
            rows.append({
                "device_id": folder,
                "name": name,
                "id": snapshot["id"],
                "path": snapshot_path(folder, snapshot["id"]),
                "skin_id": snapshot["skin_id"],
                "skin_name": snapshot["skin_name"],
                "local": folder == local_id,
            })
    rows.sort(key=lambda item: item["id"], reverse=True)
    return rows


def _restore_saved(item, parts):
    dialog = None
    notice = None
    restored = None
    try:
        dialog = _busy("Restoring build")
        client = dropbox_api.get_client()
        if client is None:
            notice = ("Authorize Dropbox first", True)
        else:
            restored = _apply(client, item, parts)
    except Exception as exc:
        dropbox_api.log(traceback.format_exc())
        notice = (dropbox_api.failure_text(exc, "Could not restore the build"), True)
    finally:
        if dialog is not None:
            dialog.close()
    if notice:
        dropbox_api.show_failure(notice[0])
        return False
    if restored:
        dropbox_api.notify("Build reset from %s. Reloading the skin." % restored)
        xbmc.executebuiltin("ReloadSkin()")
        return True
    return False


def _snapshot_ids(manifest):
    if not isinstance(manifest, dict):
        return []
    return [
        snapshot.get("id")
        for snapshot in (manifest.get("snapshots") or [])
        if isinstance(snapshot, dict) and valid_id(snapshot.get("id"))
    ]


def _delete_snapshot(item):
    if not valid_device(item.get("device_id")) or not valid_id(item.get("id")):
        raise ValueError("Snapshot is not valid")
    dialog = None
    try:
        dialog = _busy("Deleting snapshot")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        try:
            manifest = dropbox_api.download_json(client, manifest_path(item["device_id"]))
        except Exception as exc:
            if "not_found" not in str(exc):
                raise
            manifest = {}
        remaining = [
            record for record in _snapshot_records(manifest)
            if record["id"] != item["id"]
        ]
        remaining.sort(key=lambda record: record["id"], reverse=True)
        if remaining:
            dropbox_api.upload_json(client, manifest_path(item["device_id"]), {
                "device_id": item["device_id"],
                "device_name": item["name"],
                "snapshots": remaining,
            })
        else:
            dropbox_api.delete_path(client, manifest_path(item["device_id"]))
        dropbox_api.delete_path(client, snapshot_path(item["device_id"], item["id"]))
    finally:
        if dialog is not None:
            dialog.close()


def _delete_device(item):
    device_id = item.get("device_id")
    if not valid_device(device_id):
        raise ValueError("Device is not valid")
    dialog = None
    try:
        dialog = _busy("Deleting snapshots")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        try:
            manifest = dropbox_api.download_json(client, manifest_path(device_id))
        except Exception as exc:
            if "not_found" not in str(exc):
                raise
            manifest = {}
        for snapshot_id in _snapshot_ids(manifest):
            dropbox_api.delete_path(client, snapshot_path(device_id, snapshot_id))
        dropbox_api.delete_path(client, manifest_path(device_id))
        for entry in dropbox_api.list_folder(client, "%s/%s" % (ROOT, device_id)):
            name = getattr(entry, "name", "")
            if name == "manifest.json" or name.endswith(".zip"):
                target = getattr(entry, "path_display", None) or "%s/%s/%s" % (ROOT, device_id, name)
                dropbox_api.delete_path(client, target)
    finally:
        if dialog is not None:
            dialog.close()


def _manage_one(item):
    choice = xbmcgui.Dialog().select(_describe(item), [
        "Reset this device to this build",
        "Delete this snapshot",
        "Delete all snapshots for this device",
    ])
    if choice is None or choice < 0:
        return True
    if choice == 0:
        parts = choose_parts(item.get("skin_name"))
        if not parts:
            return True
        return not _restore_saved(item, parts)
    if choice == 1:
        message = "Delete this snapshot?\n%s\n%s\n%s" % (
            item["name"],
            item["device_id"],
            display_time(item["id"]),
        )
        if not xbmcgui.Dialog().yesno("Saved builds", message):
            return True
        _delete_snapshot(item)
        dropbox_api.notify("Snapshot deleted")
        return True
    message = "Delete every snapshot for this device?\n%s\n%s" % (item["name"], item["device_id"])
    if not xbmcgui.Dialog().yesno("Saved builds", message):
        return True
    _delete_device(item)
    dropbox_api.notify("Snapshots deleted")
    return True


def manage_builds():
    if not dropbox_api.authorized():
        dropbox_api.notify("Authorize Dropbox first", error=True)
        return
    while True:
        dialog = None
        notice = None
        rows = []
        try:
            dialog = _busy("Loading builds")
            client = dropbox_api.get_client()
            if client is None:
                notice = ("Authorize Dropbox first", True)
            else:
                rows = _all_snapshots(client, dropbox_api.device_id())
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            notice = (dropbox_api.failure_text(exc, "Could not load builds"), True)
        finally:
            if dialog is not None:
                dialog.close()
        if notice:
            dropbox_api.show_failure(notice[0])
            return
        if not rows:
            dropbox_api.notify("No saved builds")
            return
        index = xbmcgui.Dialog().select("Saved builds", [_describe(item) for item in rows])
        if index is None or index < 0:
            return
        try:
            if not _manage_one(rows[index]):
                return
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            dropbox_api.show_failure(dropbox_api.failure_text(exc, "Could not update the saved builds"))
