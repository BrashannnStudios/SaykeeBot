import re
from datetime import timedelta
from typing import Optional

TIME_REGEX = re.compile(
    r"(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)",
    re.IGNORECASE
)

def parse_time(time_str: str) -> Optional[timedelta]:
    """Parsea strings como 1h, 30m, 2d, 1h30m, 1w, etc."""
    if not time_str:
        return None

    total_seconds = 0
    matches = TIME_REGEX.findall(time_str.lower().replace(" ", ""))

    if not matches:
        return None

    for amount, unit in matches:
        amount = int(amount)
        if unit.startswith("s"):
            total_seconds += amount
        elif unit.startswith("m"):
            total_seconds += amount * 60
        elif unit.startswith("h"):
            total_seconds += amount * 3600
        elif unit.startswith("d"):
            total_seconds += amount * 86400
        elif unit.startswith("w"):
            total_seconds += amount * 604800

    return timedelta(seconds=total_seconds) if total_seconds > 0 else None
