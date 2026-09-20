"""Deterministic real-runtime Stop race over the Chat WebSocket boundary."""

import threading
from dataclasses import replace

from starlette.testclient import TestClient

from shopping.assistant import conversations as saved
from shopping.assistant import runtime
from shopping.assistant.runtime import run_attempt
from shopping.ingestion.pipeline import import_eml
from shopping.web import create_app

ORIGIN = "http://127.0.0.1:8000"
SOCKET = "ws://127.0.0.1:8000/chat/ws"


def receive(socket, kind, *, status=None):
    for _ in range(128):
        value = socket.receive_json()
        if value["type"] == "error":
            raise AssertionError(f"Unexpected error: {value}")
        if value["type"] == "terminal" and not (
            kind == "update" and status in {None, value.get("status")}
        ):
            raise AssertionError(f"Unexpected terminal event: {value}")
        if value["type"] == kind and (
            status is None or value.get("attempt", {}).get("status") == status
        ):
            return value
    raise AssertionError(f"Missing {kind} status={status!r}")


def initialize(client, socket):
    page = client.get("/chat/token", headers={"X-Chat-Page": "1"}).json()
    socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page["token"]})
    assert socket.receive_json()["type"] == "ready"


def connect(client):
    client.get("/chat/token", headers={"X-Chat-Page": "1"})
    return client.websocket_connect(SOCKET, headers={"Origin": ORIGIN})


def draft(socket):
    socket.send_json({"v": 1, "type": "subscribe", "id": "select", "conversation_id": None})
    return receive(socket, "draft")["conversation_id"]


def test_real_runtime_stop_race_persists_only_durable_evidence_and_recovers(
    settings, fixture_dir, monkeypatch
):
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    stop_entered = threading.Event()
    read_started = threading.Event()
    outcome_waiting = threading.Event()
    barriers_enabled = True

    original_accept = saved.accept_command
    original_dispatch = runtime.dispatch_tool

    def accept_command(settings, mutation):
        if barriers_enabled and mutation["kind"] == "stop":
            stop_entered.set()
            assert outcome_waiting.wait(3), "tool result emitter did not reach lock barrier"
        return original_accept(settings, mutation)

    def dispatch_tool(settings, name, arguments):
        if barriers_enabled and not read_started.is_set():
            read_started.set()
            assert stop_entered.wait(3), "Stop did not enter persistence barrier"
        return original_dispatch(settings, name, arguments)

    monkeypatch.setattr(saved, "accept_command", accept_command)
    monkeypatch.setattr(runtime, "dispatch_tool", dispatch_tool)

    async def count(messages):
        return 100

    async def provider(settings, messages):
        if messages[-1]["role"] != "tool":
            yield {
                "type": "tools",
                "calls": [{"id": "call-0", "name": "get_order", "arguments": {"order_id": 1}}],
            }
        else:
            yield {"type": "text", "text": "Recorded order [[order:1]]"}
        yield {"type": "end", "prompt_tokens": 100}

    async def runner(settings, question, **kwargs):
        async def emit(event):
            if barriers_enabled and event["type"] == "tool" and "result" in event:
                outcome_waiting.set()
            await kwargs["emit"](event)

        return await run_attempt(
            settings,
            question,
            stream=provider,
            count_input=count,
            **{key: value for key, value in kwargs.items() if key != "emit"},
            emit=emit,
        )

    try:
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
                        "id": "race",
                        "conversation_id": cid,
                        "text": "Order?",
                    }
                )
                aid = receive(socket, "ack")["outcome"]["attempt_id"]
                assert read_started.wait(3)
                socket.send_json(
                    {
                        "v": 1,
                        "type": "stop",
                        "id": "stop",
                        "conversation_id": cid,
                        "attempt_id": aid,
                    }
                )
                assert receive(socket, "ack")["outcome"]["status"] == "stopping"
                stopped = receive(socket, "update", status="stopped")["attempt"]
                assert stopped["id"] == aid
                assert len(stopped["tools"]) == 1
                assert stopped["tools"][0]["result"] is None
                assert stopped["evidence"] == []
                assert receive(socket, "availability")["availability"] == "available"

            assert saved.get_attempt(settings, cid, aid)["status"] == "stopped"

            with connect(client) as socket:
                initialize(client, socket)
                socket.send_json(
                    {"v": 1, "type": "subscribe", "id": "reload", "conversation_id": cid}
                )
                reloaded = receive(socket, "snapshot")["items"][0]
                assert reloaded["id"] == aid
                assert reloaded["status"] == "stopped"

                barriers_enabled = False
                socket.send_json(
                    {
                        "v": 1,
                        "type": "submit",
                        "id": "recover",
                        "conversation_id": cid,
                        "text": "Show order 1",
                    }
                )
                recovered_id = receive(socket, "ack")["outcome"]["attempt_id"]
                recovered = receive(socket, "update", status="complete")["attempt"]
                assert recovered["id"] == recovered_id
                assert recovered["evidence"]
    finally:
        barriers_enabled = False
        stop_entered.set()
        outcome_waiting.set()
