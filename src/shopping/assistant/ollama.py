"""Cancellable native Ollama transport. No retries, redirects, proxies or model management."""

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx2 as httpx

from shopping.assistant.tools import tool_schemas
from shopping.config import Settings

MAX_STREAM_BYTES = 256 * 1024
MAX_LINE_BYTES = 64 * 1024


def chat_request(settings: Settings, messages: list[dict]) -> dict[str, Any]:
    return {
        "model": settings.ollama_model,
        "messages": messages,
        "tools": tool_schemas(),
        "stream": True,
        "think": False,
        "keep_alive": "5m",
        "truncate": False,
        "options": {"num_ctx": 8192, "num_predict": 768, "temperature": 0},
    }


async def read_metadata(
    client: httpx.AsyncClient, settings: Settings, path: str, body: dict | None = None
) -> dict:
    """Read bounded metadata without emitting provider error bodies."""
    async with client.stream(
        "POST" if body is not None else "GET", settings.ollama_url + path, json=body
    ) as response:
        response.raise_for_status()
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > 32 * 1024 * 1024:
                raise ValueError("provider_metadata_limit")
        value = json.loads(chunks)
        if not isinstance(value, dict) or "error" in value or value.get("remote_host"):
            raise ValueError("provider_protocol")
        return value


def _add_calls(drafts: dict[int, dict], proposals: list) -> None:
    for proposal in proposals:
        if not isinstance(proposal, dict) or not isinstance(proposal.get("function"), dict):
            raise ValueError("provider_protocol")
        function = proposal["function"]
        if "name" in function and type(function["name"]) is not str:
            raise ValueError("provider_protocol")
        index = function.get("index", len(drafts))
        if type(index) is not int or not 0 <= index < 8:
            raise ValueError("tool_limit")
        draft = drafts.setdefault(index, {"id": f"call-{index}", "name": "", "arguments": None})
        if function.get("name"):
            if draft["name"] and draft["name"] != function["name"]:
                raise ValueError("provider_protocol")
            draft["name"] = function["name"]
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            if draft["arguments"] is not None and not isinstance(draft["arguments"], str):
                raise ValueError("provider_protocol")
            draft["arguments"] = (draft["arguments"] or "") + arguments
        elif isinstance(arguments, dict):
            if draft["arguments"] is not None:
                raise ValueError("provider_protocol")
            draft["arguments"] = arguments
        elif arguments is not None:
            raise ValueError("provider_protocol")


async def stream_chat(
    settings: Settings, messages: list[dict], *, client: httpx.AsyncClient | None = None
) -> AsyncGenerator[dict]:
    """Emit provisional text, one complete tool batch, then an explicit clean end.

    NDJSON may split at arbitrary bytes. Argument strings may split over indexed
    proposals; no tool is exposed until a clean provider end validates the batch.
    Cancellation unwinds the response context and closes the owned HTTP client.
    """
    if client is None:
        async with httpx.AsyncClient(timeout=180, trust_env=False, follow_redirects=False) as owned:
            async for event in stream_chat(settings, messages, client=owned):
                yield event
        return
    drafts: dict[int, dict] = {}
    pending = bytearray()
    received = 0
    try:
        async with client.stream(
            "POST", settings.ollama_url + "/api/chat", json=chat_request(settings, messages)
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > MAX_STREAM_BYTES:
                    yield {"type": "error", "code": "output_limit"}
                    return
                pending.extend(chunk)
                while b"\n" in pending:
                    raw, _, remaining = pending.partition(b"\n")
                    pending = bytearray(remaining)
                    if len(raw) > MAX_LINE_BYTES:
                        raise ValueError("provider_protocol")
                    if not raw.strip():
                        continue
                    value = json.loads(raw)
                    if not isinstance(value, dict) or "error" in value or value.get("remote_host"):
                        raise ValueError("provider_protocol")
                    message = value.get("message", {})
                    if not isinstance(message, dict) or message.get("thinking"):
                        raise ValueError("provider_protocol")
                    content = message.get("content", "")
                    if type(content) is not str:
                        raise ValueError("provider_protocol")
                    if content:
                        yield {"type": "text", "text": content}
                    proposals = message.get("tool_calls", [])
                    if not isinstance(proposals, list):
                        raise ValueError("provider_protocol")
                    _add_calls(drafts, proposals)
                    if value.get("done") is True:
                        if value.get("done_reason") != "stop" or value.get("eval_count", 0) >= 768:
                            yield {"type": "error", "code": "output_limit"}
                            return
                        for draft in drafts.values():
                            if isinstance(draft["arguments"], str):
                                draft["arguments"] = json.loads(draft["arguments"])
                            if not draft["name"] or not isinstance(draft["arguments"], dict):
                                raise ValueError("provider_protocol")
                        if drafts:
                            yield {"type": "tools", "calls": list(drafts.values())}
                        yield {
                            "type": "end",
                            "prompt_tokens": value.get("prompt_eval_count"),
                            "output_tokens": value.get("eval_count"),
                        }
                        return
                if len(pending) > MAX_LINE_BYTES:
                    raise ValueError("provider_protocol")
        yield {"type": "error", "code": "provider_eof"}
    except httpx.HTTPError:
        yield {"type": "error", "code": "provider_unavailable"}
    except ValueError, TypeError, KeyError, UnicodeError:
        yield {"type": "error", "code": "provider_protocol"}
