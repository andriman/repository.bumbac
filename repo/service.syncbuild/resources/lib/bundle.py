import io
import os
import re
import urllib.parse
import zipfile

SHARED_FILES = (
    "addon_data/plugin.video.themoviedb.helper/settings.xml",
    "sources.xml",
    "favourites.xml",
)
TMDB_SETTINGS = "addon_data/plugin.video.themoviedb.helper/settings.xml"
SHORTCUT_ROOT = "addon_data/script.skinvariables/nodes/"
PARTS = ("skin", "shortcuts", "tmdb", "sources", "favourites")
_SKIN_ID = re.compile(r"skin\.[A-Za-z0-9._-]+")
_SKIN_SETTINGS = re.compile(r"^addon_data/(skin\.[A-Za-z0-9._-]+)/settings\.xml$")
_SHORTCUT = re.compile(r"^addon_data/script\.skinvariables/nodes/(skin\.[A-Za-z0-9._-]+)/")
PROFILE = "{profile}"
PROFILE_ENC = "{profile_enc}"

_ENCODED_RUN = re.compile(
    r"(?:[A-Za-z0-9\-_.~]|%[0-9A-Fa-f]{2})*%(?:[A-Za-z0-9\-_.~]|%[0-9A-Fa-f]{2})*"
)
_REBUILD = re.compile(
    r'(<setting id="Shortcuts\.RebuildDateTime"[^>]*>)(.*?)(</setting>)',
    re.DOTALL,
)


def normalize(name):
    return name.replace("\\", "/").lstrip("/")


def valid_skin_id(skin_id):
    return bool(skin_id and _SKIN_ID.fullmatch(skin_id))


def skin_settings_path(skin_id):
    return "addon_data/%s/settings.xml" % skin_id


def shortcut_dir(skin_id):
    return SHORTCUT_ROOT + skin_id + "/"


def skin_id_from_path(name):
    rel = normalize(name)
    match = _SKIN_SETTINGS.match(rel) or _SHORTCUT.match(rel)
    if not match:
        return None
    skin_id = match.group(1)
    if not valid_skin_id(skin_id):
        return None
    return skin_id


def allowed(name):
    rel = normalize(name)
    if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
        return False
    if rel in SHARED_FILES:
        return True
    skin_id = skin_id_from_path(rel)
    if not skin_id:
        return False
    if rel == skin_settings_path(skin_id):
        return True
    return rel.startswith(shortcut_dir(skin_id))


def part_for(name):
    rel = normalize(name)
    if rel == TMDB_SETTINGS:
        return "tmdb"
    if rel == "sources.xml":
        return "sources"
    if rel == "favourites.xml":
        return "favourites"
    if _SKIN_SETTINGS.match(rel):
        return "skin"
    if _SHORTCUT.match(rel):
        return "shortcuts"
    return None


def all_parts():
    return set(PARTS)


def snapshot_skin_ids(names, skin_id=None):
    found = []
    for name in names:
        detected = skin_id_from_path(name)
        if detected and detected not in found:
            found.append(detected)
    if valid_skin_id(skin_id) and skin_id not in found:
        found.append(skin_id)
    return found


def home_forms(home):
    cleaned = (home or "").strip().rstrip("\\/")
    if len(cleaned) < 3:
        raise ValueError("Profile path is too short")
    forms = []
    for item in (cleaned, cleaned.replace("\\", "/"), cleaned.replace("/", "\\")):
        if item not in forms:
            forms.append(item)
    return forms


def encode_kodi(path):
    encoded = []
    for char in path:
        if char.isalnum() or char in "-_.~":
            encoded.append(char)
        else:
            encoded.append("%%%02x" % ord(char))
    return "".join(encoded)


def portable_home(home):
    return home_forms(home)[0].replace("\\", "/")


def _suffix_after_home(raw, homes, ignore_case):
    raw_norm = raw.replace("/", "\\")
    for home in homes:
        home_norm = home.replace("/", "\\").rstrip("\\")
        compared = raw_norm.lower() if ignore_case else raw_norm
        prefix = home_norm.lower() if ignore_case else home_norm
        if compared == prefix:
            return ""
        if compared.startswith(prefix + "\\"):
            return raw[len(home_norm):]
    return None


def _rewrite_raw(text, homes, ignore_case):
    flags = re.IGNORECASE if ignore_case else 0
    for home in homes:
        pattern = re.escape(home) + r"(?:[\\/][^\"'<>\r\n]*)?"

        def replace(match, home=home):
            raw = match.group(0)
            rest = _suffix_after_home(raw, [home], ignore_case)
            if rest is None:
                return raw
            rest = rest.replace("\\", "/").lstrip("/")
            if rest:
                return PROFILE + "/" + rest
            return PROFILE

        text = re.sub(pattern, replace, text, flags=flags)
    return text


def rewrite_out(text, home, ignore_case=None):
    if ignore_case is None:
        ignore_case = os.name == "nt"
    homes = home_forms(home)

    def replace_encoded(match):
        blob = match.group(0)
        rest = _suffix_after_home(urllib.parse.unquote(blob), homes, ignore_case)
        if rest is None:
            return blob
        rest = rest.replace("\\", "/").lstrip("/")
        if not rest:
            return PROFILE_ENC
        return PROFILE_ENC + "%2f" + encode_kodi(rest)

    text = _ENCODED_RUN.sub(replace_encoded, text)
    return _rewrite_raw(text, homes, ignore_case)


def expand_profile(text, home):
    local = portable_home(home)
    text = text.replace(PROFILE_ENC, encode_kodi(local))
    text = text.replace(PROFILE, local)
    return text


def bump_rebuild(text, stamp):
    return _REBUILD.sub(lambda match: match.group(1) + stamp + match.group(3), text, count=1)


def _read_rewritten(path, home, ignore_case):
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return rewrite_out(text, home, ignore_case=ignore_case).encode("utf-8")


def iter_build_files(userdata, skin_id):
    if not valid_skin_id(skin_id):
        raise ValueError("Skin is not valid")
    paths = list(SHARED_FILES) + [skin_settings_path(skin_id)]
    for rel in paths:
        path = os.path.join(userdata, *rel.split("/"))
        if os.path.isfile(path):
            yield rel, path
    root = os.path.join(userdata, *shortcut_dir(skin_id).strip("/").split("/"))
    if not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.startswith(".") or filename.lower() == "thumbs.db":
                continue
            full = os.path.join(dirpath, filename)
            rel = normalize(os.path.relpath(full, userdata))
            if allowed(rel) and os.path.isfile(full):
                yield rel, full


def pack(userdata, home, skin_id, ignore_case=None):
    buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel, path in iter_build_files(userdata, skin_id):
            archive.writestr(rel, _read_rewritten(path, home, ignore_case))
            count += 1
    if count == 0:
        return None
    return buffer.getvalue()


def _destination(userdata, rel):
    if not allowed(rel):
        return None
    root = os.path.abspath(userdata)
    dest = os.path.abspath(os.path.join(root, *rel.split("/")))
    try:
        if os.path.commonpath([root, dest]) != root:
            return None
    except ValueError:
        return None
    return dest


def _remove_file(userdata, rel):
    dest = _destination(userdata, rel)
    if dest and os.path.isfile(dest):
        os.remove(dest)


def _prune(userdata, keep, parts, skin_ids):
    for rel in SHARED_FILES:
        if part_for(rel) not in parts or rel in keep:
            continue
        _remove_file(userdata, rel)
    if "skin" in parts:
        for skin_id in skin_ids:
            rel = skin_settings_path(skin_id)
            if rel not in keep:
                _remove_file(userdata, rel)
    if "shortcuts" not in parts:
        return
    for skin_id in skin_ids:
        root = os.path.join(userdata, *shortcut_dir(skin_id).strip("/").split("/"))
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                rel = normalize(os.path.relpath(full, userdata))
                if rel not in keep and os.path.isfile(full):
                    os.remove(full)
            for dirname in dirnames:
                folder = os.path.join(dirpath, dirname)
                if os.path.isdir(folder) and not os.listdir(folder):
                    os.rmdir(folder)


def touch_rebuild(userdata, stamp, skin_id):
    if not valid_skin_id(skin_id):
        return False
    dest = _destination(userdata, skin_settings_path(skin_id))
    if not dest or not os.path.isfile(dest):
        return False
    with open(dest, "r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    updated = bump_rebuild(text, stamp)
    if updated == text:
        return False
    with open(dest, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    return True


def unpack(blob, userdata, home, rebuild_stamp=None, parts=None, skin_id=None):
    selected = all_parts() if parts is None else set(parts)
    if not selected:
        return []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = []
        for name in archive.namelist():
            rel = normalize(name)
            if not name.endswith("/") and allowed(rel):
                names.append(rel)
        if not names:
            raise ValueError("Snapshot has no build files")
        skin_ids = snapshot_skin_ids(names, skin_id)
        payload = {}
        for rel in names:
            if part_for(rel) not in selected:
                continue
            data = archive.read(rel)
            try:
                text = expand_profile(data.decode("utf-8"), home)
            except UnicodeDecodeError:
                payload[rel] = data
                continue
            if part_for(rel) == "skin" and rebuild_stamp:
                text = bump_rebuild(text, rebuild_stamp)
            payload[rel] = text.encode("utf-8")

    os.makedirs(userdata, exist_ok=True)
    for rel, data in payload.items():
        dest = _destination(userdata, rel)
        if dest is None:
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(data)
    _prune(userdata, set(payload), selected, skin_ids)
    if rebuild_stamp and "shortcuts" in selected:
        written_skins = {skin_id_from_path(rel) for rel in payload if part_for(rel) == "skin"}
        for restored_skin in skin_ids:
            if restored_skin not in written_skins:
                touch_rebuild(userdata, rebuild_stamp, restored_skin)
    return sorted(payload)
