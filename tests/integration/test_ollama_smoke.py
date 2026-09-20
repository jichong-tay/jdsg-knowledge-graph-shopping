"""Explicit local/homelab acceptance; skipped by default and never uses production data."""

import asyncio
import json
import os
import time
from datetime import UTC, datetime

import httpx2 as httpx
import pytest

from shopping.assistant.answers import render_month_items
from shopping.assistant.ollama import read_metadata
from shopping.assistant.runtime import run_attempt
from shopping.assistant.tools import dispatch_tool, encode_result
from shopping.ingestion.pipeline import import_eml

pytestmark = pytest.mark.skipif(
    os.environ.get("SHOPPING_OLLAMA_SMOKE") != "1",
    reason="Set SHOPPING_OLLAMA_SMOKE=1 explicitly for the installed local Qwen model",
)


def test_real_qwen_synthetic_tool_round_trip(settings, fixture_dir):
    # conftest always creates an isolated temporary development DB.
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)

    async def run():
        measurements = []
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            version = await read_metadata(client, settings, "/api/version")
            models = await read_metadata(client, settings, "/api/tags")
            model = next(m for m in models["models"] if m["name"] == settings.ollama_model)
            before = await read_metadata(client, settings, "/api/ps")
            for _ in range(2):
                started = time.monotonic()
                result = await run_attempt(settings, "What is the recorded total for order 1?")
                measurements.append(round(time.monotonic() - started, 2))
                assert result["status"] == "complete", result["code"]
                assert "14.00" in result["text"]
                assert any(e["id"] == "order:1" for e in result["evidence"])
                assert result["tool_calls"] >= 1
            loaded = await read_metadata(client, settings, "/api/ps")
        print(
            json.dumps(
                {
                    "server_version": version["version"],
                    "model": settings.ollama_model,
                    "digest": model["digest"],
                    "think": False,
                    "context": 8192,
                    "initially_loaded": any(
                        m["name"] == settings.ollama_model for m in before["models"]
                    ),
                    "first_seconds": measurements[0],
                    "warm_seconds": measurements[1],
                    "gpu": [
                        {
                            "size": m.get("size"),
                            "size_vram": m.get("size_vram"),
                            "context_length": m.get("context_length"),
                        }
                        for m in loaded["models"]
                        if m["name"] == settings.ollama_model
                    ],
                }
            )
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "question, expected",
    [
        (
            "hello world",
            {
                "Hello! Ask me about your recorded orders or products.",
                "I can help you with your recorded orders or products.",
            },
        ),
        ("thanks", {"You're welcome!", "I can help you with your recorded orders or products."}),
        (
            "what can you do",
            "I can help you find current recorded orders and purchase items, show monthly rows, "
            "explain unknown dates, and continue a partial page. I do not forecast future "
            "purchases "
            "or claim an inventory catalog.",
        ),
    ],
)
def test_real_qwen_conversational_modes_are_app_owned(settings, question, expected):
    result = asyncio.run(run_attempt(settings, question))
    assert result["status"] == "complete", result.get("code")
    assert result["tool_calls"] == 0
    assert result["evidence"] == []
    assert result["text"] in (expected if isinstance(expected, set) else {expected})


def test_real_qwen_monthly_items_uses_frozen_august_and_bounded_page(
    monthly_purchase_facts,
):
    events = []

    async def emit(event):
        if event["type"] in {"tool", "terminal"}:
            events.append(event)

    expected = dispatch_tool(
        monthly_purchase_facts, "list_purchase_items", {"month": "2026-08", "limit": 10}
    )
    expected_text, expected_refs = render_month_items(expected)
    result = asyncio.run(
        run_attempt(
            monthly_purchase_facts,
            "what are the items i bought last month",
            now=datetime(2026, 9, 20, 12, tzinfo=UTC),
            emit=emit,
        )
    )
    assert result["status"] == "complete", result.get("code")
    tool_events = [
        event
        for event in events
        if event["type"] == "tool"
        and event.get("name") == "list_purchase_items"
        and "result" in event
    ]
    assert tool_events
    start_events = [
        event
        for event in events
        if event["type"] == "tool"
        and event.get("name") == "list_purchase_items"
        and "arguments" in event
    ]
    assert start_events
    arguments = start_events[0]["arguments"]
    assert arguments["month"] == "2026-08"
    assert arguments.get("limit", 10) == 10 and arguments.get("limit", 10) <= 20
    completed_result = tool_events[0]["result"]
    assert len(encode_result(completed_result).encode("utf-8")) <= 4096
    assert completed_result["data"]["items"] == expected["data"]["items"]
    assert expected_text == result["text"]
    assert [entry["id"] for entry in result["evidence"]] == expected_refs
    assert "partial" in result["text"].lower()
    assert "2026-08" in result["text"]

    second_expected = dispatch_tool(
        monthly_purchase_facts,
        "list_purchase_items",
        {
            "month": arguments["month"],
            "limit": arguments["limit"],
            "cursor": completed_result["next_cursor"],
        },
    )
    second_text, second_refs = render_month_items(second_expected)
    saved_exchange = [
        {"role": "user", "content": "what are the items i bought last month"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "list_purchase_items",
                        "arguments": arguments,
                    }
                }
            ],
        },
        {
            "role": "tool",
            "tool_name": "list_purchase_items",
            "content": encode_result(completed_result),
        },
        {"role": "assistant", "content": result["text"]},
    ]
    continuation_events = []

    async def emit_continuation(event):
        if event["type"] in {"tool", "terminal"}:
            continuation_events.append(event)

    continuation = asyncio.run(
        run_attempt(
            monthly_purchase_facts,
            "next page",
            completed_exchanges=[saved_exchange],
            now=datetime(2026, 10, 20, 12, tzinfo=UTC),
            emit=emit_continuation,
        )
    )
    assert continuation["status"] == "complete", continuation.get("code")
    assert continuation["model_requests"] == 0
    assert continuation["tool_calls"] == 1
    assert continuation["text"] == second_text
    assert [entry["id"] for entry in continuation["evidence"]] == second_refs
    continuation_start = next(
        event for event in continuation_events if event["type"] == "tool" and "arguments" in event
    )
    assert continuation_start["call_id"] == "0:0"
    assert continuation_start["arguments"] == {
        "month": arguments["month"],
        "limit": arguments["limit"],
        "cursor": completed_result["next_cursor"],
    }
