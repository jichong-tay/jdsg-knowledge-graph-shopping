"""Monthly pagination continuation across the real chat boundary."""

import re
from dataclasses import replace
from datetime import UTC, datetime

from starlette.testclient import TestClient

from shopping.assistant.answers import render_month_items
from shopping.assistant.runtime import run_attempt
from shopping.assistant.tools import dispatch_tool
from shopping.web import create_app

ORIGIN = "http://127.0.0.1:8000"
SOCKET = "ws://127.0.0.1:8000/chat/ws"


def connect(client):
    client.get("/chat/token", headers={"X-Chat-Page": "1"})
    return client.websocket_connect(SOCKET, headers={"Origin": ORIGIN})


def initialize(client, socket):
    page = client.get("/chat/token", headers={"X-Chat-Page": "1"}).json()
    socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page["token"]})
    assert socket.receive_json()["type"] == "ready"


def receive(socket, kind, *, status=None):
    for _ in range(128):
        value = socket.receive_json()
        if value["type"] == "error":
            raise AssertionError(f"Unexpected error: {value}")
        if value["type"] == "terminal":
            raise AssertionError(f"Unexpected terminal event: {value}")
        if (
            value["type"] == "update"
            and value.get("attempt", {}).get("status") in {"failed", "stopped"}
            and value.get("attempt", {}).get("status") != status
        ):
            raise AssertionError(f"Unexpected terminal update: {value}")
        if value["type"] == kind and (
            status is None or value.get("attempt", {}).get("status") == status
        ):
            return value
    raise AssertionError(f"Missing {kind} status={status!r}")


def draft(socket):
    socket.send_json({"v": 1, "type": "subscribe", "id": "draft", "conversation_id": None})
    return receive(socket, "draft")["conversation_id"]


def test_monthly_continuation_uses_saved_cursor_and_scope(monthly_purchase_facts, monkeypatch):
    settings = monthly_purchase_facts
    first_now = datetime(2026, 9, 20, tzinfo=UTC)
    second_now = datetime(2026, 10, 20, tzinfo=UTC)
    first = dispatch_tool(settings, "list_purchase_items", {"month": "2026-08", "limit": 3})
    second_args = {
        "month": "2026-08",
        "limit": 3,
        "cursor": first["next_cursor"],
    }
    second = dispatch_tool(settings, "list_purchase_items", second_args)
    expected_text, expected_refs = render_month_items(second)
    expected_evidence = [entry for entry in second["evidence"] if entry["id"] in expected_refs]
    provider_calls = []

    async def count(messages):
        return 100

    async def provider(settings, messages):
        provider_calls.append(messages)
        if len(provider_calls) > 1:
            raise AssertionError("continuation must not invoke the model provider")
        yield {
            "type": "tools",
            "calls": [
                {
                    "id": "month-0",
                    "name": "list_purchase_items",
                    "arguments": {"month": "2026-08", "limit": 3},
                }
            ],
        }
        yield {"type": "end", "prompt_tokens": 100}

    async def runner(settings, question, **kwargs):
        return await run_attempt(
            settings,
            question,
            stream=provider,
            count_input=count,
            now=first_now if question != "next page" else second_now,
            **kwargs,
        )

    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=runner), base_url=ORIGIN
    ) as client:
        with connect(client) as socket:
            initialize(client, socket)
            cid = draft(socket)
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "first",
                    "conversation_id": cid,
                    "text": "Show purchase items for August 2026",
                }
            )
            first_id = receive(socket, "ack")["outcome"]["attempt_id"]
            first_attempt = receive(socket, "update", status="complete")["attempt"]
            assert first_attempt["id"] == first_id
            assert first_attempt["tools"][0]["result"]["data"]["items"] == first["data"]["items"]
            receive(socket, "availability")

        with connect(client) as socket:
            initialize(client, socket)
            socket.send_json({"v": 1, "type": "subscribe", "id": "reload", "conversation_id": cid})
            restored_first = receive(socket, "snapshot")["items"][0]
            assert restored_first["id"] == first_id
            assert restored_first["tools"][0]["result"]["data"]["items"] == first["data"]["items"]
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "next",
                    "conversation_id": cid,
                    "text": "next page",
                }
            )
            second_id = receive(socket, "ack")["outcome"]["attempt_id"]
            second_attempt = receive(socket, "update", status="complete")["attempt"]
            assert second_attempt["id"] == second_id
            assert second_attempt["text"] == expected_text
            assert second_attempt["evidence"] == expected_evidence
            assert re.fullmatch(r"\d+:\d+", second_attempt["tools"][0]["call_id"])
            assert second_attempt["tools"][0]["result"]["data"]["month"] == "2026-08"
            assert second_attempt["tools"][0]["result"]["data"]["limit"] == 3
            assert second_attempt["tools"][0]["result"]["data"]["items"] == second["data"]["items"]
            assert len(provider_calls) == 1
            receive(socket, "availability")

        with connect(client) as socket:
            initialize(client, socket)
            socket.send_json({"v": 1, "type": "subscribe", "id": "reload", "conversation_id": cid})
            restored = receive(socket, "snapshot")["items"][0]
            assert restored["id"] == second_id
            assert restored["text"] == expected_text
            assert restored["evidence"] == expected_evidence


def test_monthly_continuation_expired_cursor_reports_restart(monthly_purchase_facts, monkeypatch):
    settings = monthly_purchase_facts
    provider_calls = 0
    dispatch_calls = 0

    async def count(messages):
        return 100

    async def provider(settings, messages):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls > 1:
            raise AssertionError("expired cursor must not invoke the model provider")
        yield {
            "type": "tools",
            "calls": [
                {
                    "id": "month-0",
                    "name": "list_purchase_items",
                    "arguments": {"month": "2026-08", "limit": 3},
                }
            ],
        }
        yield {"type": "end", "prompt_tokens": 100}

    async def runner(settings, question, **kwargs):
        return await run_attempt(settings, question, stream=provider, count_input=count, **kwargs)

    from shopping.assistant import runtime

    original_dispatch = runtime.dispatch_tool

    def guarded_dispatch(*args, **kwargs):
        nonlocal dispatch_calls
        dispatch_calls += 1
        if dispatch_calls > 1:
            raise AssertionError("expired cursor must not dispatch a fresh query")
        return original_dispatch(*args, **kwargs)

    monkeypatch.setattr(runtime, "dispatch_tool", guarded_dispatch)

    with (
        TestClient(
            create_app(replace(settings, app_origin=ORIGIN), chat_runner=runner), base_url=ORIGIN
        ) as client,
        connect(client) as socket,
    ):
        initialize(client, socket)
        cid = draft(socket)
        socket.send_json(
            {
                "v": 1,
                "type": "submit",
                "id": "first",
                "conversation_id": cid,
                "text": "Show purchase items for August 2026",
            }
        )
        receive(socket, "ack")
        receive(socket, "update", status="complete")
        receive(socket, "availability")
        monkeypatch.setattr("shopping.assistant.tools._CURSOR_KEY", b"expired-key")
        socket.send_json(
            {
                "v": 1,
                "type": "submit",
                "id": "next",
                "conversation_id": cid,
                "text": "next page",
            }
        )
        receive(socket, "ack")
        failed = receive(socket, "update", status="failed")["attempt"]
        assert failed["code"] == "invalid_cursor"
        assert "2026-08" in failed["text"]
        assert "restart" in failed["text"].lower()
        assert provider_calls == 1
        assert dispatch_calls == 1
