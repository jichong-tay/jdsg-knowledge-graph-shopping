"""Pure resolution of explicit requests to continue a saved monthly page."""

import json
import re
from typing import Any

from shopping.assistant.dates import month_bounds

_NEXT = re.compile(r"^\s*(?:please\s+)?(?:show\s+)?(?:the\s+)?next\s+page\s*[.!?]?\s*$", re.I)


def monthly_continuation(
    question: str, completed_exchanges: list[list[dict]]
) -> dict[str, Any] | None:
    """Resolve the newest valid monthly tool result and its preceding call."""
    if type(question) is not str or not _NEXT.fullmatch(question):
        return None
    if not isinstance(completed_exchanges, list):
        return {"status": "missing"}
    latest = None
    latest_tool_name = None
    for exchange in completed_exchanges:
        if not isinstance(exchange, list):
            continue
        pending = []
        for message in exchange:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant" and isinstance(message.get("tool_calls"), list):
                pending.extend(
                    item.get("function")
                    for item in message["tool_calls"]
                    if isinstance(item, dict) and isinstance(item.get("function"), dict)
                )
            elif message.get("role") == "tool":
                tool_name = message.get("tool_name")
                latest = None
                latest_tool_name = tool_name
                call = next((item for item in pending if item.get("name") == tool_name), None)
                if call is None:
                    continue
                pending.remove(call)
                if tool_name == "list_purchase_items":
                    latest = (call, message)
    if latest is None:
        if latest_tool_name is not None and latest_tool_name != "list_purchase_items":
            return None
        return {"status": "missing"}
    call, tool = latest
    if not isinstance(tool.get("content"), str):
        return {"status": "missing"}
    try:
        result = json.loads(tool["content"])
    except TypeError, ValueError:
        return {"status": "missing"}
    if (
        not isinstance(result, dict)
        or result.get("status") != "ok"
        or not isinstance(result.get("data"), dict)
    ):
        return {"status": "missing"}
    data = result["data"]
    month, limit = data.get("month"), data.get("limit")
    args = call.get("arguments")
    if not isinstance(args, dict) or args.get("month") != month or args.get("limit") != limit:
        return {"status": "missing"}
    if type(limit) is not int or not 1 <= limit <= 20 or data.get("timezone") != "Asia/Singapore":
        return {"status": "missing"}
    try:
        month_bounds(month)
    except TypeError, ValueError:
        return {"status": "missing"}
    cursor = result.get("next_cursor")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        return {"status": "missing"}
    base = {"month": month, "limit": limit, "cursor": cursor}
    return {"status": "ready", **base} if cursor else {"status": "exhausted", **base}
