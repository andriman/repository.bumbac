from datetime import datetime
import re


def duration_to_seconds(duration: str) -> int:
    """
    Converts a duration string like "0h 43m 51s" to total seconds.

    Args:
        duration (str): Duration in format "Xh Ym Zs" (spaces optional, parts optional)

    Returns:
        int: Total seconds

    Example:
        >>> duration_to_seconds("0h 43m 51s")
        2631
    """
    if duration is None or duration == '':
        return 0

    pattern = r'(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?'
    match = re.match(pattern, duration.strip(), re.IGNORECASE)

    if not match:
        raise ValueError(f"Invalid duration format: {duration}")

    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0

    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds


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
