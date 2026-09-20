"""One application-owned response loop; no persistence or model administration."""

import asyncio
import json
import re
import threading
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx

from shopping.assistant.answers import render_month_items, render_recorded
from shopping.assistant.context import (
    TokenCounter,
    _validate_exchanges,
    bounded_messages,
    create_counter,
)
from shopping.assistant.continuation import monthly_continuation
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
_MODE = re.compile(
    r"^\[\[(conversation(?::(greeting|thanks|help))?|clarification|unsupported)\]\]\s*"
)
_PERSONAL_PURCHASE = re.compile(
    r"(?:\b(?:i|we|my|our)\s+(?:bought|purchased|paid|spent)\b|"
    r"\bwhat\s+did\s+(?:i|we)\s+buy\b|"
    r"\b(?:my|our)\s+(?:orders?|items?|purchases?)\b|"
    r"\b(?:what|which|show|list|find)\b[^?\n]{0,80}\b(?:orders?|items?|products?|purchases?)\b|"
    r"\bwhat\s+(?:are\s+)?(?:the\s+)?items?\s+(?:i|we)\s+bought\b|"
    r"\border\s*#?\d+\b)",
    re.I,
)
_CAPABILITY_REQUEST = re.compile(
    r"^\s*(?:what\s+can\s+you\s+do|how\s+can\s+you\s+help(?:\s+me)?|"
    r"what\s+are\s+your\s+capabilities)\s*\??\s*$",
    re.I,
)
_CONVERSATION_TEXT = {
    "greeting": "Hello! Ask me about your recorded orders or products.",
    "thanks": "You're welcome!",
    "help": (
        "I can help you find current recorded orders and purchase items, show monthly rows, "
        "explain unknown dates, and continue a partial page. I do not forecast future purchases "
        "or claim an inventory catalog."
    ),
    "conversation": "I can help you with your recorded orders or products.",
    "clarification": "Please clarify which product or purchase you mean.",
    "unsupported": "I can help with recorded shopping information, but not that request.",
}


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


def _rendered(state: dict, rendered: tuple[str, list[str], bool]) -> dict:
    answer, refs, answered = rendered
    evidence = {key: state["evidence"][key] for key in refs}
    if (
        len(json.dumps(answer, ensure_ascii=False).encode()) > MAX_OUTPUT_BYTES
        or len(json.dumps(list(evidence.values()), ensure_ascii=False).encode()) > 8192
    ):
        return _finish(state, "incomplete", "output_limit")
    state["text"], state["evidence"] = answer, evidence
    return _finish(
        state, "complete" if answered else "incomplete", None if answered else "answer_incomplete"
    )


def _complete(state: dict) -> dict:
    text = state["text"].strip()
    references = _REFERENCE.findall(text)
    mode = _MODE.match(text)
    remaining = _REFERENCE.sub("", _MODE.sub("", text))
    capability_request = _CAPABILITY_REQUEST.fullmatch(state["question"]) is not None
    if mode is not None and not remaining.strip():
        state["text"] = ""
        return _finish(state, "incomplete", "empty_response")
    if capability_request and not _PERSONAL_PURCHASE.search(state["question"]):
        state["text"] = _CONVERSATION_TEXT["help"]
        state["evidence"] = {}
        return _finish(state, "complete")
    if (
        "[[" in remaining
        or "]]" in remaining
        or any(reference not in state["evidence"] for reference in references)
    ):
        return _finish(state, "incomplete", "invalid_evidence")
    if state["results"]:
        rendered = render_recorded(state["question"], state["results"], state["evidence"])
        if rendered is not None:
            return _rendered(state, rendered)
    if mode is not None:
        mode_name = mode.group(1)
        if mode_name.startswith("conversation") and _PERSONAL_PURCHASE.search(state["question"]):
            return _finish(state, "incomplete", "missing_evidence")
        state["text"] = _CONVERSATION_TEXT[mode.group(2) or mode_name]
        state["evidence"] = {}
        return _finish(state, "complete")
    if _PERSONAL_PURCHASE.search(state["question"]) and not state["results"]:
        return _finish(state, "incomplete", "missing_evidence")
    if not text or not references:
        if any(result["status"] == "size_limit" for _, result in state["results"]):
            return _finish(state, "incomplete", "size_limit")
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
    instructions: str,
) -> dict:
    current: list[dict] = [{"role": "user", "content": question}]
    cache: dict[str, dict] = {}
    correction_used = False
    while state["model_requests"] < MAX_MODEL_REQUESTS:
        await publish({"type": "status", "status": "checking_context"})
        messages, input_tokens = await bounded_messages(
            history, current, count, instructions=instructions
        )
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
        batch_results: list[dict] = []
        for position, (call, arguments) in enumerate(zip(calls, validated, strict=True)):
            key = encode_result({"name": call["name"], "arguments": arguments})
            call_id = f"{state['model_requests']}:{position}"
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
            batch_results.append(result)
            if result["status"] == "error":
                return _finish(state, "incomplete", result["data"]["code"])
            state["evidence"].update({e["id"]: e for e in result["evidence"]})
            if key not in state["result_keys"]:
                state["results"].append((call["name"], result))
                state["result_keys"].add(key)
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
        if len(calls) == 1 and calls[0]["name"] == "list_purchase_items":
            monthly = batch_results[0]
            try:
                answer, refs = render_month_items(monthly)
            except ValueError:
                return _finish(state, "incomplete", "invalid_result")
            evidence = {key: state["evidence"][key] for key in refs}
            if (
                len(json.dumps(answer, ensure_ascii=False).encode("utf-8")) > MAX_OUTPUT_BYTES
                or len(json.dumps(list(evidence.values()), ensure_ascii=False).encode("utf-8"))
                > 8192
            ):
                return _finish(state, "incomplete", "output_limit")
            state["text"] = answer
            state["evidence"] = evidence
            return _finish(state, "complete")
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
    now: datetime | None = None,
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
        "results": [],
        "result_keys": set(),
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
    frozen_now = now if now is not None else datetime.now(UTC)
    if frozen_now.tzinfo is None or frozen_now.utcoffset() is None:
        return _finish(state, "rejected", "invalid_arguments")
    from shopping.assistant.context import instructions_for

    try:
        instructions = instructions_for(frozen_now)
    except TypeError, ValueError, OverflowError:
        return _finish(state, "rejected", "invalid_arguments")
    if _faulted or not _SLOT.acquire(blocking=False):
        return _finish(state, "rejected", availability())
    state["question"] = question
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
            history = completed_exchanges or []
            _validate_exchanges(history)
            continuation = monthly_continuation(question, history)
            if continuation is not None:
                return await _run_continuation(continuation)
            async with httpx.AsyncClient(
                timeout=WORK_SECONDS, trust_env=False, follow_redirects=False
            ) as client:
                counter = count_input or await create_counter(settings, client)
                return await _drive(
                    settings,
                    question,
                    completed_exchanges or [],
                    state,
                    publish,
                    stream,
                    counter,
                    instructions,
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

    async def _run_continuation(resolution: dict) -> dict:
        status = resolution["status"]
        if status == "missing":
            state["text"] = (
                "I need a recorded monthly page first. Ask me to list purchase items for a "
                "month, then ask for the next page."
            )
            return _finish(state, "complete")
        month = resolution["month"]
        if status == "exhausted":
            state["text"] = (
                f"The saved {month} purchase-items page has no further rows. "
                f"Refresh {month} to check again."
            )
            return _finish(state, "complete")
        arguments = {"month": month, "limit": resolution["limit"], "cursor": resolution["cursor"]}
        try:
            clean, _, _ = prepare_call(settings, "list_purchase_items", arguments)
        except ValueError, TypeError, KeyError:
            state["text"] = (
                f"The saved cursor for {month} is no longer valid. Restart the {month} listing."
            )
            return _finish(state, "incomplete", "invalid_cursor")
        state["tool_calls"] = 1
        call_id = "0:0"
        await publish(
            {
                "type": "tool",
                "call_id": call_id,
                "name": "list_purchase_items",
                "arguments": clean,
                "status": "running",
            }
        )
        read = asyncio.create_task(
            asyncio.to_thread(dispatch_tool, settings, "list_purchase_items", clean)
        )
        state["reads"].append(read)
        result = await asyncio.shield(read)
        if result["status"] == "error":
            code = result["data"].get("code")
            if code == "invalid_cursor":
                state["text"] = (
                    f"The saved cursor for {month} is no longer valid. Restart the {month} listing."
                )
                return _finish(state, "incomplete", "invalid_cursor")
            return _finish(state, "incomplete", code)
        state["evidence"].update({entry["id"]: entry for entry in result["evidence"]})
        state["results"].append(("list_purchase_items", result))
        await publish(
            {
                "type": "tool",
                "call_id": call_id,
                "name": "list_purchase_items",
                "status": result["status"],
                "result": result,
            }
        )
        try:
            answer, refs = render_month_items(result)
        except ValueError:
            return _finish(state, "incomplete", "invalid_result")
        return _rendered(state, (answer, refs, True))

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
