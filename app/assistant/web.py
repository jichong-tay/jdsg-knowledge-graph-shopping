"""Protected browser access and coordination of one durable response task."""

import asyncio
import base64
import json
import re
import secrets
import sqlite3
import time
from contextlib import suppress
from urllib.parse import urlsplit
from uuid import uuid4

from fasthtml.common import to_xml
from itsdangerous import BadSignature, TimestampSigner
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.assistant import conversations as saved
from app.assistant import runtime
from app.assistant.ui import chat_page
from app.config import Settings
from app.web_ui import document

INITIALIZE_SECONDS = 5.0
HEARTBEAT_SECONDS = 40.0
MAX_SOCKETS = 10
MAX_FRAME = 64 * 1024
MAX_BUFFER = 256 * 1024
MAX_UPDATES = 16
CHECKPOINT_SECONDS = 0.25
_PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def _allowed(settings: Settings, headers, *, websocket: bool = False) -> bool:
    if not settings.chat_enabled:
        return False
    origin = settings.app_origin
    if settings.environment == "development" and urlsplit(origin).hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        return False
    if headers.get("host") != urlsplit(origin).netloc:
        return False
    supplied = headers.get("origin")
    if websocket or supplied is not None:
        if supplied != origin:
            return False
    return headers.get("sec-fetch-site") not in {"cross-site", "same-site"}


def register_chat(app, settings: Settings, *, runner=runtime.run_attempt) -> None:
    signer = TimestampSigner(app.secret_key, salt="shopping-chat-page-v1")
    state = {
        "settings": settings,
        "signer": signer,
        "lock": asyncio.Lock(),
        "peers": [],
        "rates": {},
        "active": None,
        "ready": False,
        "runner": runner,
        "faulted": False,
        "commands": set(),
    }
    app.state.chat = state

    @app.on_event("startup")
    async def startup():
        await asyncio.to_thread(saved.interrupt_unfinished, settings)
        state["ready"] = True

    @app.on_event("shutdown")
    async def shutdown():
        state["ready"] = False
        if state["commands"]:
            _, pending = await asyncio.wait(state["commands"], timeout=runtime.CLEANUP_SECONDS)
            for task in pending:
                task.cancel()
        active = state["active"]
        if active:
            active["stop"].set()
            _, pending = await asyncio.wait({active["task"]}, timeout=runtime.CLEANUP_SECONDS + 1)
            for task in pending:
                task.cancel()
        for peer in tuple(state["peers"]):
            peer["closed"].set()

    async def websocket(socket: WebSocket):
        await _socket(state, socket)

    async def page(request: Request):
        if not settings.chat_enabled:
            return HTMLResponse(
                "Chat needs SHOPPING_APP_ORIGIN configuration.",
                status_code=503,
                headers=_PRIVATE_HEADERS,
            )
        if not _allowed(settings, request.headers):
            return HTMLResponse(
                "Chat origin is not allowed.", status_code=403, headers=_PRIVATE_HEADERS
            )
        request.session.setdefault("chat_id", secrets.token_urlsafe(32))
        return HTMLResponse(
            to_xml(
                document(
                    "Chat",
                    "Shopping Assistant",
                    chat_page(settings.ollama_model),
                    current_path="/chat",
                    environment=settings.environment,
                )
            ),
            headers=_PRIVATE_HEADERS,
        )

    async def page_token(request: Request):
        if not _allowed(settings, request.headers) or request.headers.get("x-chat-page") != "1":
            return JSONResponse({"code": "forbidden"}, status_code=403, headers=_PRIVATE_HEADERS)
        session_id = request.session.setdefault("chat_id", secrets.token_urlsafe(32))
        return JSONResponse(
            {"token": signer.sign(session_id).decode(), "expires_in": settings.chat_token_seconds},
            headers=_PRIVATE_HEADERS,
        )

    app.router.routes.extend(
        [
            Route("/chat", page),
            Route("/chat/token", page_token),
            WebSocketRoute("/chat/ws", websocket),
        ]
    )


def _encode(value: dict) -> str:
    return json.dumps({"v": 1, **value}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _queue(peer: dict, payload: dict) -> None:
    """Never await a slow tab. Oversized snapshots are bounded multipart messages."""
    raw = _encode(payload)
    data = raw.encode("utf-8")
    if len(data) <= MAX_FRAME:
        frames = [raw]
    else:
        if len(data) > 192 * 1024:
            peer["closed"].set()
            return
        chunks = [data[index : index + 32 * 1024] for index in range(0, len(data), 32 * 1024)]
        transfer = uuid4().hex
        frames = [
            _encode(
                {
                    "type": "part",
                    "transfer": transfer,
                    "index": index,
                    "total": len(chunks),
                    "data": base64.b64encode(chunk).decode(),
                }
            )
            for index, chunk in enumerate(chunks)
        ]
    size = sum(len(frame.encode("utf-8")) for frame in frames)
    if peer["queue"].qsize() + len(frames) > MAX_UPDATES or peer["bytes"] + size > MAX_BUFFER:
        peer["closed"].set()
        return
    peer["bytes"] += size
    for frame in frames:
        peer["queue"].put_nowait(frame)


async def _sender(socket: WebSocket, peer: dict) -> None:
    while True:
        frame = await peer["queue"].get()
        await socket.send_text(frame)
        peer["bytes"] -= len(frame.encode("utf-8"))


async def _receive(socket: WebSocket, seconds: float) -> dict:
    async with asyncio.timeout(seconds):
        message = await socket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect()
    raw = message.get("text")
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_FRAME:
        raise ValueError("invalid_frame")
    try:
        value = json.loads(raw)
    except ValueError, RecursionError:
        raise ValueError("invalid_frame") from None
    if type(value) is not dict or type(value.get("v")) is not int or value["v"] != 1:
        raise ValueError("invalid_frame")
    return value


def _command_id(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) is None:
        raise ValueError("invalid_command")


def _rate(state: dict, session: str) -> None:
    now = time.monotonic()
    rates = state["rates"]
    for key in list(rates):
        if now - rates[key][1] > 60:
            del rates[key]
    if session not in rates and len(rates) >= 1024:
        raise ValueError("rate_limit")
    tokens, previous = rates.get(session, (10.0, now))
    tokens = min(10.0, tokens + now - previous)
    if tokens < 1:
        raise ValueError("rate_limit")
    rates[session] = (tokens - 1, now)


async def _socket(state: dict, socket: WebSocket) -> None:
    if not state["ready"] or not _allowed(state["settings"], socket.headers, websocket=True):
        await socket.close(code=4403)
        return
    if len(state["peers"]) >= MAX_SOCKETS:
        await socket.close(code=1013)
        return
    peer = {
        "queue": asyncio.Queue(),
        "bytes": 0,
        "closed": asyncio.Event(),
        "conversation_id": None,
        "authenticated": False,
    }
    state["peers"].append(peer)
    tasks = []
    close_code = 4000
    expires = None
    try:
        await socket.accept()
        first = await _receive(socket, INITIALIZE_SECONDS)
        if set(first) != {"v", "type", "id", "token"} or first["type"] != "initialize":
            raise ValueError("unauthorized")
        _command_id(first["id"])
        if type(first["token"]) is not str:
            raise ValueError("unauthorized")
        session = socket.scope.get("session", {}).get("chat_id")
        value, issued = state["signer"].unsign(
            first["token"], max_age=state["settings"].chat_token_seconds, return_timestamp=True
        )
        if not session or not secrets.compare_digest(value.decode(), session):
            raise ValueError("unauthorized")
        expires = issued.timestamp() + state["settings"].chat_token_seconds
        _rate(state, session)
        peer["authenticated"] = True
        _queue(peer, {"type": "ready", "id": first["id"], "availability": _availability(state)})

        async def read_commands():
            while True:
                remaining = expires - time.time()
                if remaining <= 0:
                    raise ValueError("expired")
                command = await _receive(socket, min(HEARTBEAT_SECONDS, remaining))
                if time.time() >= expires:
                    raise ValueError("expired")
                if command == {"v": 1, "type": "ping"}:
                    _queue(peer, {"type": "pong", "availability": _availability(state)})
                    continue
                _rate(state, session)
                if len(state["commands"]) >= MAX_SOCKETS:
                    raise ValueError("rate_limit")
                # Accepted work must finish even if its originating socket disappears.
                task = asyncio.create_task(_command(state, peer, command))
                state["commands"].add(task)
                task.add_done_callback(lambda done: _command_done(state, done))
                await asyncio.shield(task)

        expiry = asyncio.create_task(asyncio.sleep(max(0, expires - time.time())))
        tasks = [
            expiry,
            asyncio.create_task(_sender(socket, peer)),
            asyncio.create_task(read_commands()),
            asyncio.create_task(peer["closed"].wait()),
        ]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if expiry in done:
            close_code = 4401
        for task in done:
            task.result()
    except WebSocketDisconnect, asyncio.CancelledError:
        pass
    except BadSignature:
        close_code = 4401
    except ValueError as error:
        close_code = (
            4429
            if str(error) == "rate_limit"
            else 4401
            if str(error) in {"expired", "unauthorized"}
            else 4400
        )
    except TimeoutError:
        close_code = 4401 if expires is None or time.time() >= expires else 4000
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
        peer["authenticated"] = False
        state["peers"].remove(peer)
        with suppress(RuntimeError, WebSocketDisconnect, asyncio.CancelledError):
            await socket.close(code=4008 if peer["closed"].is_set() else close_code)


def _availability(state: dict) -> str:
    if state["faulted"] or runtime.availability() == "faulted":
        return "faulted"
    return "busy" if state["active"] else runtime.availability()


async def _snapshot(state: dict, peer: dict, conversation_id: str, *, before=None, request_id=None):
    settings = state["settings"]
    conversation = await asyncio.to_thread(saved.get_conversation, settings, conversation_id)
    page = await asyncio.to_thread(saved.history, settings, conversation_id, before=before, limit=1)
    _queue(
        peer,
        {
            "type": "snapshot",
            "id": request_id,
            "conversation": conversation,
            "items": page["items"],
            "next_cursor": page["next_cursor"],
            "older": before is not None,
            "availability": _availability(state),
        },
    )


async def _library(state: dict, peer: dict, *, before=None):
    page = await asyncio.to_thread(saved.list_conversations, state["settings"], before=before)
    _queue(peer, {"type": "library", **page, "older": before is not None})


async def _publish(state: dict, conversation_id: str, attempt: dict | None = None):
    """Called under the coordination lock, strictly after repository commit."""
    conversation = await asyncio.to_thread(
        saved.get_conversation, state["settings"], conversation_id
    )
    for peer in tuple(state["peers"]):
        if peer["authenticated"] and peer["conversation_id"] == conversation_id:
            _queue(
                peer,
                {
                    "type": "update",
                    "conversation": conversation,
                    "attempt": attempt,
                    "availability": _availability(state),
                },
            )
    page = await asyncio.to_thread(saved.list_conversations, state["settings"])
    for peer in tuple(state["peers"]):
        if peer["authenticated"]:
            _queue(peer, {"type": "library", **page, "older": False})


async def _command(state: dict, peer: dict, command: dict) -> None:
    fields = {
        "subscribe": {"conversation_id"},
        "snapshot": {"conversation_id", "before"},
        "status": {"command_id"},
        "submit": {"conversation_id", "text"},
        "retry": {"conversation_id", "attempt_id"},
        "stop": {"conversation_id", "attempt_id"},
        "rename": {"conversation_id", "text"},
        "delete": {"conversation_id", "confirmed"},
    }
    kind = command.get("type")
    if (
        type(kind) is not str
        or kind not in fields
        or set(command) != {"v", "type", "id"} | fields[kind]
    ):
        raise ValueError("invalid_command")
    _command_id(command["id"])
    async with state["lock"]:
        try:
            settings = state["settings"]
            if not state["ready"]:
                raise ValueError("server_shutdown")
            if kind == "subscribe":
                cid = command["conversation_id"]
                if cid is None:
                    cid = await asyncio.to_thread(saved.new_draft, settings)
                    peer["conversation_id"] = cid
                    _queue(peer, {"type": "draft", "conversation_id": cid, "id": command["id"]})
                else:
                    _command_id(cid)
                    # Register before reading the snapshot under the same writer lock.
                    peer["conversation_id"] = cid
                    await _snapshot(state, peer, cid, request_id=command["id"])
                await _library(state, peer)
            elif kind == "snapshot":
                cid = command["conversation_id"]
                if cid is None:
                    before = command["before"]
                    if before is not None and (
                        type(before) is not list
                        or len(before) != 2
                        or any(type(v) is not str for v in before)
                    ):
                        raise ValueError("invalid_command")
                    await _library(state, peer, before=before)
                else:
                    _command_id(cid)
                    await _snapshot(
                        state, peer, cid, before=command["before"], request_id=command["id"]
                    )
            elif kind == "status":
                if command["command_id"] is not None:
                    _command_id(command["command_id"])
                outcome = (
                    await asyncio.to_thread(saved.command_status, settings, command["command_id"])
                    if command["command_id"]
                    else None
                )
                _queue(
                    peer,
                    {
                        "type": "command_status",
                        "id": command["id"],
                        "command_id": command["command_id"],
                        "outcome": outcome,
                        "availability": _availability(state),
                    },
                )
            else:
                prior = await asyncio.to_thread(saved.command_status, settings, command["id"])
                if (
                    prior is None
                    and kind in {"submit", "retry"}
                    and _availability(state) != "available"
                ):
                    raise ValueError(_availability(state))
                if (
                    kind == "stop"
                    and state["active"]
                    and state["active"]["attempt_id"] == command["attempt_id"]
                ):
                    await _flush(state, state["active"])
                mutation = {
                    key: value for key, value in command.items() if key not in {"v", "type"}
                }
                mutation["kind"] = kind
                outcome = await asyncio.to_thread(saved.accept_command, settings, mutation)
                _queue(peer, {"type": "ack", "id": command["id"], "outcome": outcome})
                if prior is None and outcome["status"] == "accepted":
                    active = {
                        "conversation_id": outcome["conversation_id"],
                        "attempt_id": outcome["attempt_id"],
                        "stop": asyncio.Event(),
                        "text": "",
                        "dirty": False,
                        "task": None,
                    }
                    state["active"] = active
                    active["task"] = asyncio.create_task(_run(state, active))
                    attempt = await asyncio.to_thread(
                        saved.get_attempt, settings, active["conversation_id"], active["attempt_id"]
                    )
                    await _publish(state, active["conversation_id"], attempt)
                elif kind in {"stop", "delete", "rename"} and outcome["status"] != "gone":
                    cid = outcome["conversation_id"]
                    active = state["active"]
                    if (
                        kind in {"stop", "delete"}
                        and active
                        and active["conversation_id"] == cid
                        and (kind == "delete" or active["attempt_id"] == command["attempt_id"])
                    ):
                        active["stop"].set()
                    attempt = (
                        await asyncio.to_thread(
                            saved.get_attempt, settings, cid, outcome["attempt_id"]
                        )
                        if outcome.get("attempt_id")
                        else None
                    )
                    await _publish(state, cid, attempt)
                    if kind == "delete" and (active is None or active["conversation_id"] != cid):
                        await _remove(state, cid)
        except ValueError as error:
            # Repository errors are safe codes; malformed requests never echo their content.
            code = str(error)
            if re.fullmatch(r"[a-z_]{1,64}", code) is None:
                code = "invalid_command"
            _queue(peer, {"type": "error", "id": command["id"], "code": code})
        except sqlite3.Error, OSError:
            _queue(peer, {"type": "error", "id": command["id"], "code": "storage_failure"})


async def _flush(state: dict, active: dict):
    if not active["dirty"]:
        return
    settings = state["settings"]
    cid, aid = active["conversation_id"], active["attempt_id"]
    conversation = await asyncio.to_thread(saved.get_conversation, settings, cid)
    attempt = await asyncio.to_thread(saved.get_attempt, settings, cid, aid)
    if conversation["deleting"] or attempt["status"] != "running":
        active["dirty"] = False
        return
    text = active["text"]
    active["dirty"] = False
    attempt = await asyncio.to_thread(
        saved.checkpoint, settings, cid, aid, expected_version=attempt["version"], text=text
    )
    await _publish(state, cid, attempt)


async def _run(state: dict, active: dict):
    settings = state["settings"]
    cid, aid = active["conversation_id"], active["attempt_id"]

    async def ticker():
        while True:
            await asyncio.sleep(CHECKPOINT_SECONDS)
            async with state["lock"]:
                await _flush(state, active)

    async def emit(event):
        if event["type"] == "text":
            active["text"] += event["text"]
            active["dirty"] = True
        elif event["type"] == "status" and event["status"] == "generating":
            active["text"] = ""
            active["dirty"] = True
        elif event["type"] == "tool":
            async with state["lock"]:
                await _flush(state, active)
                conversation = await asyncio.to_thread(saved.get_conversation, settings, cid)
                attempt = await asyncio.to_thread(saved.get_attempt, settings, cid, aid)
                if conversation["deleting"] or attempt["status"] != "running":
                    return
                attempt = await asyncio.to_thread(
                    saved.record_tool,
                    settings,
                    cid,
                    aid,
                    expected_version=attempt["version"],
                    event=event,
                )
                await _publish(state, cid, attempt)

    timer = asyncio.create_task(ticker())
    worker = None
    try:
        if not state["ready"]:
            await asyncio.to_thread(saved.interrupt_unfinished, settings)
            return
        context = await asyncio.to_thread(saved.context_for_attempt, settings, cid, aid)
        worker = asyncio.create_task(
            state["runner"](
                settings,
                context["question"],
                completed_exchanges=context["completed_exchanges"],
                identity=context["identity"],
                stop=active["stop"],
                emit=emit,
            )
        )
        worker.add_done_callback(_observe)
        done, _ = await asyncio.wait({worker, timer}, return_when=asyncio.FIRST_COMPLETED)
        if timer in done:
            timer.result()  # A failed durable checkpoint must stop work immediately.
        result = await worker
        async with state["lock"]:
            if not state["ready"]:
                await asyncio.to_thread(saved.interrupt_unfinished, settings)
            else:
                conversation = await asyncio.to_thread(saved.get_conversation, settings, cid)
                if result.get("code") == "cleanup_fault":
                    state["faulted"] = True
                if conversation["deleting"]:
                    await _remove(state, cid)
                else:
                    attempt = await asyncio.to_thread(saved.get_attempt, settings, cid, aid)
                    status = "complete" if result["status"] == "complete" else "failed"
                    text = result["text"]
                    if attempt["status"] == "stopping":
                        status = "stopping" if state["faulted"] else "stopped"
                        text = attempt["text"]
                    attempt = await asyncio.to_thread(
                        saved.checkpoint,
                        settings,
                        cid,
                        aid,
                        expected_version=attempt["version"],
                        text=text,
                        status=status,
                        code=result.get("code"),
                        evidence=result.get("evidence", []),
                    )
                    await _publish(state, cid, attempt)
    except Exception, asyncio.CancelledError:
        state["faulted"] = True
        active["stop"].set()
        for peer in tuple(state["peers"]):
            if peer["authenticated"]:
                _queue(peer, {"type": "error", "code": "persistence_or_runtime_failure"})
        if worker is not None and not worker.done():
            _, pending = await asyncio.wait({worker}, timeout=runtime.CLEANUP_SECONDS)
            for task in pending:
                task.cancel()
    finally:
        timer.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await timer
        async with state["lock"]:
            state["active"] = None
            for peer in tuple(state["peers"]):
                if peer["authenticated"]:
                    _queue(peer, {"type": "availability", "availability": _availability(state)})


async def _remove(state: dict, conversation_id: str):
    if state["faulted"] or runtime.availability() == "faulted":
        for peer in tuple(state["peers"]):
            if peer["authenticated"] and peer["conversation_id"] == conversation_id:
                _queue(peer, {"type": "error", "code": "cleanup_fault"})
        return
    conversation = await asyncio.to_thread(
        saved.get_conversation, state["settings"], conversation_id
    )
    gone = await asyncio.to_thread(
        saved.finalize_delete,
        state["settings"],
        conversation_id,
        expected_version=conversation["version"],
        cleanup_confirmed=True,
    )
    for peer in tuple(state["peers"]):
        if peer["authenticated"]:
            _queue(peer, {"type": "gone", **gone})
            await _library(state, peer)


def _command_done(state: dict, task: asyncio.Task) -> None:
    state["commands"].discard(task)
    _observe(task)


def _observe(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()  # Disconnection must not leave unobserved task errors.
