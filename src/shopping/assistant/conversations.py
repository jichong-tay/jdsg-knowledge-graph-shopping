"""Durable conversation commands and checkpoints, independent of model/browser work.

Each call opens and closes its own connection. Callers commit here before starting
work or broadcasting; returned versions identify saved state, not token events.
ValueError messages are safe rejection codes. Storage failures propagate so callers
cannot mistake a failed commit for a saved acknowledgement.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from shopping.config import Settings
from shopping.storage.connection import connect_database, transaction
from shopping.storage.schema import assert_schema_current


@contextmanager
def _database(settings: Settings) -> Iterator[sqlite3.Connection]:
    assert_schema_current(settings.database_path, settings.migrations_dir)
    connection = connect_database(settings.database_path)
    try:
        yield connection
    finally:
        connection.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _text(value: object, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError("invalid_text")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("invalid_text") from None
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) is None:
        raise ValueError("invalid_id")
    return value


def _number(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("invalid_id")
    return value


def _conversation(connection: sqlite3.Connection, conversation_id: str) -> dict:
    row = connection.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise ValueError("gone")
    return dict(row)


def _attempt(connection: sqlite3.Connection, conversation_id: str, attempt_id: int) -> dict:
    _identifier(conversation_id)
    _number(attempt_id)
    row = connection.execute(
        """SELECT a.*, m.conversation_id, m.content AS question
        FROM response_attempts a JOIN conversation_messages m ON m.id = a.message_id
        WHERE a.id = ? AND m.conversation_id = ?""",
        (attempt_id, conversation_id),
    ).fetchone()
    if row is None:
        raise ValueError("attempt_gone")
    result = dict(row)
    result["evidence"] = json.loads(result.pop("evidence_json"))
    result["tools"] = [
        {
            "call_id": tool["call_id"],
            "name": tool["name"],
            "arguments": json.loads(tool["arguments_json"]),
            "result": json.loads(tool["result_json"]) if tool["result_json"] is not None else None,
        }
        for tool in connection.execute(
            """SELECT * FROM conversation_tools
            WHERE attempt_id = ? ORDER BY position""",
            (attempt_id,),
        )
    ]
    return result


def new_draft(settings: Settings) -> str:
    """Issue an explicit creation key, without creating a Conversation or content."""
    identifier = uuid4().hex
    with _database(settings) as connection:
        connection.execute("INSERT INTO conversation_keys(id) VALUES (?)", (identifier,))
    return identifier


def get_conversation(settings: Settings, conversation_id: str) -> dict:
    with _database(settings) as connection:
        return _conversation(connection, conversation_id)


def get_attempt(settings: Settings, conversation_id: str, attempt_id: int) -> dict:
    with _database(settings) as connection, transaction(connection, immediate=False):
        return _attempt(connection, conversation_id, attempt_id)


def command_status(settings: Settings, command_id: str) -> dict | None:
    """Look up an uncertain acknowledgement without replaying any mutation."""
    with _database(settings) as connection:
        row = connection.execute(
            "SELECT outcome_json FROM conversation_commands WHERE id = ?",
            (_identifier(command_id),),
        ).fetchone()
        return json.loads(row[0]) if row else None


def _limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("invalid_limit")


def list_conversations(
    settings: Settings, *, limit: int = 20, before: tuple[str, str] | None = None
) -> dict:
    """Newest message activity first; rename does not reorder the list."""
    _limit(limit)
    with _database(settings) as connection:
        rows = connection.execute(
            """SELECT * FROM conversations
            WHERE (? IS NULL OR (activity_at, id) < (?, ?))
            ORDER BY activity_at DESC, id DESC LIMIT ?""",
            (
                before[0] if before else None,
                before[0] if before else None,
                before[1] if before else None,
                limit + 1,
            ),
        ).fetchall()
        items = [dict(row) for row in rows[:limit]]
        return {
            "items": items,
            "next_cursor": (items[-1]["activity_at"], items[-1]["id"])
            if len(rows) > limit
            else None,
        }


def history(
    settings: Settings, conversation_id: str, *, before: int | None = None, limit: int = 20
) -> dict:
    """Newest attempts first, with shared message IDs identifying explicit Retries.

    Pages are capped at 256 KiB in addition to row count. The browser transport must
    further page/chunk individual records to fit its smaller wire envelope.
    """
    _limit(limit)
    if before is not None:
        _number(before)
    with _database(settings) as connection, transaction(connection, immediate=False):
        _conversation(connection, conversation_id)
        rows = connection.execute(
            """SELECT a.id FROM response_attempts a
            JOIN conversation_messages m ON m.id = a.message_id
            WHERE m.conversation_id = ? AND (? IS NULL OR a.id < ?)
            ORDER BY a.id DESC LIMIT ?""",
            (conversation_id, before, before, limit + 1),
        ).fetchall()
        items = []
        size = 0
        for row in rows[:limit]:
            item = _attempt(connection, conversation_id, row["id"])
            item_size = len(_json(item).encode("utf-8"))
            if items and size + item_size > 256 * 1024:
                break
            items.append(item)
            size += item_size
        return {"items": items, "next_cursor": items[-1]["id"] if len(rows) > len(items) else None}


def _bump(connection: sqlite3.Connection, conversation_id: str, *, activity: bool = False) -> int:
    if activity:
        connection.execute(
            "UPDATE conversations SET version = version + 1, activity_at = ? WHERE id = ?",
            (_now(), conversation_id),
        )
    else:
        connection.execute(
            "UPDATE conversations SET version = version + 1 WHERE id = ?", (conversation_id,)
        )
    return _conversation(connection, conversation_id)["version"]


def _accept_submit(connection: sqlite3.Connection, settings: Settings, command: dict) -> dict:
    conversation_id = command["conversation_id"]
    if connection.execute(
        "SELECT 1 FROM response_attempts WHERE status IN ('running', 'stopping')"
    ).fetchone():
        raise ValueError("busy")
    key = connection.execute(
        "SELECT consumed FROM conversation_keys WHERE id = ?", (conversation_id,)
    ).fetchone()
    if key is None:
        raise ValueError("gone")
    now = _now()
    if not key["consumed"]:
        connection.execute(
            """INSERT INTO conversations(id, title, endpoint, model, created_at, activity_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                conversation_id,
                " ".join(command["text"].split())[:80],
                settings.ollama_url,
                settings.ollama_model,
                now,
                now,
            ),
        )
        connection.execute(
            "UPDATE conversation_keys SET consumed = 1 WHERE id = ?", (conversation_id,)
        )
        version = 1
    else:
        conversation = _conversation(connection, conversation_id)
        if conversation["deleting"]:
            raise ValueError("deleting")
        if (conversation["endpoint"], conversation["model"]) != (
            settings.ollama_url,
            settings.ollama_model,
        ):
            raise ValueError("configuration_changed")
        version = _bump(connection, conversation_id, activity=True)
    message_id = connection.execute(
        """INSERT INTO conversation_messages(conversation_id, content, created_at)
        VALUES (?, ?, ?) RETURNING id""",
        (conversation_id, command["text"], now),
    ).fetchone()[0]
    attempt_id = connection.execute(
        """INSERT INTO response_attempts(message_id, created_at, updated_at)
        VALUES (?, ?, ?) RETURNING id""",
        (message_id, now, now),
    ).fetchone()[0]
    return {
        "status": "accepted",
        "conversation_id": conversation_id,
        "message_id": message_id,
        "attempt_id": attempt_id,
        "version": version,
        "attempt_version": 1,
    }


def accept_command(settings: Settings, command: dict) -> dict:
    """Accept an explicit command atomically; identical accepted IDs return the same outcome.

    Rejected commands are not recorded and may be deliberately tried again. The
    caller must also check runtime availability and serialize acceptance/start.
    """
    if type(command) is not dict:
        raise ValueError("invalid_command")
    fields = {
        "submit": {"text"},
        "stop": {"attempt_id"},
        "retry": {"attempt_id"},
        "rename": {"text"},
        "delete": {"confirmed"},
    }
    kind = command.get("kind")
    if (
        type(kind) is not str
        or kind not in fields
        or set(command) != {"id", "kind", "conversation_id"} | fields[kind]
    ):
        raise ValueError("invalid_command")
    _identifier(command["id"])
    _identifier(command["conversation_id"])
    if kind in {"submit", "rename"}:
        _text(command["text"], 4000 if kind == "submit" else 80)
    if kind == "delete" and command["confirmed"] is not True:
        raise ValueError("confirmation_required")
    if kind in {"stop", "retry"}:
        _number(command["attempt_id"])
    fingerprint = hashlib.sha256(_json(command).encode("utf-8")).hexdigest()
    with _database(settings) as connection, transaction(connection):
        prior = connection.execute(
            "SELECT * FROM conversation_commands WHERE id = ?", (command["id"],)
        ).fetchone()
        if prior:
            if prior["fingerprint"] is not None and prior["fingerprint"] != fingerprint:
                raise ValueError("command_conflict")
            return json.loads(prior["outcome_json"])
        if kind == "submit":
            result = _accept_submit(connection, settings, command)
        elif kind == "retry":
            result = _accept_retry(connection, settings, command)
        elif kind == "stop":
            result = _accept_stop(connection, command)
        elif kind == "rename":
            result = _accept_rename(connection, command)
        else:
            result = _accept_delete(connection, command)
        connection.execute(
            """INSERT INTO conversation_commands(id, conversation_id, fingerprint, outcome_json)
            VALUES (?, ?, ?, ?)""",
            (command["id"], command["conversation_id"], fingerprint, _json(result)),
        )
        return result


def _writable(
    connection: sqlite3.Connection, conversation_id: str, attempt_id: int, expected_version: int
) -> dict:
    if _conversation(connection, conversation_id)["deleting"]:
        raise ValueError("deleting")
    attempt = _attempt(connection, conversation_id, attempt_id)
    if attempt["version"] != _number(expected_version):
        raise ValueError("stale_version")
    if attempt["status"] not in {"running", "stopping"}:
        raise ValueError("already_finished")
    return attempt


def checkpoint(
    settings: Settings,
    conversation_id: str,
    attempt_id: int,
    *,
    expected_version: int,
    text: str,
    status: str = "running",
    code: str | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    """Replace bounded saved text using compare-and-swap; terminal writes flush it.

    Stopping is a durable cancellation fence. Its final stopped outcome is written
    only after the caller proves local cleanup; a cleanup fault can remain stopping.
    """
    if type(text) is not str or len(_json(text).encode("utf-8")) > 65536:
        raise ValueError("output_limit")
    if status not in {"running", "stopping", "complete", "failed", "stopped"}:
        raise ValueError("invalid_status")
    if code is not None and (type(code) is not str or re.fullmatch(r"[a-z_]{1,64}", code) is None):
        raise ValueError("invalid_code")
    with _database(settings) as connection, transaction(connection):
        attempt = _writable(connection, conversation_id, attempt_id, expected_version)
        if attempt["status"] == "stopping" and status not in {"stopping", "stopped"}:
            raise ValueError("stopping")
        if status == "complete" and (
            not text.strip() or any(t["result"] is None for t in attempt["tools"])
        ):
            raise ValueError("incomplete_response")
        selected = attempt["evidence"] if evidence is None else evidence
        if type(selected) is not list or len(_json(selected).encode("utf-8")) > 8192:
            raise ValueError("invalid_evidence")
        available = [
            e
            for tool in attempt["tools"]
            if tool["result"] is not None
            for e in tool["result"]["evidence"]
        ]
        if any(e not in available for e in selected):
            raise ValueError("invalid_evidence")
        connection.execute(
            """UPDATE response_attempts SET text = ?, status = ?, code = ?, evidence_json = ?,
            version = version + 1, updated_at = ? WHERE id = ?""",
            (text, status, code, _json(selected), _now(), attempt_id),
        )
        _bump(connection, conversation_id, activity=True)
        return _attempt(connection, conversation_id, attempt_id)


def _accept_stop(connection: sqlite3.Connection, command: dict) -> dict:
    cid, aid = command["conversation_id"], command["attempt_id"]
    conversation = _conversation(connection, cid)
    if conversation["deleting"]:
        raise ValueError("deleting")
    attempt = _attempt(connection, cid, aid)
    if attempt["status"] == "running":
        connection.execute(
            """UPDATE response_attempts SET status = 'stopping', version = version + 1,
                updated_at = ? WHERE id = ?""",
            (_now(), aid),
        )
        version = _bump(connection, cid)
        attempt["version"] += 1
        status = "stopping"
    else:
        version = conversation["version"]
        status = "stopping" if attempt["status"] == "stopping" else "already_finished"
    return {
        "status": status,
        "conversation_id": cid,
        "attempt_id": aid,
        "version": version,
        "attempt_version": attempt["version"],
    }


def _accept_retry(connection: sqlite3.Connection, settings: Settings, command: dict) -> dict:
    cid = command["conversation_id"]
    conversation = _conversation(connection, cid)
    if conversation["deleting"]:
        raise ValueError("deleting")
    if (conversation["endpoint"], conversation["model"]) != (
        settings.ollama_url,
        settings.ollama_model,
    ):
        raise ValueError("configuration_changed")
    previous = _attempt(connection, cid, command["attempt_id"])
    latest = connection.execute(
        """SELECT a.id FROM response_attempts a
        JOIN conversation_messages m ON m.id = a.message_id
        WHERE m.conversation_id = ? ORDER BY m.id DESC, a.id DESC LIMIT 1""",
        (cid,),
    ).fetchone()[0]
    if latest != previous["id"] or previous["status"] not in {"failed", "stopped", "interrupted"}:
        raise ValueError("not_retryable")
    if connection.execute(
        "SELECT 1 FROM response_attempts WHERE status IN ('running', 'stopping')"
    ).fetchone():
        raise ValueError("busy")
    now = _now()
    aid = connection.execute(
        """INSERT INTO response_attempts(message_id, created_at, updated_at)
        VALUES (?, ?, ?) RETURNING id""",
        (previous["message_id"], now, now),
    ).fetchone()[0]
    return {
        "status": "accepted",
        "conversation_id": cid,
        "attempt_id": aid,
        "message_id": previous["message_id"],
        "version": _bump(connection, cid, activity=True),
        "attempt_version": 1,
    }


def record_tool(
    settings: Settings, conversation_id: str, attempt_id: int, *, expected_version: int, event: dict
) -> dict:
    """Save one runtime tool start/outcome, bounded by the existing four-tool boundary."""
    from shopping.assistant.tools import encode_result, validate_arguments

    if type(event) is not dict or event.get("type") != "tool":
        raise ValueError("invalid_tool")
    call_id = event.get("call_id")
    if type(call_id) is not str or re.fullmatch(r"[0-9]{1,2}:[0-9]{1,3}", call_id) is None:
        raise ValueError("invalid_tool")
    starting = event.get("status") == "running"
    required = {"type", "call_id", "name", "status", "arguments" if starting else "result"}
    if set(event) != required:
        raise ValueError("invalid_tool")
    arguments: dict = {}
    result_json = None
    if starting:
        arguments = validate_arguments(event["name"], event["arguments"])
        if len(encode_result(arguments).encode("utf-8")) > 4096:
            raise ValueError("tool_limit")
    else:
        result = event["result"]
        if (
            type(result) is not dict
            or set(result) != {"status", "data", "evidence", "next_cursor", "truncated"}
            or result["status"] not in {"ok", "not_found", "size_limit", "error"}
            or event["status"] != result["status"]
            or type(result["data"]) is not dict
            or type(result["evidence"]) is not list
        ):
            raise ValueError("invalid_tool")
        result_json = encode_result(result)
        if len(result_json.encode("utf-8")) > 4096:
            raise ValueError("tool_limit")
    with _database(settings) as connection, transaction(connection):
        attempt = _writable(connection, conversation_id, attempt_id, expected_version)
        if attempt["status"] != "running":
            raise ValueError("stopping")
        existing = next((tool for tool in attempt["tools"] if tool["call_id"] == call_id), None)
        if starting:
            if existing is not None:
                raise ValueError("tool_conflict")
            if len(attempt["tools"]) >= 8:
                raise ValueError("tool_limit")
            connection.execute(
                """INSERT INTO conversation_tools
                (attempt_id, call_id, position, name, arguments_json)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    attempt_id,
                    call_id,
                    len(attempt["tools"]) + 1,
                    event["name"],
                    encode_result(arguments),
                ),
            )
        else:
            if (
                existing is None
                or existing["name"] != event["name"]
                or existing["result"] is not None
            ):
                raise ValueError("tool_conflict")
            connection.execute(
                """UPDATE conversation_tools SET result_json = ?
                WHERE attempt_id = ? AND call_id = ?""",
                (result_json, attempt_id, call_id),
            )
        connection.execute(
            "UPDATE response_attempts SET version = version + 1, updated_at = ? WHERE id = ?",
            (_now(), attempt_id),
        )
        _bump(connection, conversation_id)
        return _attempt(connection, conversation_id, attempt_id)


def context_for_attempt(
    settings: Settings,
    conversation_id: str,
    attempt_id: int,
    *,
    limit: int = 16,
    max_bytes: int = 256 * 1024,
) -> dict:
    """Select a bounded recent suffix of complete exchanges, oldest first.

    The runtime still applies exact model token accounting and can remove more
    whole exchanges. Failed text and incomplete tools are never model input.
    Historical tools are complete synthetic call/result groups, not executable work.
    """
    _limit(limit)
    if type(max_bytes) is not int or not 1 <= max_bytes <= 256 * 1024:
        raise ValueError("invalid_limit")
    with _database(settings) as connection, transaction(connection, immediate=False):
        conversation = _conversation(connection, conversation_id)
        current = _attempt(connection, conversation_id, attempt_id)
        rows = connection.execute(
            """SELECT a.id FROM response_attempts a
            JOIN conversation_messages m ON m.id = a.message_id
            WHERE m.conversation_id = ? AND m.id < ? AND a.status = 'complete'
            ORDER BY m.id DESC LIMIT ?""",
            (conversation_id, current["message_id"], limit),
        ).fetchall()
        exchanges = []
        size = 0
        for row in rows:
            attempt = _attempt(connection, conversation_id, row["id"])
            if any(tool["result"] is None for tool in attempt["tools"]):
                continue
            exchange = [{"role": "user", "content": attempt["question"]}]
            for tool in attempt["tools"]:
                exchange.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": tool["name"], "arguments": tool["arguments"]}}
                        ],
                    }
                )
                exchange.append(
                    {"role": "tool", "tool_name": tool["name"], "content": _json(tool["result"])}
                )
            exchange.append({"role": "assistant", "content": attempt["text"]})
            size += len(_json(exchange).encode("utf-8"))
            if size > max_bytes:
                break
            exchanges.append(exchange)
        return {
            "question": current["question"],
            "identity": (conversation["endpoint"], conversation["model"]),
            "completed_exchanges": list(reversed(exchanges)),
        }


def _accept_rename(connection: sqlite3.Connection, command: dict) -> dict:
    cid = command["conversation_id"]
    if _conversation(connection, cid)["deleting"]:
        raise ValueError("deleting")
    connection.execute("UPDATE conversations SET title = ? WHERE id = ?", (command["text"], cid))
    return {"status": "renamed", "conversation_id": cid, "version": _bump(connection, cid)}


def _accept_delete(connection: sqlite3.Connection, command: dict) -> dict:
    cid = command["conversation_id"]
    conversation = _conversation(connection, cid)
    if not conversation["deleting"]:
        connection.execute("UPDATE conversations SET deleting = 1 WHERE id = ?", (cid,))
        connection.execute(
            """UPDATE response_attempts SET status = 'stopping',
            version = version + 1, updated_at = ? WHERE status = 'running'
            AND message_id IN (SELECT id FROM conversation_messages WHERE conversation_id = ?)""",
            (_now(), cid),
        )
        conversation["version"] = _bump(connection, cid)
    active = connection.execute(
        """SELECT a.id FROM response_attempts a
        JOIN conversation_messages m ON m.id = a.message_id
        WHERE m.conversation_id = ? AND a.status IN ('running', 'stopping')""",
        (cid,),
    ).fetchone()
    return {
        "status": "deleting",
        "conversation_id": cid,
        "version": conversation["version"],
        "attempt_id": active["id"] if active else None,
    }


def finalize_delete(
    settings: Settings, conversation_id: str, *, expected_version: int, cleanup_confirmed: bool
) -> dict:
    """Remove owned records only after local work is known unable to write.

    Failure rolls back removal and leaves the deletion fence for deliberate recovery.
    Minimal IDs survive, with command fingerprints erased; backups are unaffected.
    """
    if cleanup_confirmed is not True:
        raise ValueError("cleanup_required")
    with _database(settings) as connection, transaction(connection):
        conversation = _conversation(connection, conversation_id)
        if not conversation["deleting"]:
            raise ValueError("delete_not_requested")
        if conversation["version"] != _number(expected_version):
            raise ValueError("stale_version")
        result = {
            "status": "gone",
            "conversation_id": conversation_id,
            "version": conversation["version"] + 1,
        }
        connection.execute(
            """UPDATE conversation_commands SET fingerprint = NULL, outcome_json = ?
            WHERE conversation_id = ?""",
            (_json(result), conversation_id),
        )
        connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return result


def interrupt_unfinished(settings: Settings) -> list[dict]:
    """Startup-only recovery, before admitting work; never reruns a question.

    Invoke once after the previous process has exited, not on browser reconnect.
    Deleting Conversations remain fenced for explicit finalization after recovery.
    """
    with _database(settings) as connection, transaction(connection):
        rows = connection.execute("""SELECT a.id, m.conversation_id FROM response_attempts a
            JOIN conversation_messages m ON m.id = a.message_id
            WHERE a.status IN ('running', 'stopping')""").fetchall()
        result = []
        for row in rows:
            connection.execute(
                """UPDATE response_attempts SET status = 'interrupted', code = 'server_restart',
                version = version + 1, updated_at = ? WHERE id = ?""",
                (_now(), row["id"]),
            )
            _bump(connection, row["conversation_id"])
            result.append(_attempt(connection, row["conversation_id"], row["id"]))
        return result
