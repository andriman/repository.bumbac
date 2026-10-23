import io
import os
import re
import urllib.parse
import zipfile

ALLOW_FILES = (
    "addon_data/skin.arctic.fuse.3/settings.xml",
    "addon_data/plugin.video.themoviedb.helper/settings.xml",
    "sources.xml",
    "favourites.xml",
)
ALLOW_DIR = "addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/"
SKIN_SETTINGS = "addon_data/skin.arctic.fuse.3/settings.xml"
TMDB_SETTINGS = "addon_data/plugin.video.themoviedb.helper/settings.xml"
PARTS = (
    ("skin", "Arctic Fuse settings"),
    ("shortcuts", "Skin shortcuts"),
    ("tmdb", "TMDbHelper settings"),
    ("sources", "Sources"),
    ("favourites", "Favourites"),
)
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


def allowed(name):
    rel = normalize(name)
    if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
        return False
    if rel in ALLOW_FILES:
        return True
    return rel.startswith(ALLOW_DIR)


def part_for(name):
    rel = normalize(name)
    if rel == SKIN_SETTINGS:
        return "skin"
    if rel == TMDB_SETTINGS:
        return "tmdb"
    if rel == "sources.xml":
        return "sources"
    if rel == "favourites.xml":
        return "favourites"
    if rel.startswith(ALLOW_DIR):
        return "shortcuts"
    return None


def all_parts():
    return {part_id for part_id, _label in PARTS}


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


def iter_build_files(userdata):
    for rel in ALLOW_FILES:
        path = os.path.join(userdata, *rel.split("/"))
        if os.path.isfile(path):
            yield rel, path
    root = os.path.join(userdata, *ALLOW_DIR.strip("/").split("/"))
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


def pack(userdata, home, ignore_case=None):
    buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel, path in iter_build_files(userdata):
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


def _prune(userdata, keep, parts):
    for rel in ALLOW_FILES:
        if part_for(rel) not in parts or rel in keep:
            continue
        dest = _destination(userdata, rel)
        if dest and os.path.isfile(dest):
            os.remove(dest)
    if "shortcuts" not in parts:
        return
    root = os.path.join(userdata, *ALLOW_DIR.strip("/").split("/"))
    if not os.path.isdir(root):
        return
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


def touch_rebuild(userdata, stamp):
    dest = _destination(userdata, SKIN_SETTINGS)
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


def unpack(blob, userdata, home, rebuild_stamp=None, parts=None):
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
            if rel == SKIN_SETTINGS and rebuild_stamp:
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
    _prune(userdata, set(payload), selected)
    if rebuild_stamp and "shortcuts" in selected and "skin" not in selected:
        touch_rebuild(userdata, rebuild_stamp)
    return sorted(payload)
