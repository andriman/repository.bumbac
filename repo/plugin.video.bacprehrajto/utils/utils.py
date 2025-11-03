import os
import re
from typing import List, Optional, Tuple
from urllib.parse import urlencode
from datetime import datetime, timedelta

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from common import g_is_debug_logs_enabled
from model.SubData import SubData

def dprint(text):
    if g_is_debug_logs_enabled:
        print(text)

def truncate_middle(s, n=50):
    # Check if string is already short enough
    if len(s) <= n:
        return s

    # Look for SxxExx pattern (e.g., S01E05)
    match = re.search(r'S\d{2}E\d{2}', s)
    if match:
        # Get the SxxExx part
        season_episode = match.group(0)
        # Get index of the match
        start_idx = match.start()
        end_idx = match.end()

        # Keep first 3 characters before SxxExx
        before = s[:start_idx][:3]
        # Keep everything after SxxExx
        after = s[end_idx:]

        # Combine the parts with "..." between them
        result = before + "..." + season_episode + "..." + after

        # If the result is still too long, truncate
        if len(result) <= n:
            return result
        # Truncate middle of the result
        n_2 = int(n / 2 - 3)
        n_1 = n - n_2 - 3
        return '{0}...{1}'.format(result[:n_1], result[-n_2:])

    # If no SxxExx pattern, use original truncation
    n_2 = int(n / 2 - 3)
    n_1 = n - n_2 - 3
    return '{0}...{1}'.format(s[:n_1], s[-n_2:])


def contains_pattern(source, pattern):
    pattern = re.compile(pattern, re.DOTALL)
    return pattern.search(source) is not None

def find_pattern(source, pattern):
    pattern = re.compile(pattern, re.DOTALL)
    result = pattern.search(source)
    if result is None:
        return None

    return result.group(1)

def find_pattern_groups(source, pattern):
    pattern = re.compile(pattern, re.DOTALL)
    result = pattern.search(source)
    if result is None:
        return None

    return result

def filter_subtitles(data) -> List[SubData]:
    dprint(f'filter_subtitles(): data: ' + str(len(data)))

    # Now filter and clean the tracks.
    subtitle_pattern = re.compile(r'- (cze|eng)\d*$', re.IGNORECASE)

    filtered_tracks: List[SubData] = []
    for track in data:  # assuming dt is the list of track dicts
        label = track.get('label', '')
        match = subtitle_pattern.search(label)
        if match:
            lang_code = match.group(1)
            # If there's a number after cze/eng, include it (e.g., cze1)
            full_match = re.search(r'(cze|eng)\d*$', label, re.IGNORECASE)

            if full_match:
                lang_code = full_match.group(0)  # e.g., "cze", "cze1", "eng"

            file = track.get('file', '')
            if len(file) > 0:
                filtered_tracks.append(SubData(label=lang_code, path=file))

    # Print result
    dprint(f'filter_subtitles(): finish: ' + str(len(data)) + ' -> ' + str(len(filtered_tracks)))
    for t in filtered_tracks:
        dprint(t)

    return filtered_tracks


def get_file_size_human_readable(file_path: str) -> Optional[str]:
    """
    Returns file size as a formatted string (e.g., "1.23 GB" or "456 MB").
    Returns None if size cannot be determined.
    """
    try:
        if file_path.startswith(('http://', 'https://')):
            # Remote file: Check Content-Length header
            response = requests.head(file_path, allow_redirects=True, timeout=5)
            size_bytes = int(response.headers.get('Content-Length', 0))
        else:
            # Local file
            size_bytes = os.path.getsize(file_path)

        # Convert to human-readable format
        if size_bytes >= 1024 ** 3:  # 1 GB or more
            return f"{size_bytes / (1024 ** 3):.2f} GB"
        else:
            return f"{size_bytes / (1024 ** 2):.2f} MB"

    except (requests.RequestException, OSError) as e:
        xbmc.log(f"Failed to get file size: {e}", xbmc.LOGWARNING)
        return None


def notify_file_size(file):
    # Get formatted file size
    file_size_str = "Unknown"
    if file is not None:
        file_size_str = get_file_size_human_readable(file)

    dprint(f'notify_file_size(): ' + file_size_str)

    if file_size_str:
        xbmcgui.Dialog().notification(
            heading="Přehraj.to",
            message=f"Velikost: {file_size_str}",
            icon=xbmcgui.NOTIFICATION_INFO,
            time=4000,
            sound=False
        )


def get_url(url, **kwargs):
    return '{0}?{1}'.format(url, urlencode(kwargs))

def convert_size(number_of_bytes):
    if number_of_bytes < 0:
        raise ValueError("!!! number_of_bytes can't be smaller than 0 !!!")
    step_to_greater_unit = 1024.
    number_of_bytes = float(number_of_bytes)
    unit = 'bytes'
    if (number_of_bytes / step_to_greater_unit) >= 1:
        number_of_bytes /= step_to_greater_unit
        unit = 'KB'
    if (number_of_bytes / step_to_greater_unit) >= 1:
        number_of_bytes /= step_to_greater_unit
        unit = 'MB'
    if (number_of_bytes / step_to_greater_unit) >= 1:
        number_of_bytes /= step_to_greater_unit
        unit = 'GB'
    if (number_of_bytes / step_to_greater_unit) >= 1:
        number_of_bytes /= step_to_greater_unit
        unit = 'TB'
    precision = 1
    number_of_bytes = round(number_of_bytes, precision)
    return str(number_of_bytes) + ' ' + unit

def format_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds <= 0 or seconds == float('inf'):
        return "--:--:--"

    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def format_eta_and_finish(seconds: Optional[float]) -> Tuple[str, str]:
    """
    Vrátí:
        eta_str   → "00:02:13" nebo "--:--:--"
        finish_at → "18:45"   nebo "--:--"
    """
    if seconds is None or seconds <= 0 or seconds == float('inf'):
        return "--:--:--", "--:--"

    # ETA (zůstává stejné)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    eta_str = f"{h:02d}:{m:02d}:{s:02d}"

    # Čas dokončení = teď + ETA
    finish_time = datetime.now() + timedelta(seconds=int(seconds))
    finish_str = finish_time.strftime("%H:%M")

    return eta_str, finish_str


def format_time_ago(date_str: str) -> str:
    dprint(f"format_time_ago(): date_str = {date_str}")

    if not date_str or not date_str.strip():
        return "neznámé datum"

    try:
        upload_time = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        dprint(f"format_time_ago(): ValueError: {e}")
        return "neznámé datum"
    except Exception as e:
        dprint(f"format_time_ago(): Neočekávaná chyba: {e}")
        return "neznámé datum"

    # Teprve teď je upload_time platný
    now = datetime.now()
    delta = now - upload_time
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return "právě teď"
    elif total_seconds < 3600:
        mins = total_seconds // 60
        return f"před {mins} minut{'ou' if mins == 1 else 'ami'}"
    elif total_seconds < 3 * 86400:
        hours = total_seconds // 3600
        return f"před {hours} hodin{'ou' if hours == 1 else 'ami'}"
    else:
        days = total_seconds // 86400
        return f"před {days} {'dnem' if days == 1 else 'dny'}"