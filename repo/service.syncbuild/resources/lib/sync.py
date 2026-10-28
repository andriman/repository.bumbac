import datetime
import traceback

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import dropbox_api
from resources.lib.bundle import pack, unpack, valid_skin_id
from resources.lib.history import (
    DEFAULT_PROFILE,
    choose_newer,
    device_folder,
    display_time,
    kept_snapshot_ids,
    manifest_path,
    snapshot_path,
    valid_device,
    valid_id,
    valid_skin_id,
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


def default_part_indexes(same_skin):
    if same_skin:
        return [index for index, part in enumerate(PART_IDS) if part != "tmdb_auth"]
    return [index for index, part in enumerate(PART_IDS) if part in ("tmdb", "sources", "favourites")]


def choose_parts(skin_name, same_skin=True):
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
        preselect=default_part_indexes(same_skin),
    )
    if not picked:
        return None
    return {PART_IDS[index] for index in picked}


def _place_skin(place, skin_id):
    if place == "skin":
        return skin_id
    return None


def _manifest_at(profile, device_id, place, skin_id):
    return manifest_path(profile, device_id, place == "root", _place_skin(place, skin_id))


def _snapshot_at(profile, device_id, snapshot_id, place, skin_id):
    return snapshot_path(profile, device_id, snapshot_id, place == "root", _place_skin(place, skin_id))


def _load_manifest(client, profile, device_id, place, skin_id, strict=False):
    try:
        manifest = dropbox_api.download_json(client, _manifest_at(profile, device_id, place, skin_id))
    except Exception as exc:
        if "not_found" in str(exc):
            return {}
        if strict:
            raise
        dropbox_api.log("Skipped %s: %s" % (device_id, exc))
        return {}
    return manifest if isinstance(manifest, dict) else {}


def _records_for_skin(manifest, skin_id):
    return [record for record in _snapshot_records(manifest) if record["skin_id"] == skin_id]


def _remote_builds(client, profile, local_id, skin_id):
    found = []
    for device in dropbox_api.list_skin_devices(client, profile, skin_id):
        folder = device["device_id"]
        if folder == local_id:
            continue
        place = device["place"]
        manifest = _load_manifest(client, profile, folder, place, skin_id)
        records = _records_for_skin(manifest, skin_id)
        if not records:
            continue
        newest = max(records, key=lambda record: record["id"])
        found.append({
            "device_id": folder,
            "name": manifest.get("device_name") or folder,
            "id": newest["id"],
            "path": _snapshot_at(profile, folder, newest["id"], place, skin_id),
            "skin_id": newest["skin_id"],
            "skin_name": newest["skin_name"],
            "profile": profile,
            "place": place,
        })
    newest = {}
    for item in found:
        current = newest.get(item["device_id"])
        if current is None or item["id"] > current["id"]:
            newest[item["device_id"]] = item
    return choose_newer(
        list(newest.values()),
        local_id,
        dropbox_api.last_marker(),
        dropbox_api.ignored_ids(),
    )


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


def _startup_choice(index, candidates):
    if index is None or index < 0:
        return None
    if index < len(candidates):
        return candidates[index]
    if index == len(candidates):
        return ("ignore", [item["id"] for item in candidates])
    return ("disable", None)


def _prompt(candidates, monitor=None, automatic=False):
    if monitor is not None and monitor.abortRequested():
        return None
    if automatic and len(candidates) == 1:
        item = candidates[0]
        index = xbmcgui.Dialog().select("Newer build", [
            "Reset to this build: %s" % _describe(item),
            "Not now",
            "Ignore this build",
            "Turn off automatic checks",
        ])
        if index == 0:
            return item
        if index == 2:
            return ("ignore", [item["id"]])
        if index == 3:
            return ("disable", None)
        return None
    if not automatic and len(candidates) == 1:
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
    labels = [_describe(item) for item in candidates]
    if automatic:
        labels.extend(["Ignore these builds", "Turn off automatic checks"])
    index = xbmcgui.Dialog().select("Newer builds", labels)
    if not automatic:
        if index is None or index < 0:
            return None
        return candidates[index]
    return _startup_choice(index, candidates)


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
            skin_id, _skin_name = current_skin()
            if not skin_id:
                notice = ("Kodi has no skin selected", True)
            else:
                candidates = _remote_builds(
                    client,
                    dropbox_api.profile_name(),
                    dropbox_api.device_id(),
                    skin_id,
                )
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
    chosen = _prompt(candidates, monitor, automatic=automatic)
    if chosen is None:
        return
    if isinstance(chosen, tuple):
        action, snapshot_ids = chosen
        if action == "ignore":
            dropbox_api.ignore_snapshots(snapshot_ids)
            if len(snapshot_ids) == 1:
                dropbox_api.notify("This build will not be offered again")
            else:
                dropbox_api.notify("These builds will not be offered again")
        elif action == "disable":
            dropbox_api.set_setting("auto_check", "false")
            dropbox_api.notify("Automatic checks are off")
        return
    active_id, _active_name = current_skin()
    parts = choose_parts(chosen.get("skin_name"), same_skin=chosen.get("skin_id") == active_id)
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
                    dropbox_api.upload_bytes(
                        client,
                        snapshot_path(profile, local_id, snapshot_id, skin_id=skin_id),
                        blob,
                    )
                    try:
                        manifest = dropbox_api.download_json(client, manifest_path(profile, local_id, skin_id=skin_id))
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
                    dropbox_api.upload_json(client, manifest_path(profile, local_id, skin_id=skin_id), {
                        "device_id": local_id,
                        "device_name": dropbox_api.device_name(),
                        "snapshots": records,
                    })
                    dropbox_api.set_last_marker(snapshot_id)
                    try:
                        folder = device_folder(profile, local_id, skin_id=skin_id)
                        for old_id in removed:
                            dropbox_api.delete_path(client, snapshot_path(profile, local_id, old_id, skin_id=skin_id))
                        for entry in dropbox_api.list_folder(client, folder):
                            name = getattr(entry, "name", "")
                            if not name.endswith(".zip"):
                                continue
                            old_id = name[:-4]
                            if old_id not in kept:
                                target = getattr(entry, "path_display", None) or snapshot_path(
                                    profile, local_id, old_id, skin_id=skin_id
                                )
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


def _all_snapshots(client, profile, skin_id, local_id):
    rows = []
    seen = set()
    devices = dropbox_api.list_skin_devices(client, profile, skin_id)
    devices.sort(key=lambda device: 0 if device["place"] == "skin" else 1)
    for device in devices:
        folder = device["device_id"]
        place = device["place"]
        manifest = _load_manifest(client, profile, folder, place, skin_id)
        name = manifest.get("device_name") or folder
        for snapshot in _records_for_skin(manifest, skin_id):
            key = (folder, snapshot["id"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "device_id": folder,
                "name": name,
                "id": snapshot["id"],
                "path": _snapshot_at(profile, folder, snapshot["id"], place, skin_id),
                "skin_id": snapshot["skin_id"],
                "skin_name": snapshot["skin_name"],
                "starred": bool(snapshot.get("starred")),
                "local": folder == local_id,
                "profile": profile,
                "place": place,
            })
    rows.sort(key=lambda item: item["id"], reverse=True)
    return rows


def _discover_skins(client, profile):
    found = {}

    def add(skin_id, skin_name):
        if not valid_skin_id(skin_id):
            return
        name = skin_name or skin_id
        current = found.get(skin_id)
        if current is None or current == skin_id:
            found[skin_id] = name

    for skin_id in dropbox_api.list_skin_folders(client, profile):
        add(skin_id, skin_id)
    for device in dropbox_api.list_legacy_devices(client, profile):
        manifest = _load_manifest(client, profile, device["device_id"], device["place"], None)
        for record in _snapshot_records(manifest):
            add(record["skin_id"], record["skin_name"])
    for skin_id in list(found):
        for device in dropbox_api.list_skin_devices(client, profile, skin_id):
            if device["place"] != "skin":
                continue
            manifest = _load_manifest(client, profile, device["device_id"], "skin", skin_id)
            records = _records_for_skin(manifest, skin_id)
            if records:
                add(skin_id, records[0]["skin_name"])
                break
    return sorted(found.items(), key=lambda item: item[1].lower())


def _profile_usage(client, profile):
    device_ids = set()
    snapshots = 0
    for device in dropbox_api.list_legacy_devices(client, profile):
        device_ids.add(device["device_id"])
        manifest = _load_manifest(client, profile, device["device_id"], device["place"], None)
        snapshots += len(_snapshot_records(manifest))
    for skin_id in dropbox_api.list_skin_folders(client, profile):
        for device in dropbox_api.list_skin_devices(client, profile, skin_id):
            if device["place"] != "skin":
                continue
            device_ids.add(device["device_id"])
            manifest = _load_manifest(client, profile, device["device_id"], "skin", skin_id)
            snapshots += len(_snapshot_records(manifest))
    return len(device_ids), snapshots


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


def _item_place(item):
    profile = item.get("profile")
    skin_id = item.get("skin_id")
    place = item.get("place") or "profile"
    if not profile or not valid_skin_id(skin_id):
        raise ValueError("Snapshot is not valid")
    return profile, place, skin_id


def _delete_snapshot(item):
    if not valid_device(item.get("device_id")) or not valid_id(item.get("id")):
        raise ValueError("Snapshot is not valid")
    profile, place, skin_id = _item_place(item)
    dialog = None
    try:
        dialog = _busy("Deleting snapshot")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        manifest = _load_manifest(client, profile, item["device_id"], place, skin_id, strict=True)
        remaining = [
            record for record in _snapshot_records(manifest)
            if record["id"] != item["id"]
        ]
        remaining.sort(key=lambda record: record["id"], reverse=True)
        target = _manifest_at(profile, item["device_id"], place, skin_id)
        if remaining:
            dropbox_api.upload_json(client, target, {
                "device_id": item["device_id"],
                "device_name": item["name"],
                "snapshots": remaining,
            })
        else:
            dropbox_api.delete_path(client, target)
        dropbox_api.delete_path(client, _snapshot_at(profile, item["device_id"], item["id"], place, skin_id))
    finally:
        if dialog is not None:
            dialog.close()


def _wipe_device(client, profile, device_id, legacy=False, skin_id=None):
    try:
        manifest = dropbox_api.download_json(client, manifest_path(profile, device_id, legacy, skin_id))
    except Exception as exc:
        if "not_found" not in str(exc):
            raise
        manifest = {}
    for snapshot_id in _snapshot_ids(manifest):
        dropbox_api.delete_path(client, snapshot_path(profile, device_id, snapshot_id, legacy, skin_id))
    dropbox_api.delete_path(client, manifest_path(profile, device_id, legacy, skin_id))
    folder = device_folder(profile, device_id, legacy, skin_id)
    for entry in dropbox_api.list_folder(client, folder):
        name = getattr(entry, "name", "")
        if name == "manifest.json" or name.endswith(".zip"):
            target = getattr(entry, "path_display", None) or "%s/%s" % (folder, name)
            dropbox_api.delete_path(client, target)


def _drop_skin_snapshots(client, profile, device_id, place, skin_id):
    manifest = _load_manifest(client, profile, device_id, place, skin_id)
    records = _snapshot_records(manifest)
    kept = [record for record in records if record["skin_id"] != skin_id]
    dropped = [record for record in records if record["skin_id"] == skin_id]
    if not dropped:
        return
    for record in dropped:
        dropbox_api.delete_path(client, _snapshot_at(profile, device_id, record["id"], place, skin_id))
    target = _manifest_at(profile, device_id, place, skin_id)
    if kept:
        dropbox_api.upload_json(client, target, {
            "device_id": device_id,
            "device_name": manifest.get("device_name") or device_id,
            "snapshots": kept,
        })
    else:
        dropbox_api.delete_path(client, target)


def _delete_device(item):
    device_id = item.get("device_id")
    if not valid_device(device_id):
        raise ValueError("Device is not valid")
    profile, _place, skin_id = _item_place(item)
    dialog = None
    try:
        dialog = _busy("Deleting snapshots")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        _wipe_device(client, profile, device_id, skin_id=skin_id)
        _drop_skin_snapshots(client, profile, device_id, "profile", skin_id)
        if profile == DEFAULT_PROFILE:
            _drop_skin_snapshots(client, profile, device_id, "root", skin_id)
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
    profile, place, skin_id = _item_place(item)
    dialog = None
    try:
        dialog = _busy("Saving")
        client = dropbox_api.get_client()
        if client is None:
            raise RuntimeError("Authorize Dropbox first")
        manifest = _load_manifest(client, profile, item["device_id"], place, skin_id, strict=True)
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
        dropbox_api.upload_json(client, _manifest_at(profile, item["device_id"], place, skin_id), {
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
        active_id, _active_name = current_skin()
        parts = choose_parts(item.get("skin_name"), same_skin=item.get("skin_id") == active_id)
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


def manage_builds(profile=None, skin_id=None, skin_name=None):
    if not dropbox_api.authorized():
        dropbox_api.notify("Authorize Dropbox first", error=True)
        return False
    try:
        profile = dropbox_api.profile_name() if profile is None else profile
        if skin_id is None:
            skin_id, skin_name = current_skin()
        if not valid_skin_id(skin_id):
            raise ValueError("Kodi has no skin selected")
    except Exception as exc:
        dropbox_api.show_failure(dropbox_api.failure_text(exc, "Profile name is not valid"))
        return False
    heading = "Saved builds — %s — %s" % (profile, skin_name or skin_id)
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
                rows = _all_snapshots(client, profile, skin_id, dropbox_api.device_id())
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            notice = (dropbox_api.failure_text(exc, "Could not load builds"), True)
        finally:
            if dialog is not None:
                dialog.close()
        if notice:
            dropbox_api.show_failure(notice[0])
            return False
        labels = ["Other skins"] + [_describe(item) for item in rows]
        index = xbmcgui.Dialog().select(heading, labels)
        if index is None or index < 0:
            return True
        if index == 0:
            if browse_skins(profile) is False:
                return False
            continue
        try:
            if not _manage_one(rows[index - 1], rows):
                return False
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            dropbox_api.show_failure(dropbox_api.failure_text(exc, "Could not update the saved builds"))
            return False


def browse_skins(profile):
    while True:
        dialog = None
        notice = None
        skins = []
        lines = []
        try:
            dialog = _busy("Loading skins")
            client = dropbox_api.get_client()
            if client is None:
                notice = ("Authorize Dropbox first", True)
            else:
                for skin_id, skin_name in _discover_skins(client, profile):
                    rows = _all_snapshots(client, profile, skin_id, dropbox_api.device_id())
                    devices = len({row["device_id"] for row in rows})
                    skins.append((skin_id, skin_name))
                    lines.append("%s | %s | %s" % (
                        skin_name,
                        _count_label(devices, "device", "devices"),
                        _count_label(len(rows), "snapshot", "snapshots"),
                    ))
        except Exception as exc:
            dropbox_api.log(traceback.format_exc())
            notice = (dropbox_api.failure_text(exc, "Could not load skins"), True)
        finally:
            if dialog is not None:
                dialog.close()
        if notice:
            dropbox_api.show_failure(notice[0])
            return False
        if not lines:
            dropbox_api.notify("No skins")
            return True
        index = xbmcgui.Dialog().select("Skins — %s" % profile, lines)
        if index is None or index < 0:
            return True
        skin_id, skin_name = skins[index]
        if manage_builds(profile, skin_id, skin_name) is False:
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
                    device_count, snapshots = _profile_usage(client, name)
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
        if browse_skins(names[index]) is False:
            return
