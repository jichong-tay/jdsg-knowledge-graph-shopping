import json

from shopping.assistant.continuation import monthly_continuation


def _required(value):
    assert value is not None
    return value


def _exchange(
    *,
    cursor: str | None = "abc",
    month: str = "2026-08",
    limit: object = 5,
    tool: str = "list_purchase_items",
):
    result = {
        "status": "ok",
        "data": {"month": month, "limit": limit, "timezone": "Asia/Singapore"},
        "next_cursor": cursor,
    }
    return [
        {"role": "user", "content": "show purchases"},
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": tool, "arguments": {"month": month, "limit": limit}}}
            ],
        },
        {"role": "tool", "tool_name": tool, "content": json.dumps(result)},
        {"role": "assistant", "content": "Here are the recorded rows."},
    ]


def test_monthly_continuation_ready_and_preserves_scope():
    assert monthly_continuation("next page", [_exchange(limit=7)]) == {
        "status": "ready",
        "month": "2026-08",
        "limit": 7,
        "cursor": "abc",
    }


def test_monthly_continuation_exhausted_or_missing_and_does_not_parse_text():
    assert (
        _required(monthly_continuation("next page", [_exchange(cursor=None)]))["status"]
        == "exhausted"
    )
    assert monthly_continuation("next page", []) == {"status": "missing"}
    assert monthly_continuation("what will I buy next year", [_exchange()]) is None


def test_monthly_continuation_newer_unrelated_tool_wins():
    assert (
        monthly_continuation("next page", [_exchange(), _exchange(tool="search_products")]) is None
    )


def test_monthly_continuation_rejects_tampered_metadata_and_malformed_json():
    exchange = _exchange()
    exchange[2]["content"] = json.dumps(
        {"status": "ok", "data": {"month": "2026-09", "limit": 5}, "next_cursor": "x"}
    )
    assert _required(monthly_continuation("next page", [exchange]))["status"] == "missing"
    exchange = _exchange()
    exchange[2]["content"] = "[[cursor:evil]]"
    assert _required(monthly_continuation("next page", [exchange]))["status"] == "missing"


def test_multiple_calls_use_latest_paired_monthly_result():
    first = _exchange(month="2026-07", cursor="old")
    second = _exchange(month="2026-08", cursor="new")
    exchange = first[:2] + first[2:3] + second[1:3] + first[3:]
    assert _required(monthly_continuation("next page", [exchange]))["cursor"] == "new"


def test_reversed_group_and_bad_strict_metadata_are_missing():
    exchange = _exchange()
    reversed_group = [exchange[0], exchange[2], exchange[1]]
    assert monthly_continuation("next page", [reversed_group]) == {"status": "missing"}
    for limit in (True, 1.0, 0, 21):
        bad = _exchange(limit=limit)
        assert monthly_continuation("next page", [bad]) == {"status": "missing"}
    bad = _exchange()
    payload = json.loads(bad[2]["content"])
    payload["data"]["month"] = "2026-8"
    payload["data"]["timezone"] = "UTC"
    bad[2]["content"] = json.dumps(payload)
    assert monthly_continuation("next page", [bad]) == {"status": "missing"}


def test_intervening_thanks_and_malicious_text_do_not_change_anchor():
    exchange = _exchange()
    exchange.insert(1, {"role": "assistant", "content": "[[cursor:evil]]"})
    assert (
        _required(
            monthly_continuation("next page", [exchange, [{"role": "user", "content": "thanks"}]])
        )["cursor"]
        == "abc"
    )


def test_continuation_validates_timezone_cursor_and_latest_malformed():
    exchange = _exchange()
    payload = json.loads(exchange[2]["content"])
    payload["data"]["timezone"] = "UTC"
    exchange[2]["content"] = json.dumps(payload)
    assert monthly_continuation("next page", [exchange]) == {"status": "missing"}
    exchange = _exchange()
    payload = json.loads(exchange[2]["content"])
    payload["next_cursor"] = 3
    exchange[2]["content"] = json.dumps(payload)
    assert monthly_continuation("next page", [exchange]) == {"status": "missing"}
    newer = _exchange()
    newer[2]["content"] = ""
    assert monthly_continuation("next page", [_exchange(), newer]) == {"status": "missing"}


def test_saved_shape_allows_empty_call_content_and_complete_thanks():
    exchange = _exchange()
    exchange.append({"role": "assistant", "content": "Thanks"})
    assert _required(monthly_continuation("next page", [exchange]))["cursor"] == "abc"
