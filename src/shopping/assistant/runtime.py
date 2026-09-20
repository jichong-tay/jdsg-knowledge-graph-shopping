"""One application-owned response loop; no persistence or model administration."""

import asyncio
import re
import threading
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

import httpx2 as httpx

from shopping.assistant.context import TokenCounter, bounded_messages, create_counter
from shopping.assistant.ollama import stream_chat
from shopping.assistant.tools import dispatch_tool, encode_result, prepare_call
from shopping.config import Settings

WORK_SECONDS = 180.0
CLEANUP_SECONDS = 5.0
MAX_MODEL_REQUESTS = 4
MAX_TOOL_CALLS = 8
MAX_OUTPUT_BYTES = 64 * 1024
_SLOT = threading.Lock()
_faulted = False

Stream = Callable[[Settings, list[dict]], AsyncGenerator[dict]]
Emitter = Callable[[dict], Awaitable[None]]
_REFERENCE = re.compile(r"\[\[((?:order|product):[1-9][0-9]*)\]\]")
_MODE = re.compile(r"^\[\[(clarification|unsupported)\]\]\s*")


def availability() -> str:
    """Local state only: this never contacts or loads Ollama."""
    return "faulted" if _faulted else "busy" if _SLOT.locked() else "available"


def _finish(state: dict, status: str, code: str | None = None) -> dict:
    return {
        "status": status,
        "code": code,
        "text": state["text"],
        "evidence": list(state["evidence"].values()),
        "model_requests": state["model_requests"],
        "tool_calls": state["tool_calls"],
    }


def _complete(state: dict) -> dict:
    text = state["text"].strip()
    references = _REFERENCE.findall(text)
    mode = _MODE.match(text)
    remaining = _REFERENCE.sub("", _MODE.sub("", text))
    if (
        "[[" in remaining
        or "]]" in remaining
        or any(reference not in state["evidence"] for reference in references)
    ):
        return _finish(state, "incomplete", "invalid_evidence")
    if not text or (not references and mode is None):
        return _finish(state, "incomplete", "missing_evidence")
    state["text"] = _MODE.sub("", text)
    # Only return cited, application-owned links. Marker validity is not semantic proof.
    state["evidence"] = {key: state["evidence"][key] for key in dict.fromkeys(references)}
    return _finish(state, "complete")


async def _drive(
    settings: Settings,
    question: str,
    history: list[list[dict]],
    state: dict,
    publish: Emitter,
    stream: Stream,
    count: TokenCounter,
) -> dict:
    current: list[dict] = [{"role": "user", "content": question}]
    cache: dict[str, dict] = {}
    correction_used = False
    while state["model_requests"] < MAX_MODEL_REQUESTS:
        await publish({"type": "status", "status": "checking_context"})
        messages, input_tokens = await bounded_messages(history, current, count)
        state["model_requests"] += 1
        await publish({"type": "status", "status": "generating"})
        calls = []
        ended = False
        state["text"] = ""
        async with aclosing(stream(settings, messages)) as events:
            async for event in events:
                kind = event["type"]
                if kind == "text":
                    state["text"] += event["text"]
                    if len(state["text"].encode("utf-8")) > MAX_OUTPUT_BYTES:
                        return _finish(state, "incomplete", "output_limit")
                    await publish(event)
                elif kind == "tools":
                    calls.extend(event["calls"])
                elif kind == "error":
                    return _finish(state, "incomplete", event["code"])
                elif kind == "end":
                    if event.get("prompt_tokens") != input_tokens:
                        return _finish(state, "incomplete", "accounting_mismatch")
                    ended = True
                else:
                    return _finish(state, "incomplete", "provider_protocol")
        if not ended:
            return _finish(state, "incomplete", "provider_eof")
        if not calls:
            return _complete(state)
        state["tool_calls"] += len(calls)
        if state["tool_calls"] > MAX_TOOL_CALLS:
            return _finish(state, "incomplete", "tool_limit")
        validated = []
        try:
            for call in calls:
                validated.append(prepare_call(settings, call["name"], call["arguments"])[0])
        except ValueError, TypeError, KeyError:
            if correction_used:
                return _finish(state, "incomplete", "invalid_tools")
            correction_used = True
            # Retain a complete proposal/result group, but execute none of this batch.
            current.append(
                {
                    "role": "assistant",
                    "content": state["text"],
                    "tool_calls": [
                        {"function": {"name": call["name"], "arguments": call["arguments"]}}
                        for call in calls
                    ],
                }
            )
            current.extend(
                {
                    "role": "tool",
                    "tool_name": call["name"],
                    "content": '{"status":"error","code":"invalid_batch",'
                    '"instruction":"Correct the entire batch using the tool schemas."}',
                }
                for call in calls
            )
            continue
        current.append(
            {
                "role": "assistant",
                "content": state["text"],
                "tool_calls": [
                    {"function": {"name": call["name"], "arguments": arguments}}
                    for call, arguments in zip(calls, validated, strict=True)
                ],
            }
        )
        for call, arguments in zip(calls, validated, strict=True):
            key = encode_result({"name": call["name"], "arguments": arguments})
            call_id = f"{state['model_requests']}:{call['id']}"
            await publish(
                {
                    "type": "tool",
                    "call_id": call_id,
                    "name": call["name"],
                    "arguments": arguments,
                    "status": "running",
                }
            )
            if key not in cache:
                # Shield so cancellation cannot pretend a running SQLite read has stopped.
                read = asyncio.create_task(
                    asyncio.to_thread(dispatch_tool, settings, call["name"], arguments)
                )
                state["reads"].append(read)
                cache[key] = await asyncio.shield(read)
            result = cache[key]
            if result["status"] == "error":
                return _finish(state, "incomplete", result["data"]["code"])
            state["evidence"].update({e["id"]: e for e in result["evidence"]})
            current.append(
                {"role": "tool", "tool_name": call["name"], "content": encode_result(result)}
            )
            await publish(
                {
                    "type": "tool",
                    "call_id": call_id,
                    "name": call["name"],
                    "status": result["status"],
                    "result": result,
                }
            )
    return _finish(state, "incomplete", "model_limit")


async def run_attempt(
    settings: Settings,
    question: str,
    *,
    completed_exchanges: list[list[dict]] | None = None,
    identity: tuple[str, str] | None = None,
    stop: asyncio.Event | None = None,
    emit: Emitter | None = None,
    stream: Stream = stream_chat,
    count_input: TokenCounter | None = None,
) -> dict[str, Any]:
    """Collect one bounded attempt. Callers pass completed exchanges from one conversation.

    Explicit identity preserves a saved conversation's endpoint/model binding. A
    stopped caller cannot publish late data; unsettled cleanup faults availability
    until process restart. This function does not persist or expose a Chat route.
    """
    global _faulted
    state: dict[str, Any] = {
        "text": "",
        "evidence": {},
        "model_requests": 0,
        "tool_calls": 0,
        "reads": [],
    }
    if type(question) is not str or not question.strip() or len(question) > 4000:
        return _finish(state, "rejected", "invalid_question")
    try:
        question.encode("utf-8")
    except UnicodeError:
        return _finish(state, "rejected", "invalid_question")
    if identity is not None and identity != (settings.ollama_url, settings.ollama_model):
        return _finish(state, "rejected", "configuration_changed")
    if stop is not None and stop.is_set():
        return _finish(state, "rejected", "cancelled")
    if _faulted or not _SLOT.acquire(blocking=False):
        return _finish(state, "rejected", availability())
    stopped = stop if stop is not None else asyncio.Event()
    terminal = False
    deadline = asyncio.get_running_loop().time() + WORK_SECONDS

    def check_active() -> None:
        if terminal or stopped.is_set():
            raise asyncio.CancelledError
        if asyncio.get_running_loop().time() >= deadline:
            raise ValueError("deadline")

    async def publish(event: dict) -> None:
        check_active()
        if emit is not None:
            await emit(event)
        check_active()

    async def work() -> dict:
        try:
            check_active()
            async with httpx.AsyncClient(
                timeout=WORK_SECONDS, trust_env=False, follow_redirects=False
            ) as client:
                counter = count_input or await create_counter(settings, client)
                return await _drive(
                    settings, question, completed_exchanges or [], state, publish, stream, counter
                )
        except httpx.HTTPError, OSError:
            return _finish(state, "incomplete", "provider_unavailable")
        except (ValueError, TypeError, KeyError) as error:
            code = str(error)
            if code not in {
                "context_limit",
                "invalid_history",
                "accounting_unsupported",
                "tokenizer_unsupported",
                "deadline",
            }:
                code = "context_unavailable"
            return _finish(state, "incomplete", code)

    worker = asyncio.create_task(work())
    stop_waiter = asyncio.create_task(stopped.wait())
    result = None
    try:
        finished, _ = await asyncio.wait(
            {worker, stop_waiter}, timeout=WORK_SECONDS, return_when=asyncio.FIRST_COMPLETED
        )
        if stopped.is_set():
            result = _finish(state, "incomplete", "cancelled")
        elif worker in finished:
            result = worker.result()
        else:
            result = _finish(state, "incomplete", "deadline")
    except asyncio.CancelledError:
        result = _finish(state, "incomplete", "cancelled")
    finally:
        terminal = True
        stop_waiter.cancel()
        if not worker.done():
            worker.cancel()
        outstanding = {task for task in [worker, stop_waiter, *state["reads"]] if not task.done()}
        if outstanding:
            try:
                _, pending = await asyncio.wait(outstanding, timeout=CLEANUP_SECONDS)
                if pending:
                    _faulted = True
            except asyncio.CancelledError:
                # Cleanup was interrupted; do not silently leave a permanent busy slot.
                _faulted = True
        if not _faulted:
            _SLOT.release()
    if _faulted:
        result = _finish(state, "incomplete", "cleanup_fault")
    if result is None:
        result = _finish(state, "incomplete", "runtime_failure")
    if emit is not None:
        await emit({"type": "terminal", **result})
    return result
