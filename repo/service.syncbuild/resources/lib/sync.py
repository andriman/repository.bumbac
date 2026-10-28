import datetime
import traceback

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import dropbox_api
from resources.lib.bundle import pack, unpack, valid_skin_id
from resources.lib.history import (
    choose_newer,
    device_folder,
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
PART_IDS = ("skin", "shortcuts", "tmdb", "tmdb_auth", "sources", "favourites")


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
        record = {
            "id": snapshot["id"],
            "skin_id": skin_id,
            "skin_name": skin_name,
        }
        if snapshot.get("starred") is True:
            record["starred"] = True
        records.append(record)
    return records


def _describe(item):
    line = "%s | %s | %s | %s" % (
        item["name"],
        item.get("skin_name") or LEGACY_SKIN_NAME,
        display_time(item["id"]),
        item["device_id"],
    )
    if item.get("starred"):
        line = "* " + line
    if item.get("local"):
        line += " (this device)"
    return line


def choose_parts(skin_name):
    label = skin_name or LEGACY_SKIN_NAME
    labels = [
        "%s settings" % label,
        "%s shortcuts" % label,
        "TMDbHelper settings",
        "TMDbHelper sign-in",
        "Sources",
        "Favourites",
    ]
    picked = xbmcgui.Dialog().multiselect(
        "Overwrite",
        labels,
        preselect=[index for index, part in enumerate(PART_IDS) if part != "tmdb_auth"],
    )
    if not picked:
        return None
    return {PART_IDS[index] for index in picked}


def _remote_builds(client, profile, local_id):
    found = []
    for device in dropbox_api.list_profile_devices(client, profile):
        folder = device["device_id"]
        if folder == local_id:
            continue
        legacy = device["legacy"]
        try:
            manifest = dropbox_api.download_json(client, manifest_path(profile, folder, legacy))
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
            "path": snapshot_path(profile, folder, newest["id"], legacy),
            "skin_id": newest["skin_id"],
            "skin_name": newest["skin_name"],
            "profile": profile,
            "legacy": legacy,
        })
    newest = {}
    for item in found:
        current = newest.get(item["device_id"])
        if current is None or item["id"] > current["id"]:
            newest[item["device_id"]] = item
    return choose_newer(list(newest.values()), local_id, dropbox_api.last_marker())


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
            candidates = _remote_builds(client, dropbox_api.profile_name(), dropbox_api.device_id())
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
                    profile = dropbox_api.profile_name()
                    snapshot_id = _stamp()
                    dropbox_api.upload_bytes(client, snapshot_path(profile, local_id, snapshot_id), blob)
                    try:
                        manifest = dropbox_api.download_json(client, manifest_path(profile, local_id))
                    except Exception as exc:
                        if "not_found" not in str(exc):
                            raise
                        manifest = {}
                    existing = _snapshot_records(manifest if isinstance(manifest, dict) else {})
                    by_id = {record["id"]: record for record in existing}
                    kept, removed = kept_snapshot_ids(existing, snapshot_id, dropbox_api.setting_int("history", 3))
                    records = []
                    for kept_id in kept:
                        if kept_id == snapshot_id:
                            record = {
                                "id": snapshot_id,
                                "skin_id": skin_id,
                                "skin_name": skin_name,
                            }
                            if by_id.get(snapshot_id, {}).get("starred"):
                                record["starred"] = True
                            records.append(record)
                        else:
                            records.append(by_id[kept_id])
                    dropbox_api.upload_json(client, manifest_path(profile, local_id), {
                        "device_id": local_id,
                        "device_name": dropbox_api.device_name(),
                        "snapshots": records,
                    })
                    dropbox_api.set_last_marker(snapshot_id)
                    try:
                        folder = device_folder(profile, local_id)
                        for old_id in removed:
                            dropbox_api.delete_path(client, snapshot_path(profile, local_id, old_id))
                        for entry in dropbox_api.list_folder(client, folder):
                            name = getattr(entry, "name", "")
                            if not name.endswith(".zip"):
                                continue
                            old_id = name[:-4]
                            if old_id not in kept:
                                target = getattr(entry, "path_display", None) or snapshot_path(profile, local_id, old_id)
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


def _read_manifests(client, profile):
    found = []
    for device in dropbox_api.list_profile_devices(client, profile):
        folder = device["device_id"]
        legacy = device["legacy"]
        try:
            manifest = dropbox_api.download_json(client, manifest_path(profile, folder, legacy))
        except Exception as exc:
            dropbox_api.log("Skipped %s: %s" % (folder, exc))
            continue
        if isinstance(manifest, dict):
            found.append((folder, legacy, manifest))
    return found


def _all_snapshots(client, profile, local_id):
    rows = []
    for folder, legacy, manifest in _read_manifests(client, profile):
        name = manifest.get("device_name") or folder
        for snapshot in _snapshot_records(manifest):
            rows.append({
                "device_id": folder,
                "name": name,
                "id": snapshot["id"],
                "path": snapshot_path(profile, folder, snapshot["id"], legacy),
                "skin_id": snapshot["skin_id"],
                "skin_name": snapshot["skin_name"],
                "starred": bool(snapshot.get("starred")),
                "local": folder == local_id,
                "profile": profile,
                "legacy": legacy,
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


def _item_location(item):
    profile = item.get("profile")
    if not profile:
        raise ValueError("Profile is not valid")
    return profile, bool(item.get("legacy"))


def _delete_snapshot(item):
    if not valid_device(item.get("device_id")) or not valid_id(item.get("id")):
        raise ValueError("Snapshot is not valid")
    profile, legacy = _item_location(item)
    dialog = None
    try:
        dialog = _busy("Deleting snapshot")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        try:
            manifest = dropbox_api.download_json(client, manifest_path(profile, item["device_id"], legacy))
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
            dropbox_api.upload_json(client, manifest_path(profile, item["device_id"], legacy), {
                "device_id": item["device_id"],
                "device_name": item["name"],
                "snapshots": remaining,
            })
        else:
            dropbox_api.delete_path(client, manifest_path(profile, item["device_id"], legacy))
        dropbox_api.delete_path(client, snapshot_path(profile, item["device_id"], item["id"], legacy))
    finally:
        if dialog is not None:
            dialog.close()


def _wipe_device(client, profile, device_id, legacy):
    try:
        manifest = dropbox_api.download_json(client, manifest_path(profile, device_id, legacy))
    except Exception as exc:
        if "not_found" not in str(exc):
            raise
        manifest = {}
    for snapshot_id in _snapshot_ids(manifest):
        dropbox_api.delete_path(client, snapshot_path(profile, device_id, snapshot_id, legacy))
    dropbox_api.delete_path(client, manifest_path(profile, device_id, legacy))
    folder = device_folder(profile, device_id, legacy)
    for entry in dropbox_api.list_folder(client, folder):
        name = getattr(entry, "name", "")
        if name == "manifest.json" or name.endswith(".zip"):
            target = getattr(entry, "path_display", None) or "%s/%s" % (folder, name)
            dropbox_api.delete_path(client, target)


def _delete_device(item):
    device_id = item.get("device_id")
    if not valid_device(device_id):
        raise ValueError("Device is not valid")
    profile, _legacy = _item_location(item)
    dialog = None
    try:
        dialog = _busy("Deleting snapshots")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        locations = [
            device["legacy"]
            for device in dropbox_api.list_profile_devices(client, profile)
            if device["device_id"] == device_id
        ]
        if not locations:
            locations = [bool(item.get("legacy"))]
        for legacy in locations:
            _wipe_device(client, profile, device_id, legacy)
    finally:
        if dialog is not None:
            dialog.close()


def _confirm_star_delete(items):
    if len(items) == 1:
        item = items[0]
        message = "Do you really want to delete * %s?\n%s\n%s\n%s" % (
            item.get("skin_name") or LEGACY_SKIN_NAME,
            item.get("name") or "",
            item.get("device_id") or "",
            display_time(item["id"]),
        )
    else:
        lines = ["Do you really want to delete * builds?"]
        for item in items:
            lines.append("%s | %s | %s" % (
                item.get("name") or item.get("device_id") or "",
                item.get("skin_name") or LEGACY_SKIN_NAME,
                display_time(item["id"]),
            ))
        message = "\n".join(lines)
    return xbmcgui.Dialog().yesno("Saved builds", message)


def _set_star(item, starred):
    if not valid_device(item.get("device_id")) or not valid_id(item.get("id")):
        raise ValueError("Snapshot is not valid")
    profile, legacy = _item_location(item)
    dialog = None
    try:
        dialog = _busy("Saving")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        try:
            manifest = dropbox_api.download_json(client, manifest_path(profile, item["device_id"], legacy))
        except Exception as exc:
            if "not_found" not in str(exc):
                raise
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        snapshots = manifest.get("snapshots")
        if not isinstance(snapshots, list):
            raise ValueError("Snapshot was not found")
        updated = False
        for snapshot in snapshots:
            if isinstance(snapshot, dict) and snapshot.get("id") == item["id"]:
                if starred:
                    snapshot["starred"] = True
                else:
                    snapshot.pop("starred", None)
                updated = True
        if not updated:
            raise ValueError("Snapshot was not found")
        dropbox_api.upload_json(client, manifest_path(profile, item["device_id"], legacy), {
            "device_id": item["device_id"],
            "device_name": manifest.get("device_name") or item.get("name") or item["device_id"],
            "snapshots": snapshots,
        })
    finally:
        if dialog is not None:
            dialog.close()


def _manage_one(item, rows):
    star_label = "Remove *" if item.get("starred") else "Mark with *"
    choice = xbmcgui.Dialog().select(_describe(item), [
        "Reset this device to this build",
        star_label,
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
        _set_star(item, not item.get("starred"))
        dropbox_api.notify("Star removed" if item.get("starred") else "Build marked")
        return True
    if choice == 2:
        message = "Delete this snapshot?\n%s\n%s\n%s" % (
            item["name"],
            item["device_id"],
            display_time(item["id"]),
        )
        if not xbmcgui.Dialog().yesno("Saved builds", message):
            return True
        if item.get("starred") and not _confirm_star_delete([item]):
            return True
        _delete_snapshot(item)
        dropbox_api.notify("Snapshot deleted")
        return True
    message = "Delete every snapshot for this device?\n%s\n%s" % (item["name"], item["device_id"])
    if not xbmcgui.Dialog().yesno("Saved builds", message):
        return True
    starred = [
        row for row in rows
        if row.get("device_id") == item.get("device_id") and row.get("starred")
    ]
    if starred and not _confirm_star_delete(starred):
        return True
    _delete_device(item)
    dropbox_api.notify("Snapshots deleted")
    return True


def _count_label(count, singular, plural):
    return "%d %s" % (count, singular if count == 1 else plural)


def manage_builds(profile=None):
    if not dropbox_api.authorized():
        dropbox_api.notify("Authorize Dropbox first", error=True)
        return False
    try:
        profile = dropbox_api.profile_name() if profile is None else profile
    except Exception as exc:
        dropbox_api.show_failure(dropbox_api.failure_text(exc, "Profile name is not valid"))
        return False
    heading = "Saved builds — %s" % profile
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
                rows = _all_snapshots(client, profile, dropbox_api.device_id())
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            notice = (dropbox_api.failure_text(exc, "Could not load builds"), True)
        finally:
            if dialog is not None:
                dialog.close()
        if notice:
            dropbox_api.show_failure(notice[0])
            return False
        if not rows:
            dropbox_api.notify("No saved builds")
            return True
        index = xbmcgui.Dialog().select(heading, [_describe(item) for item in rows])
        if index is None or index < 0:
            return True
        try:
            if not _manage_one(rows[index], rows):
                return False
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            dropbox_api.show_failure(dropbox_api.failure_text(exc, "Could not update the saved builds"))
            return False


def browse_profiles():
    if not dropbox_api.authorized():
        dropbox_api.notify("Authorize Dropbox first", error=True)
        return
    while True:
        dialog = None
        notice = None
        names = []
        lines = []
        try:
            dialog = _busy("Loading profiles")
            client = dropbox_api.get_client()
            if client is None:
                notice = ("Authorize Dropbox first", True)
            else:
                for name in dropbox_api.list_profile_names(client):
                    devices = dropbox_api.list_profile_devices(client, name)
                    device_count = len({device["device_id"] for device in devices})
                    snapshots = 0
                    for _folder, _legacy, manifest in _read_manifests(client, name):
                        snapshots += len(_snapshot_records(manifest))
                    names.append(name)
                    lines.append("%s | %s | %s" % (
                        name,
                        _count_label(device_count, "device", "devices"),
                        _count_label(snapshots, "snapshot", "snapshots"),
                    ))
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            notice = (dropbox_api.failure_text(exc, "Could not load profiles"), True)
        finally:
            if dialog is not None:
                dialog.close()
        if notice:
            dropbox_api.show_failure(notice[0])
            return
        if not lines:
            dropbox_api.notify("No profiles")
            return
        index = xbmcgui.Dialog().select("Other profiles", lines)
        if index is None or index < 0:
            return
        if manage_builds(names[index]) is False:
            return
