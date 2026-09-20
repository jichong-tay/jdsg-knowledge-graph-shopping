import asyncio
import json
from datetime import UTC, datetime

from shopping.assistant.runtime import run_attempt
from shopping.assistant.tools import dispatch_tool


async def no_model(messages):
    raise AssertionError("continuation must not create model metadata")


def test_year_one_now_is_rejected_before_runtime(settings):
    result = asyncio.run(
        run_attempt(settings, "hello", now=datetime(1, 1, 1, tzinfo=UTC), count_input=no_model)
    )
    assert result["status"] == "rejected"
    assert result["code"] == "invalid_arguments"


def test_next_page_without_anchor_is_safe_and_does_not_read(settings):
    result = asyncio.run(
        run_attempt(settings, "next page", count_input=no_model, completed_exchanges=[])
    )
    assert result["status"] == "complete"
    assert result["model_requests"] == 0
    assert result["tool_calls"] == 0
    assert "monthly page" in result["text"]


def test_next_page_rejects_invalid_saved_history_and_preset_stop(settings):
    invalid = asyncio.run(
        run_attempt(
            settings,
            "next page",
            completed_exchanges=[[{"role": "user", "content": "unfinished"}]],
            count_input=no_model,
        )
    )
    assert invalid["code"] == "invalid_history"
    stop = asyncio.Event()
    stop.set()
    stopped = asyncio.run(run_attempt(settings, "next page", stop=stop, count_input=no_model))
    assert stopped["code"] == "cancelled"
    assert stopped["tool_calls"] == 0


def _saved_monthly_exchange(result, month="2026-08", limit=3):
    return [
        {"role": "user", "content": "list purchase items"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "list_purchase_items",
                        "arguments": {"month": month, "limit": limit},
                    }
                }
            ],
        },
        {"role": "tool", "tool_name": "list_purchase_items", "content": json.dumps(result)},
        {"role": "assistant", "content": "Recorded page."},
    ]


def test_next_page_uses_real_monthly_result_without_model_or_tokenizer(
    monthly_purchase_facts, monkeypatch
):
    import shopping.assistant.runtime as runtime

    first = dispatch_tool(
        monthly_purchase_facts, "list_purchase_items", {"month": "2026-08", "limit": 3}
    )
    assert first["next_cursor"]
    second = dispatch_tool(
        monthly_purchase_facts,
        "list_purchase_items",
        {"month": "2026-08", "limit": 3, "cursor": first["next_cursor"]},
    )
    older = _saved_monthly_exchange(first, limit=3)
    older[-1]["content"] = "old " * 2000
    monkeypatch.setattr(
        runtime,
        "create_counter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no counter")),
    )
    events = []

    async def publish(event):
        events.append(event)

    result = asyncio.run(
        run_attempt(
            monthly_purchase_facts,
            "next page",
            completed_exchanges=[older, _saved_monthly_exchange(first, limit=3)],
            count_input=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no count")),
            emit=publish,
            now=datetime(2026, 10, 20, tzinfo=UTC),
        )
    )
    assert result["status"] == "complete"
    assert result["model_requests"] == 0 and result["tool_calls"] == 1
    assert [event["call_id"] for event in events if event.get("type") == "tool"] == ["0:0", "0:0"]
    assert result["text"] == runtime.render_month_items(second)[0]
    _, expected_refs = runtime.render_month_items(second)
    assert {entry["id"] for entry in result["evidence"]} == set(expected_refs)


def test_next_page_exhausted_saved_page_does_not_claim_fresh_facts(settings):
    empty = dispatch_tool(settings, "list_purchase_items", {"month": "2030-01", "limit": 3})
    assert empty["status"] == "ok" and empty["next_cursor"] is None
    result = asyncio.run(
        run_attempt(
            settings,
            "next page",
            completed_exchanges=[_saved_monthly_exchange(empty, month="2030-01", limit=3)],
            count_input=no_model,
        )
    )
    assert result["status"] == "complete"
    assert result["model_requests"] == 0 and result["tool_calls"] == 0
    assert "2030-01" in result["text"] and "no further rows" in result["text"]
