import re
from typing import Optional


def duration_to_seconds(duration: Optional[str]) -> int:
    if not duration:
        return 0

    s = duration.strip()

    hms_pattern = re.compile(
        r'(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s\s*)?$',
        re.IGNORECASE
    )
    m = hms_pattern.match(s)
    if m:
        hours = int(m.group(1)) if m.group(1) else 0
        minutes = int(m.group(2)) if m.group(2) else 0
        seconds = int(m.group(3)) if m.group(3) else 0
        return hours * 3600 + minutes * 60 + seconds

    if ':' in s:
        parts = [int(p) for p in s.split(':')]
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours, minutes, seconds = 0, parts[0], parts[1]
        else:
            raise ValueError(f"Invalid duration format: {duration}")
        return hours * 3600 + minutes * 60 + seconds

    raise ValueError(f"Invalid duration format: {duration}")
