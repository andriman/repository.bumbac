import re

SNAPSHOT_ID = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z")
DEVICE_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ROOT = "/SyncBuild"
DEFAULT_PROFILE = "default"


def valid_device(device_id):
    return bool(device_id and DEVICE_ID.fullmatch(device_id))


def valid_profile(name):
    text = (name or "").strip()
    if not text or text in (".", "..") or valid_device(text):
        return False
    return "/" not in text and "\\" not in text


def clean_profile(name):
    text = (name or "").strip() or DEFAULT_PROFILE
    if text in (".", "..") or "/" in text or "\\" in text:
        raise ValueError("Profile name cannot contain slashes")
    if valid_device(text):
        raise ValueError("Profile name cannot be a device id")
    return text


def classify_root_folders(names):
    profiles = []
    legacy = False
    for name in names or []:
        if valid_device(name):
            legacy = True
        elif valid_profile(name) and name not in profiles:
            profiles.append(name)
    if legacy and DEFAULT_PROFILE not in profiles:
        profiles.append(DEFAULT_PROFILE)
    profiles.sort()
    return profiles


def profile_device_entries(profile, profile_folders, root_folders):
    profile = clean_profile(profile)
    devices = []
    for name in profile_folders or []:
        if valid_device(name):
            devices.append({"device_id": name, "legacy": False})
    if profile == DEFAULT_PROFILE:
        for name in root_folders or []:
            if valid_device(name):
                devices.append({"device_id": name, "legacy": True})
    return devices


def profile_root(profile):
    return "%s/%s" % (ROOT, clean_profile(profile))


def device_folder(profile, device_id, legacy=False):
    if not valid_device(device_id):
        raise ValueError("Device is not valid")
    if legacy:
        if clean_profile(profile) != DEFAULT_PROFILE:
            raise ValueError("Legacy builds belong to the default profile")
        return "%s/%s" % (ROOT, device_id)
    return "%s/%s" % (profile_root(profile), device_id)


def valid_id(snapshot_id):
    return bool(snapshot_id and SNAPSHOT_ID.fullmatch(snapshot_id))


def snapshot_path(profile, device_id, snapshot_id, legacy=False):
    return "%s/%s.zip" % (device_folder(profile, device_id, legacy), snapshot_id)


def manifest_path(profile, device_id, legacy=False):
    return "%s/manifest.json" % device_folder(profile, device_id, legacy)


def display_time(snapshot_id):
    if not valid_id(snapshot_id):
        return snapshot_id or ""
    day, clock = snapshot_id[:-1].split("T")
    hour, minute, _second = clock.split("-")
    return "%s %s:%s UTC" % (day, hour, minute)


def choose_newer(found, local_id, last_marker, ignored=None):
    baseline = last_marker or ""
    skipped = set(ignored or [])
    chosen = [
        item for item in found
        if valid_device(item.get("device_id"))
        and item.get("device_id") != local_id
        and valid_id(item.get("id"))
        and item["id"] > baseline
        and item["id"] not in skipped
    ]
    chosen.sort(key=lambda item: item["id"], reverse=True)
    return chosen


def clamp_keep(keep):
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        keep = 3
    return min(50, max(1, keep))


def kept_snapshot_ids(existing, new_id, keep):
    if not valid_id(new_id):
        raise ValueError("Snapshot time is not valid")
    keep = clamp_keep(keep)
    starred = []
    plain = []
    seen = set()
    for item in existing or []:
        if isinstance(item, dict):
            snapshot_id = item.get("id")
            is_starred = bool(item.get("starred"))
        else:
            snapshot_id = item
            is_starred = False
        if not valid_id(snapshot_id) or snapshot_id == new_id or snapshot_id in seen:
            continue
        seen.add(snapshot_id)
        if is_starred:
            starred.append(snapshot_id)
        else:
            plain.append(snapshot_id)
    starred.sort(reverse=True)
    plain.sort(reverse=True)
    kept_ids = set(starred)
    kept_ids.add(new_id)
    kept_ids.update(plain[:keep - 1])
    removed = plain[keep - 1:]
    return sorted(kept_ids, reverse=True), removed
