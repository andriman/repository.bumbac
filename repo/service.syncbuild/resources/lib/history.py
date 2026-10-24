import re

SNAPSHOT_ID = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z")
DEVICE_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ROOT = "/SyncBuild"


def valid_device(device_id):
    return bool(device_id and DEVICE_ID.fullmatch(device_id))


def valid_id(snapshot_id):
    return bool(snapshot_id and SNAPSHOT_ID.fullmatch(snapshot_id))


def snapshot_path(device_id, snapshot_id):
    return "%s/%s/%s.zip" % (ROOT, device_id, snapshot_id)


def manifest_path(device_id):
    return "%s/%s/manifest.json" % (ROOT, device_id)


def display_time(snapshot_id):
    if not valid_id(snapshot_id):
        return snapshot_id or ""
    day, clock = snapshot_id[:-1].split("T")
    hour, minute, _second = clock.split("-")
    return "%s %s:%s UTC" % (day, hour, minute)


def choose_newer(found, local_id, last_marker):
    baseline = last_marker or ""
    chosen = [
        item for item in found
        if valid_device(item.get("device_id"))
        and item.get("device_id") != local_id
        and valid_id(item.get("id"))
        and item["id"] > baseline
    ]
    chosen.sort(key=lambda item: item["id"], reverse=True)
    return chosen


def kept_snapshot_ids(existing_ids, new_id, keep):
    if not valid_id(new_id):
        raise ValueError("Snapshot time is not valid")
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        keep = 3
    keep = min(50, max(1, keep))
    others = sorted(
        {snapshot_id for snapshot_id in (existing_ids or []) if valid_id(snapshot_id) and snapshot_id != new_id},
        reverse=True,
    )
    kept = sorted([new_id] + others[:keep - 1], reverse=True)
    return kept, others[keep - 1:]
