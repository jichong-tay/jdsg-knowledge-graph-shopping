from datetime import UTC, date, datetime

import pytest

from shopping.assistant.context import instructions_for
from shopping.assistant.dates import month_bounds, previous_month


def test_previous_month_and_singapore_bounds():
    assert previous_month(date(2026, 9, 20)) == "2026-08"
    assert previous_month(date(2026, 1, 1)) == "2025-12"
    assert month_bounds("2026-08") == (
        "2026-07-31T16:00:00+00:00",
        "2026-08-31T16:00:00+00:00",
    )
    assert month_bounds("2028-02")[1] == "2028-02-29T16:00:00+00:00"


@pytest.mark.parametrize(
    "value",
    ["0000-01", "0001-01", "9999-12", "٢٠٢٦-٠٨", "2026-00", "2026-13", "2026-8", "x", True, None],
)
def test_invalid_months_are_safe(value):
    with pytest.raises(ValueError, match="invalid_arguments"):
        month_bounds(value)


def test_instructions_freeze_singapore_calendar_context():
    text = instructions_for(datetime(2026, 1, 1, 0, tzinfo=UTC))
    assert "Current Singapore date: 2026-01-01" in text
    assert "Previous calendar month: 2025-12" in text


def test_previous_month_rejects_year_one_january():
    with pytest.raises(ValueError, match="invalid_arguments"):
        previous_month(date(1, 1, 2))
