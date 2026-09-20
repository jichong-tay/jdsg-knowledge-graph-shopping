"""Bounded, read-only membership review history."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, cast

from shopping.config import Settings
from shopping.knowledge.cursors import decode_cursor, encode_cursor
from shopping.knowledge.models import GraphReadError, SnapshotRef
from shopping.knowledge.projection import canonical_json
from shopping.purchases.family_models import EvidenceRef
from shopping.storage.connection import connect_database, transaction
from shopping.storage.schema import assert_schema_current

MAX_LIMIT = 50
MAX_BYTES = 1 << 20
MAX_OPS = 2_000_000
PROGRESS_INTERVAL = 5000
MAX_SECONDS = 2


def read_reviews(
    settings: Settings,
    *,
    mode: str = "pending",
    family_id: int | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    if type(mode) is not str or mode not in {"pending", "current", "history"}:
        raise GraphReadError("invalid_input")
    if family_id is not None and (type(family_id) is not int or not 0 < family_id <= 2**63 - 1):
        raise GraphReadError("invalid_input")
    if (
        type(limit) is not int
        or not 1 <= limit <= MAX_LIMIT
        or type(cursor) not in {str, type(None)}
        or (cursor is not None and len(cursor) > 2048)
    ):
        raise GraphReadError("invalid_input")
    assert_schema_current(settings.database_path, settings.migrations_dir)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"mode": mode, "family_id": family_id, "limit": limit},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    connection = connect_database(settings.database_path)
    try:
        connection.execute("PRAGMA query_only=ON")
        with transaction(connection, immediate=False):
            dataset, generation = connection.execute(
                "SELECT dataset_id,generation FROM graph_dataset_state WHERE id=1"
            ).fetchone()
            snapshot = SnapshotRef(str(dataset), int(generation))
            root = f"{dataset}:family:{family_id}" if family_id is not None else None
            after = None
            if cursor is not None:
                after = decode_cursor(
                    cursor, snapshot, fingerprint=fingerprint, kind="reviews", root=root
                )[0]
            if (
                family_id is not None
                and connection.execute(
                    "SELECT 1 FROM product_families WHERE id=?", (family_id,)
                ).fetchone()
                is None
            ):
                raise GraphReadError("not_found")
            instructions = [0]
            started = time.monotonic()

            def progress() -> int:
                instructions[0] += PROGRESS_INTERVAL
                if instructions[0] >= MAX_OPS or time.monotonic() - started > MAX_SECONDS:
                    return 1
                return 0

            connection.set_progress_handler(progress, PROGRESS_INTERVAL)
            try:
                params: list[object] = []
                where = []
                if family_id is not None:
                    where.append("m.family_id=?")
                    params.append(family_id)
                if mode == "pending":
                    where.append("e.kind='proposed'")
                    where.append(
                        "NOT EXISTS (SELECT 1 FROM product_family_events newer WHERE newer.membership_id=e.membership_id AND newer.version>e.version)"
                    )
                elif mode == "current":
                    where.append(
                        "NOT EXISTS (SELECT 1 FROM product_family_events newer WHERE newer.membership_id=e.membership_id AND newer.version>e.version)"
                    )
                if after is not None:
                    where.append("e.id>?")
                    params.append(after)
                sql = (
                    """SELECT m.id,m.product_id,m.family_id,e.version,e.kind,e.id,e.proposal_event_id,
                    p.origin,p.method,p.rationale,p.support_json,e.review_reason,e.created_at,
                    pr.canonical_name,f.name,
                    NOT EXISTS (SELECT 1 FROM product_family_events newer WHERE newer.membership_id=e.membership_id AND newer.version>e.version)
                    FROM product_family_memberships m JOIN product_family_events e ON e.membership_id=m.id
                    JOIN product_family_events p ON p.id=COALESCE(e.proposal_event_id,e.id)
                    JOIN products pr ON pr.id=m.product_id JOIN product_families f ON f.id=m.family_id
                    WHERE """
                    + " AND ".join(where or ["1=1"])
                    + " ORDER BY e.id LIMIT ?"
                )
                params.append(limit + 1)
                try:
                    rows = connection.execute(sql, params).fetchall()
                except sqlite3.OperationalError as exc:
                    if exc.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT:
                        raise GraphReadError("scope_too_large") from None
                    raise
            finally:
                connection.set_progress_handler(None, 0)
            if MAX_OPS <= PROGRESS_INTERVAL:
                raise GraphReadError("scope_too_large")
            has_more = len(rows) > limit
            rows = rows[:limit]
            entries = [_entry(row) for row in rows]
            payload = {
                "snapshot": snapshot,
                "entries": entries,
                "page": {"has_more": has_more},
                "mode": mode,
                "family_id": family_id,
            }
            if has_more and rows:
                payload["page"]["cursor"] = encode_cursor(
                    snapshot,
                    fingerprint=fingerprint,
                    kind="reviews",
                    root=root,
                    last=(int(rows[-1][5]),),
                )
            else:
                payload["page"]["cursor"] = None
            if len(canonical_json(payload)) > MAX_BYTES:
                raise GraphReadError("scope_too_large")
            return payload
    finally:
        connection.close()


def _entry(row: tuple[Any, ...]) -> dict[str, Any]:
    try:
        refs = tuple(
            EvidenceRef(cast(Any, str(item["entity_type"])), int(item["row_id"]))
            for item in json.loads(row[10] or "[]")
        )
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise GraphReadError("invalid_input") from exc
    state = "pending" if row[4] == "proposed" else str(row[4])
    actions = (
        ("accepted", "rejected")
        if row[15] and state == "pending"
        else (("withdrawn",) if row[15] and state == "accepted" else ())
    )
    return {
        "id": int(row[0]),
        "product_id": int(row[1]),
        "family_id": int(row[2]),
        "version": int(row[3]),
        "state": state,
        "event_id": int(row[5]),
        "proposal_event_id": int(row[6] or row[5]),
        "origin": row[7],
        "method": row[8],
        "rationale": row[9],
        "support_refs": refs,
        "review_reason": row[11],
        "created_at": row[12],
        "product_name": row[13],
        "family_name": row[14],
        "is_current": bool(row[15]),
        "actions": actions,
    }
