"""Strict four-tool boundary, whole-row envelopes and application-owned evidence.

Cursors are signed, query-bound live-page offsets. They expire on process restart;
callers restart pagination after invalid_cursor. No shopping state is stored here.
"""

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Mapping
from typing import Any

from app.assistant.queries import read_page
from app.config import Settings
from app.db.migrations import assert_schema_current

MAX_RESULT_BYTES = 4096
_MAX_ID = 2**63 - 1
_CURSOR_KEY = secrets.token_bytes(32)
_LIMITS = {
    "search_products": (10, 20),
    "get_product_history": (20, 50),
    "list_recent_orders": (10, 25),
    "get_order": (50, 50),
}


def tool_schemas() -> list[dict[str, Any]]:
    """Ollama-compatible function schemas; validation uses these same properties."""
    schemas = []
    for name, (default, maximum) in _LIMITS.items():
        properties: dict[str, Any] = {
            "cursor": {"type": "string", "minLength": 1, "maxLength": 512},
        }
        required = []
        if name != "get_order":
            properties["limit"] = {
                "type": "integer",
                "minimum": 1,
                "maximum": maximum,
                "default": default,
            }
        if name == "search_products":
            properties["query"] = {"type": "string", "minLength": 1, "maxLength": 200}
            required = ["query"]
        elif name in {"get_product_history", "get_order"}:
            field = "product_id" if name == "get_product_history" else "order_id"
            properties[field] = {"type": "integer", "minimum": 1, "maximum": _MAX_ID}
            required = [field]
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "Read current purchase facts. Purchase date is delivery_at; "
                    "missing dates stay unknown. Follow next_cursor for more rows. "
                    "Multiple search matches are candidates, not a selected identity.",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            }
        )
    return schemas


def validate_arguments(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Validate without database access, also usable for later whole-batch validation."""
    schema = next(
        (s["function"]["parameters"] for s in tool_schemas() if s["function"]["name"] == name), None
    )
    if schema is None:
        raise ValueError("unknown_tool")
    if not isinstance(arguments, Mapping) or set(arguments) - set(schema["properties"]):
        raise ValueError("invalid_arguments")
    if not set(schema["required"]) <= set(arguments):
        raise ValueError("invalid_arguments")
    clean = dict(arguments)
    for field, rule in schema["properties"].items():
        if field not in clean:
            if "default" in rule:
                clean[field] = rule["default"]
            continue
        value = clean[field]
        if rule["type"] == "integer":
            if type(value) is not int or not rule["minimum"] <= value <= rule["maximum"]:
                raise ValueError("invalid_arguments")
        else:
            if type(value) is not str:
                raise ValueError("invalid_arguments")
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("invalid_arguments") from None
            if field == "query":
                value = value.strip()
                clean[field] = value
            if not rule["minLength"] <= len(value) <= rule["maxLength"]:
                raise ValueError("invalid_arguments")
    return clean


def encode_result(result: dict[str, Any]) -> str:
    """Canonical wire encoding used when enforcing the UTF-8 envelope budget."""
    return json.dumps(
        result, ensure_ascii=False, separators=(",", ":"), allow_nan=False, sort_keys=True
    )


def _cursor(scope: str, offset: int) -> str:
    payload = f"{scope}:{offset}".encode()
    signature = hmac.digest(_CURSOR_KEY, payload, "sha256")
    return base64.urlsafe_b64encode(payload + signature).decode()


def _offset(cursor: str, scope: str) -> int:
    try:
        raw = base64.b64decode(cursor, altchars=b"-_", validate=True)
        payload, signature = raw[:-32], raw[-32:]
        if not hmac.compare_digest(signature, hmac.digest(_CURSOR_KEY, payload, "sha256")):
            raise ValueError
        bound_scope, value = payload.decode().split(":")
        offset = int(value)
        if bound_scope != scope or not 0 < offset <= _MAX_ID - 51:
            raise ValueError
        return offset
    except ValueError, UnicodeError:
        raise ValueError("invalid_cursor") from None


def _evidence(parent: dict, rows: list[dict]) -> list[dict]:
    entries = {}
    for record in [parent, *rows]:
        for entity in ("order", "product"):
            entity_id = record.get(f"{entity}_id")
            if entity_id is None:
                continue
            reference = f"{entity}:{entity_id}"
            entries[reference] = {
                "id": reference,
                "entity_type": entity,
                "entity_id": entity_id,
                "label": f"{entity.title()} {entity_id}",
                "url": f"/{entity}s/{entity_id}",
            }
    return list(entries.values())


def _envelope(
    status: str, data: dict, evidence: list | None = None, next_cursor: str | None = None
) -> dict[str, Any]:
    return {
        "status": status,
        "data": data,
        "evidence": evidence or [],
        "next_cursor": next_cursor,
        "truncated": next_cursor is not None,
    }


def dispatch_tool(settings: Settings, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded facts or stable errors, without exposing storage internals."""
    try:
        clean = validate_arguments(name, arguments)
        scope_values = {key: value for key, value in clean.items() if key != "cursor"}
        scope = hashlib.sha256(
            encode_result(
                {
                    "database": str(settings.database_path.resolve()),
                    "tool": name,
                    "arguments": scope_values,
                }
            ).encode()
        ).hexdigest()
        offset = _offset(clean["cursor"], scope) if "cursor" in clean else 0
    except ValueError as error:
        return _envelope("error", {"code": str(error)})
    try:
        assert_schema_current(settings.database_path, settings.migrations_dir)
        limit = clean.get("limit", 50)
        parent, rows = read_page(settings.database_path, name, clean, offset=offset, limit=limit)
    except sqlite3.Error, OSError, RuntimeError:
        return _envelope("error", {"code": "storage_unavailable"})
    if parent is None:
        return _envelope("not_found", {})
    # Rebuild evidence and pagination for each candidate page; never slice fact strings.
    for count in range(min(len(rows), limit), -1, -1):
        if rows and count == 0:
            break
        selected = rows[:count]
        next_cursor = _cursor(scope, offset + count) if count < len(rows) else None
        result = _envelope(
            "ok", {**parent, "items": selected}, _evidence(parent, selected), next_cursor
        )
        try:
            size = len(encode_result(result).encode("utf-8"))
        except UnicodeError:
            break
        if size <= MAX_RESULT_BYTES:
            return result
    return _envelope("error", {"code": "size_limit"})
