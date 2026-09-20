"""Saved-state streaming over the real WebSocket boundary, with a fake model loop."""

from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from shopping.assistant import conversations as saved
from shopping.web import create_app

ORIGIN = "http://127.0.0.1:8000"
SOCKET = "ws://127.0.0.1:8000/chat/ws"


def initialize(client, socket):
    page = client.get("/chat/token", headers={"X-Chat-Page": "1"}).json()
    socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page["token"]})
    assert socket.receive_json()["type"] == "ready"


def receive(socket, kind, *, status=None):
    for _ in range(128):
        value = socket.receive_json()
        if value["type"] == kind and (
            status is None or value.get("attempt", {}).get("status") == status
        ):
            return value
    raise AssertionError(f"Missing {kind}")


def connect(client):
    # Set the signed cookie before the WebSocket handshake.
    client.get("/chat/token", headers={"X-Chat-Page": "1"})
    return client.websocket_connect(SOCKET, headers={"Origin": ORIGIN})


def draft(socket):
    socket.send_json({"v": 1, "type": "subscribe", "id": "select", "conversation_id": None})
    return receive(socket, "draft")["conversation_id"]


async def answer(settings, question, *, emit, **kwargs):
    # The question has already been accepted before any provider work.
    assert saved.list_conversations(settings)["items"]
    await emit({"type": "status", "status": "generating"})
    await emit({"type": "text", "text": "Please clarify which product."})
    return {
        "status": "complete",
        "code": None,
        "text": "Please clarify which product.",
        "evidence": [],
    }


def test_send_is_saved_before_generation_and_retransmission_does_not_repeat(settings):
    calls = []

    async def provider(*args, **kwargs):
        calls.append(True)
        return await answer(*args, **kwargs)

    configured = replace(settings, app_origin=ORIGIN)
    with TestClient(create_app(configured, chat_runner=provider), base_url=ORIGIN) as client:
        with connect(client) as socket:
            initialize(client, socket)
            cid = draft(socket)
            command = {
                "v": 1,
                "type": "submit",
                "id": "send-1",
                "conversation_id": cid,
                "text": "Which product?",
            }
            socket.send_json(command)
            ack = receive(socket, "ack")
            assert ack["outcome"]["status"] == "accepted"
            complete = receive(socket, "update", status="complete")
            assert complete["attempt"]["text"] == "Please clarify which product."
            assert (
                saved.get_attempt(settings, cid, complete["attempt"]["id"])["text"]
                == complete["attempt"]["text"]
            )
            socket.send_json(command)
            assert receive(socket, "ack")["outcome"] == ack["outcome"]
            assert calls == [True]
            socket.send_json({**command, "text": "Different"})
            assert receive(socket, "error")["code"] == "command_conflict"


@pytest.mark.parametrize(
    ("answer_text", "expected_prefix"),
    [
        (
            "An unsupported claim about your purchases.",
            "Here are the recorded details from this lookup:",
        ),
        (
            "The recorded total is SGD 14.00. [[order:1]]",
            "Here are the recorded details from this lookup:",
        ),
    ],
)
def test_real_runtime_tool_answer_is_saved_and_restored(
    settings, fixture_dir, answer_text, expected_prefix
):
    from functools import partial

    from shopping.assistant.runtime import run_attempt
    from shopping.ingestion.pipeline import import_eml

    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)

    async def count(messages):
        return 100

    async def provider(settings, messages):
        if messages[-1]["role"] == "tool":
            yield {"type": "text", "text": answer_text}
        else:
            yield {
                "type": "tools",
                "calls": [{"id": "call-0", "name": "list_recent_orders", "arguments": {}}],
            }
        yield {"type": "end", "prompt_tokens": 100}

    runner = partial(run_attempt, stream=provider, count_input=count)
    configured = replace(settings, app_origin=ORIGIN)
    with TestClient(create_app(configured, chat_runner=runner), base_url=ORIGIN) as client:
        with connect(client) as socket:
            initialize(client, socket)
            cid = draft(socket)
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "uncited-recent",
                    "conversation_id": cid,
                    "text": "What is my latest order?",
                }
            )
            aid = receive(socket, "ack")["outcome"]["attempt_id"]
            for _ in range(20):
                attempt = receive(socket, "update")["attempt"]
                if attempt["status"] in {"complete", "failed"}:
                    break
            assert attempt["status"] == "complete", attempt.get("code")
            assert attempt["text"].startswith(expected_prefix)
            assert "SGD 14.00" in attempt["text"]
            assert "unsupported claim" not in attempt["text"]
            assert any(item["id"] == "order:1" for item in attempt["evidence"])
            receive(socket, "availability")
        with connect(client) as resumed:
            initialize(client, resumed)
            resumed.send_json(
                {"v": 1, "type": "subscribe", "id": "restore", "conversation_id": cid}
            )
            restored = receive(resumed, "snapshot")["items"][0]
            assert restored["id"] == aid
            assert restored["status"] == "complete"
            assert restored["text"] == attempt["text"]
            assert restored["evidence"] == attempt["evidence"]


def test_disconnect_continues_and_stop_retry_targets_saved_attempt(settings):
    import asyncio

    async def waiting(settings, question, *, emit, stop, **kwargs):
        await emit({"type": "text", "text": "Saved partial"})
        await stop.wait()
        await asyncio.sleep(0.05)
        return {
            "status": "incomplete",
            "code": "cancelled",
            "text": "Saved partial",
            "evidence": [],
        }

    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=waiting), base_url=ORIGIN
    ) as client:
        with connect(client) as socket:
            initialize(client, socket)
            cid = draft(socket)
            socket.send_json(
                {"v": 1, "type": "submit", "id": "send", "conversation_id": cid, "text": "Wait"}
            )
            aid = receive(socket, "ack")["outcome"]["attempt_id"]
            partial = receive(socket, "update", status="running")
            while not partial["attempt"]["text"]:
                partial = receive(socket, "update", status="running")
        assert saved.get_attempt(settings, cid, aid)["status"] == "running"
        with connect(client) as resumed:
            initialize(client, resumed)
            resumed.send_json({"v": 1, "type": "subscribe", "id": "resume", "conversation_id": cid})
            assert receive(resumed, "snapshot")["items"][0]["text"] == "Saved partial"
            resumed.send_json(
                {"v": 1, "type": "stop", "id": "stop", "conversation_id": cid, "attempt_id": aid}
            )
            assert receive(resumed, "ack")["outcome"]["status"] == "stopping"
            assert (
                receive(resumed, "update", status="stopped")["attempt"]["text"] == "Saved partial"
            )
            receive(resumed, "availability")
            retry = {
                "v": 1,
                "type": "retry",
                "id": "retry",
                "conversation_id": cid,
                "attempt_id": aid,
            }
            resumed.send_json(retry)
            new_aid = receive(resumed, "ack")["outcome"]["attempt_id"]
            assert new_aid != aid
            resumed.send_json(retry)
            assert receive(resumed, "ack")["outcome"]["attempt_id"] == new_aid
            resumed.send_json(
                {
                    "v": 1,
                    "type": "stop",
                    "id": "old-stop",
                    "conversation_id": cid,
                    "attempt_id": aid,
                }
            )
            assert receive(resumed, "ack")["outcome"]["status"] == "already_finished"
            resumed.send_json(
                {
                    "v": 1,
                    "type": "delete",
                    "id": "delete",
                    "conversation_id": cid,
                    "confirmed": True,
                }
            )
            assert receive(resumed, "ack")["outcome"]["status"] == "deleting"
            assert receive(resumed, "gone")["conversation_id"] == cid
            import time

            time.sleep(1)  # The shared session budget includes both connections.
            resumed.send_json(retry)
            assert receive(resumed, "ack")["outcome"]["status"] == "gone"


def test_stop_during_controlled_tool_return_saves_only_durable_evidence_and_recovers(settings):
    import asyncio
    import threading

    tool_returned = threading.Event()
    release = threading.Event()

    async def controlled(settings, question, *, emit, stop, **kwargs):
        await emit({"type": "status", "status": "generating"})
        tool_returned.set()
        await asyncio.to_thread(release.wait)
        if stop.is_set():
            return {
                "status": "incomplete",
                "code": "cancelled",
                "text": "",
                "evidence": [{"id": "order:1"}],
            }
        return {"status": "complete", "code": None, "text": "Done", "evidence": []}

    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=controlled), base_url=ORIGIN
    ) as client:
        with connect(client) as socket:
            initialize(client, socket)
            cid = draft(socket)
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "race-send",
                    "conversation_id": cid,
                    "text": "Wait",
                }
            )
            aid = receive(socket, "ack")["outcome"]["attempt_id"]
            assert tool_returned.wait(2)
            socket.send_json(
                {
                    "v": 1,
                    "type": "stop",
                    "id": "race-stop",
                    "conversation_id": cid,
                    "attempt_id": aid,
                }
            )
            assert receive(socket, "ack")["outcome"]["status"] == "stopping"
            release.set()
            stopped = receive(socket, "update", status="stopped")["attempt"]
            assert stopped["evidence"] == []
            assert receive(socket, "availability")["availability"] == "available"
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "recovery",
                    "conversation_id": cid,
                    "text": "Again",
                }
            )
            new_attempt = receive(socket, "ack")["outcome"]["attempt_id"]
            assert receive(socket, "update", status="complete")["attempt"]["id"] == new_attempt


@pytest.mark.parametrize("marker", ["[[clarification]]", "[[unsupported]]"])
def test_marker_only_runtime_is_saved_failed_and_next_attempt_completes(settings, marker):
    from functools import partial

    from shopping.assistant.runtime import run_attempt

    calls = 0

    async def stream(settings, messages):
        nonlocal calls
        calls += 1
        yield {"type": "text", "text": marker if calls == 1 else "[[clarification]] Which product?"}
        yield {"type": "end", "prompt_tokens": 100}

    async def count(messages):
        return 100

    runner = partial(run_attempt, stream=stream, count_input=count)
    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=runner), base_url=ORIGIN
    ) as client:
        with connect(client) as socket:
            initialize(client, socket)
            cid = draft(socket)
            socket.send_json(
                {"v": 1, "type": "submit", "id": "marker", "conversation_id": cid, "text": "Help"}
            )
            first = receive(socket, "ack")["outcome"]["attempt_id"]
            failed = receive(socket, "update", status="failed")["attempt"]
            assert (
                failed["id"] == first and failed["code"] == "empty_response" and not failed["text"]
            )
            assert saved.get_attempt(settings, cid, first)["status"] == "failed"
            assert receive(socket, "availability")["availability"] == "available"
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "marker-next",
                    "conversation_id": cid,
                    "text": "Again",
                }
            )
            second = receive(socket, "ack")["outcome"]["attempt_id"]
            complete = receive(socket, "update", status="complete")["attempt"]
            assert complete["id"] == second and complete["text"].strip()
            assert saved.get_attempt(settings, cid, first)["status"] == "failed"


def test_failed_stale_subscription_keeps_a_updates_on_same_peer(settings):
    async def answer(settings, question, *, emit, **kwargs):
        await emit({"type": "text", "text": "Saved answer"})
        return {"status": "complete", "code": None, "text": "Saved answer", "evidence": []}

    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=answer), base_url=ORIGIN
    ) as client:
        with connect(client) as socket:
            initialize(client, socket)
            a = draft(socket)
            socket.send_json(
                {"v": 1, "type": "submit", "id": "a-send", "conversation_id": a, "text": "A"}
            )
            receive(socket, "ack")
            receive(socket, "update", status="complete")
            socket.send_json(
                {
                    "v": 1,
                    "type": "subscribe",
                    "id": "stale-b",
                    "conversation_id": "missing-conversation",
                }
            )
            assert receive(socket, "error")["code"] == "gone"
            socket.send_json(
                {
                    "v": 1,
                    "type": "rename",
                    "id": "a-rename",
                    "conversation_id": a,
                    "text": "A updated",
                }
            )
            assert receive(socket, "ack")["outcome"]["status"] == "renamed"
            update = receive(socket, "update")
            assert update["conversation"]["id"] == a


def test_initial_stale_restore_still_hydrates_saved_library(settings):
    def seed(label):
        cid = saved.new_draft(settings)
        accepted = saved.accept_command(
            settings, {"kind": "submit", "id": label, "conversation_id": cid, "text": label}
        )
        attempt = saved.get_attempt(settings, cid, accepted["attempt_id"])
        saved.checkpoint(
            settings,
            cid,
            attempt["id"],
            expected_version=attempt["version"],
            text="Saved",
            status="complete",
        )
        return cid

    first = seed("first")
    second = seed("second")
    with TestClient(create_app(replace(settings, app_origin=ORIGIN)), base_url=ORIGIN) as client:
        with connect(client) as socket:
            initialize(client, socket)
            library = receive(socket, "library")
            ids = {item["id"] for item in library["items"]}
            assert first in ids and second in ids
            socket.send_json(
                {
                    "v": 1,
                    "type": "subscribe",
                    "id": "stale-restore",
                    "conversation_id": "gone-conversation",
                }
            )
            assert receive(socket, "error")["code"] == "gone"


def test_persistence_failure_stops_generation_without_broadcasting_unsaved_text(settings):
    from contextlib import closing

    from shopping.storage.connection import connect_database

    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "CREATE TRIGGER fail_chat_save BEFORE UPDATE ON conversations "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=answer), base_url=ORIGIN
    ) as client:
        with connect(client) as socket:
            initialize(client, socket)
            cid = draft(socket)
            socket.send_json(
                {"v": 1, "type": "submit", "id": "send", "conversation_id": cid, "text": "Question"}
            )
            aid = receive(socket, "ack")["outcome"]["attempt_id"]
            assert receive(socket, "error")["code"] == "persistence_or_runtime_failure"
            assert saved.get_attempt(settings, cid, aid)["text"] == ""
            assert receive(socket, "availability")["availability"] == "faulted"
            assert client.get("/orders").status_code == 200
            assert client.get("/api/health").status_code == 200


def test_restart_recovers_partial_attempt_without_rerunning_and_can_rename(settings):
    cid = saved.new_draft(settings)
    accepted = saved.accept_command(
        settings,
        {"kind": "submit", "id": "old", "conversation_id": cid, "text": "<script>typed</script>"},
    )
    saved.checkpoint(
        settings, cid, accepted["attempt_id"], expected_version=1, text="Previous partial"
    )
    calls = []

    async def provider(*args, **kwargs):
        calls.append(True)
        return await answer(*args, **kwargs)

    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=provider), base_url=ORIGIN
    ) as client:
        with connect(client) as socket:
            initialize(client, socket)
            receive(socket, "library")
            socket.send_json({"v": 1, "type": "subscribe", "id": "resume", "conversation_id": cid})
            snapshot = receive(socket, "snapshot")
            assert snapshot["items"][0]["status"] == "interrupted"
            assert snapshot["items"][0]["text"] == "Previous partial"
            assert calls == []
            socket.send_json(
                {
                    "v": 1,
                    "type": "rename",
                    "id": "name",
                    "conversation_id": cid,
                    "text": "<img src=x>",
                }
            )
            assert receive(socket, "ack")["outcome"]["status"] == "renamed"
            assert receive(socket, "update")["conversation"]["title"] == "<img src=x>"


def test_large_saved_snapshot_is_chunked_under_wire_limit(settings):
    import base64
    import json

    cid = saved.new_draft(settings)
    accepted = saved.accept_command(
        settings, {"kind": "submit", "id": "large", "conversation_id": cid, "text": "q" * 4000}
    )
    saved.checkpoint(
        settings,
        cid,
        accepted["attempt_id"],
        expected_version=1,
        text="a" * 64000,
        status="complete",
    )
    with TestClient(create_app(replace(settings, app_origin=ORIGIN)), base_url=ORIGIN) as client:
        with connect(client) as socket:
            initialize(client, socket)
            receive(socket, "library")
            socket.send_json({"v": 1, "type": "subscribe", "id": "resume", "conversation_id": cid})
            chunks = []
            while True:
                raw = socket.receive_text()
                assert len(raw.encode()) <= 65536
                frame = json.loads(raw)
                assert frame["type"] == "part"
                chunks.append(base64.b64decode(frame["data"]))
                if len(chunks) == frame["total"]:
                    break
            snapshot = json.loads(b"".join(chunks))
            assert snapshot["items"][0]["text"] == "a" * 64000


def test_slow_subscriber_is_dropped_without_stalling_other_tabs(settings):
    import asyncio
    import threading

    release = threading.Event()

    async def provider(settings, question, *, emit, **kwargs):
        while not release.is_set():
            await asyncio.sleep(0.005)
        for index in range(8):
            await emit(
                {
                    "type": "tool",
                    "call_id": f"1:{index}",
                    "name": "get_order",
                    "status": "running",
                    "arguments": {"order_id": 1},
                }
            )
            await emit(
                {
                    "type": "tool",
                    "call_id": f"1:{index}",
                    "name": "get_order",
                    "status": "not_found",
                    "result": {
                        "status": "not_found",
                        "data": {},
                        "evidence": [],
                        "next_cursor": None,
                        "truncated": False,
                    },
                }
            )
        return {"status": "complete", "text": "No matching order.", "code": None, "evidence": []}

    app = create_app(replace(settings, app_origin=ORIGIN), chat_runner=provider)

    async def network(scope, incoming, outgoing):
        slow = (b"x-slow-test", b"1") in scope.get("headers", [])
        sent = 0

        async def send(message):
            nonlocal sent
            if slow and message["type"] == "websocket.send":
                sent += 1
                if sent > 1:
                    await asyncio.Event().wait()  # Network backpressure after authentication.
            await outgoing(message)

        await app(scope, incoming, send)

    import pytest
    from starlette.websockets import WebSocketDisconnect

    with TestClient(network, base_url=ORIGIN) as client:
        with connect(client) as fast:
            initialize(client, fast)
            cid = draft(fast)
            fast.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "send",
                    "conversation_id": cid,
                    "text": "Find order",
                }
            )
            receive(fast, "ack")
            with client.websocket_connect(
                SOCKET, headers={"Origin": ORIGIN, "X-Slow-Test": "1"}
            ) as slow:
                initialize(client, slow)
                slow.send_json({"v": 1, "type": "subscribe", "id": "slow", "conversation_id": cid})
                release.set()
                assert (
                    receive(fast, "update", status="complete")["attempt"]["text"]
                    == "No matching order."
                )
                with pytest.raises(WebSocketDisconnect) as closed:
                    slow.receive_json()
                assert closed.value.code == 4008


def test_shutdown_during_acceptance_never_starts_new_model_work(settings):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing

    from shopping.storage.connection import connect_database, transaction

    calls = []
    locked, release = threading.Event(), threading.Event()

    def hold_writer():
        with (
            closing(connect_database(settings.database_path)) as connection,
            transaction(connection),
        ):
            locked.set()
            release.wait(2)

    async def provider(*args, **kwargs):
        calls.append(True)
        return await answer(*args, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with TestClient(
            create_app(replace(settings, app_origin=ORIGIN), chat_runner=provider), base_url=ORIGIN
        ) as client:
            with connect(client) as socket:
                initialize(client, socket)
                cid = draft(socket)
                writer = pool.submit(hold_writer)
                assert locked.wait(1)
                socket.send_json(
                    {
                        "v": 1,
                        "type": "submit",
                        "id": "closing",
                        "conversation_id": cid,
                        "text": "Do not run on shutdown",
                    }
                )
                time.sleep(0.05)  # The accepted-command transaction is waiting on the writer.
            timer = threading.Timer(0.2, release.set)
            timer.start()
        writer.result()
        timer.join()
    assert calls == []
    outcome = saved.command_status(settings, "closing")
    assert outcome is not None
    assert saved.get_attempt(settings, cid, outcome["attempt_id"])["status"] == "interrupted"


def test_completed_first_stays_complete_and_rename_delete_reach_other_tabs(settings):
    with TestClient(
        create_app(replace(settings, app_origin=ORIGIN), chat_runner=answer), base_url=ORIGIN
    ) as client:
        with connect(client) as first:
            initialize(client, first)
            cid = draft(first)
            first.send_json(
                {"v": 1, "type": "submit", "id": "send", "conversation_id": cid, "text": "Question"}
            )
            aid = receive(first, "ack")["outcome"]["attempt_id"]
            receive(first, "update", status="complete")
            receive(first, "availability")
            with connect(client) as second:
                initialize(client, second)
                second.send_json(
                    {"v": 1, "type": "subscribe", "id": "select-two", "conversation_id": cid}
                )
                receive(second, "snapshot")
                first.send_json(
                    {
                        "v": 1,
                        "type": "stop",
                        "id": "late-stop",
                        "conversation_id": cid,
                        "attempt_id": aid,
                    }
                )
                assert receive(first, "ack")["outcome"]["status"] == "already_finished"
                first.send_json(
                    {
                        "v": 1,
                        "type": "rename",
                        "id": "rename",
                        "conversation_id": cid,
                        "text": "Renamed",
                    }
                )
                receive(first, "ack")
                update = receive(second, "update")
                while update["conversation"]["title"] != "Renamed":
                    update = receive(second, "update")
                assert saved.get_attempt(settings, cid, aid)["status"] == "complete"
                first.send_json(
                    {
                        "v": 1,
                        "type": "delete",
                        "id": "delete",
                        "conversation_id": cid,
                        "confirmed": True,
                    }
                )
                receive(first, "ack")
                assert receive(second, "gone")["conversation_id"] == cid
