"""Singapore calendar helpers for application-owned Chat context."""

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

SG = ZoneInfo("Asia/Singapore")
_MONTH = re.compile(r"^([0-9]{4})-(0[1-9]|1[0-2])$")


def previous_month(today: date) -> str:
    if type(today) is not date:
        raise ValueError("invalid_arguments")
    if today.year == 1 and today.month == 1:
        raise ValueError("invalid_arguments")
    year, month = today.year, today.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def month_bounds(month: str) -> tuple[str, str]:
    match = _MONTH.fullmatch(month) if type(month) is str else None
    if match is None:
        raise ValueError("invalid_arguments")
    try:
        year, number = int(match[1]), int(match[2])
        start = datetime(year, number, 1, tzinfo=SG)
        if number == 12:
            end = datetime(year + 1, 1, 1, tzinfo=SG)
        else:
            end = datetime(year, number + 1, 1, tzinfo=SG)
        return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid_arguments") from exc
