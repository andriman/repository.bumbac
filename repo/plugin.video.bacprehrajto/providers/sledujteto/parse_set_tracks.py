import re
import json
from html import unescape
from collections import namedtuple
from typing import List

# ----------------------------------------------------------------------
# Public data structure – one entry per subtitle track
# ----------------------------------------------------------------------
Track = namedtuple('Track', ['id', 'file', 'path', 'label', 'delete_link'])


def parse_set_tracks(raw: str) -> List[Track]:
    """
    Convert a raw ``setTracks([...])`` string (HTML-escaped JSON) into a
    list of ``Track`` objects.

    Parameters
    ----------
    raw: str
        The exact text you receive, e.g.

        setTracks([{"id":10979,"file":"https:\/\/...","path":"...","label":"...","delete_link":""}]);

    Returns
    -------
    List[Track]
        Empty list if nothing is found or parsing fails.
    """
    # 1. Grab the JSON array inside the parentheses
    m = re.search(r'setTracks\s*\(\s*(\[.+?\])\s*\)', raw, re.DOTALL)
    if not m:
        return []

    json_text = m.group(1)

    # 2. Undo HTML escaping ( &quot; → " )
    json_text = unescape(json_text)

    # 3. The original page uses &quot; for every quote → replace with real "
    json_text = json_text.replace('&quot;', '"')

    # 4. Parse as JSON
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        # In a KODI addon you would log this:
        # xbmc.log(f"[myaddon] JSON error: {exc}", xbmc.LOGERROR)
        return []

    # 5. Build Track objects (defensive – ignore missing keys)
    tracks: List[Track] = []
    for entry in data:
        try:
            tracks.append(
                Track(
                    id=int(entry.get('id', 0)),
                    file=str(entry.get('file', '')),
                    path=str(entry.get('path', '')),
                    label=str(entry.get('label', '')),
                    delete_link=str(entry.get('delete_link', ''))
                )
            )
        except (ValueError, TypeError):
            continue

    return tracks