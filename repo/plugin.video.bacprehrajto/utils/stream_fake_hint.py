"""
Compare TMDB air date with Prehraj.to upload date on search results (probable fake uploads).
"""
import re
from datetime import date, datetime
from typing import Any, Dict, Optional

from utils.StrUtils import find_pattern
from utils.utils import dprint

# Kodi [COLOR AARRGGBB] — orange
_ORANGE = "FFFF8C00"


def parse_air_date_to_date(air_s: Optional[str]) -> Optional[date]:
    if not air_s or not str(air_s).strip():
        return None
    try:
        return date.fromisoformat(str(air_s).strip()[:10])
    except ValueError:
        return None


def parse_prehraj_upload_to_datetime(s: str) -> Optional[datetime]:
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in (
        "%d. %m. %Y %H:%M:%S",
        "%d. %m. %Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d. %m. %Y",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def highlight_datum_vysilani_line_orange(plot: str) -> str:
    if not plot:
        return plot
    return re.sub(
        r"(^Datum vysílání:\s*[^\n]+)",
        "[COLOR " + _ORANGE + r"]\1[/COLOR]",
        plot,
        count=1,
        flags=re.MULTILINE,
    )


def extract_upload_date_raw_from_listing_card(link_tag: Any) -> Optional[str]:
    """Walk up from the video link and find Datum nahrání text (HTML or visible)."""
    node = link_tag
    for _ in range(16):
        if node is None:
            break
        blob = str(node)
        for pattern in (
            r'Datum nahr.n.:</span>\s*<span>([^<]+)</span>',
            r'Datum nahr[^:]*:</span>\s*<span>([^<]+)</span>',
        ):
            u = find_pattern(blob, pattern)
            if u:
                return u.strip()
        try:
            text = node.get_text(" ", strip=True)
        except Exception:
            text = ""
        m = re.search(
            r"Datum\s+nahr[^\d]{0,40}(\d{1,2}\.\s*\d{1,2}\.\s*\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        node = getattr(node, "parent", None)
    return None


LISTING_UPLOAD_PROP = "PrehrajListingUploadRaw"


def maybe_highlight_fake_stream_in_listitem(
    list_item: Any, video_info_dict: Dict, enabled: bool
) -> None:
    """
    If enabled and upload on Prehraj is before TMDB air date, colorize the
    'Datum vysílání' line in plot (Kodi [COLOR] tags) and set a list property.
    Mutates video_info_dict in place.
    """
    if not enabled:
        return
    raw = list_item.getProperty(LISTING_UPLOAD_PROP)
    if not raw:
        return
    air_s = video_info_dict.get("aired") or video_info_dict.get("premiered") or ""
    air_d = parse_air_date_to_date(air_s)
    upload_dt = parse_prehraj_upload_to_datetime(raw)
    if not air_d or not upload_dt:
        dprint(
            f"stream_fake_hint: skip compare air={air_s!r} upload_raw={raw!r}"
        )
        return
    if upload_dt.date() >= air_d:
        return
    plot = video_info_dict.get("plot") or ""
    video_info_dict["plot"] = highlight_datum_vysilani_line_orange(plot)
    list_item.setProperty("IsProbableFakeStream", "true")
    dprint(
        f"stream_fake_hint: probable fake upload={upload_dt.date()} air={air_d}"
    )
