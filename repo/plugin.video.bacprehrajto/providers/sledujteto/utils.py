from datetime import datetime
import re

from bs4 import BeautifulSoup


_DURATION_WORDS_RE = re.compile(
    r'^(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?$',
    re.IGNORECASE,
)


def duration_to_seconds(duration: str) -> int:
    """
    Converts a duration string like "1h 39m 8s" or "01:39:08" to total seconds.

    Args:
        duration (str): "Xh Ym Zs", "HH:mm:ss", "mm:ss", or a seconds count

    Returns:
        int: Total seconds

    Example:
        >>> duration_to_seconds("0h 43m 51s")
        2631
        >>> duration_to_seconds("1h 39m 8s")
        5948
    """
    if duration is None or duration == '':
        return 0
    if isinstance(duration, bool):
        raise ValueError(f"Invalid duration format: {duration}")
    if isinstance(duration, (int, float)):
        return int(duration)

    text = str(duration).strip()
    if not text:
        return 0

    words = _DURATION_WORDS_RE.match(text)
    if words and any(words.groups()):
        hours = int(words.group(1) or 0)
        minutes = int(words.group(2) or 0)
        seconds = int(words.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    if ':' in text:
        parts = text.split(':')
        try:
            numbers = [int(part) for part in parts]
        except ValueError as exc:
            raise ValueError(f"Invalid duration format: {duration}") from exc
        if len(numbers) == 3:
            hours, minutes, seconds = numbers
        elif len(numbers) == 2:
            hours, minutes, seconds = 0, numbers[0], numbers[1]
        else:
            raise ValueError(f"Invalid duration format: {duration}")
        return hours * 3600 + minutes * 60 + seconds

    if text.isdigit():
        return int(text)

    raise ValueError(f"Invalid duration format: {duration}")


def format_duration_hms(duration: str) -> str:
    """Format a sledujteto duration ("1h 39m 8s") as zero-padded HH:mm:ss."""
    if duration is None or str(duration).strip() == '':
        return ''
    total = duration_to_seconds(duration)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def parameter_table_value(soup: BeautifulSoup, label_fragment: str) -> str:
    """Read a cell from the file-page parameters table (Rozlišení, Trvání, Velikost, ...)."""
    for row in soup.select('.parameters-wrapper tr, table.table-striped tr'):
        cells = row.find_all('td')
        if len(cells) < 3:
            continue
        label = cells[1].get_text(' ', strip=True)
        if label_fragment.lower() not in label.lower():
            continue
        return cells[2].get_text(' ', strip=True)
    return ''


def size_duration_label(size: str, duration: str) -> str:
    """Match prehrajto list items: "2.62 GB - 01:39:08"."""
    size_text = (size or '').strip()
    clock = ''
    if duration is not None and str(duration).strip():
        try:
            clock = format_duration_hms(duration)
        except ValueError:
            clock = str(duration).strip()
    if size_text and clock:
        return f'{size_text} - {clock}'
    return size_text or clock


def date_str_to_iso(date_str: str) -> str:
    """
    Converts date string "22. 10. 2025 09:53" to ISO format "Y-m-d h:m:s"

    Args:
        date_str (str): Date in format "DD. MM. YYYY HH:MM" (dots and spaces)

    Returns:
        str: Formatted date "YYYY-MM-DD HH:MM:SS"

    Example:
        >>> date_str_to_iso("22. 10. 2025 09:53")
        "2025-10-22 09:53:00"
    """
    # Parse input format
    try:
        dt = datetime.strptime(date_str.strip(), "%d. %m. %Y %H:%M")
    except ValueError as e:
        raise ValueError(f"Invalid date format: {date_str}") from e

    # Format to desired output
    return dt.strftime("%d.%m.%Y")
    return dt.strftime("%Y-%m-%d %H:%M:%S")
