"""Bounded selected-record reads for graph details."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import ValidationError

from shopping.knowledge.models import GraphReadError, GraphViewRequest, RecordRef
from shopping.knowledge.records import read_record
from shopping.purchases.family_models import EvidenceRef, PurchaseScope
from shopping.purchases.timelines import TimelineError, read_timeline

MAX_SELECTED_MEMBERS = 500


def read_selection(
    connection: sqlite3.Connection,
    ref: RecordRef,
    *,
    scope: PurchaseScope,
    after_order: tuple[str, int] | None = None,
) -> dict[str, Any]:
    if type(ref) is not RecordRef or type(ref.row_id) is not int or not 0 < ref.row_id <= 2**63 - 1:
        raise GraphReadError("invalid_input")
    if after_order is not None and ref.entity_type not in {"product", "family"}:
        raise GraphReadError("invalid_cursor")
    try:
        GraphViewRequest(purchase_scope=scope)
    except ValidationError as exc:
        raise GraphReadError("invalid_input") from exc
    if ref.entity_type == "product":
        record = read_record(connection, ref)
        if record is None:
            raise GraphReadError("not_found")
        try:
            timeline = read_timeline(
                connection,
                product_ids=(ref.row_id,),
                scope=scope,
                membership_event_ids=(),
                after_order=after_order,
            )
        except TimelineError as exc:
            raise _timeline_error(exc) from None
        return {
            "record": record,
            "details": {"id": ref.row_id, **record.attributes},
            "timeline": timeline,
            "memberships": (),
        }
    if ref.entity_type == "family":
        record = read_record(connection, ref)
        if record is None:
            raise GraphReadError("not_found")
        rows = connection.execute(
            """SELECT m.id,m.product_id,m.family_id,e.version,e.id,e.proposal_event_id,
            p.origin,p.method,p.rationale,p.support_json
            FROM product_family_memberships m JOIN product_family_events e ON e.membership_id=m.id
            JOIN product_family_events p ON p.id=COALESCE(e.proposal_event_id,e.id)
            WHERE m.family_id=? AND e.kind='accepted' AND NOT EXISTS
            (SELECT 1 FROM product_family_events newer
             WHERE newer.membership_id=e.membership_id AND newer.version>e.version)
            ORDER BY m.product_id LIMIT ?""",
            (ref.row_id, MAX_SELECTED_MEMBERS + 1),
        ).fetchall()
        has_more = len(rows) > MAX_SELECTED_MEMBERS
        active = rows[:MAX_SELECTED_MEMBERS]
        memberships = tuple(_membership(row) for row in active)
        try:
            timeline = read_timeline(
                connection,
                product_ids=tuple(int(row[1]) for row in rows),
                scope=scope,
                membership_event_ids=tuple(int(row[4]) for row in rows),
                after_order=after_order,
            )
        except TimelineError as exc:
            raise _timeline_error(exc) from None
        return {
            "record": record,
            "details": {"id": ref.row_id, **record.attributes, "has_more_memberships": has_more},
            "timeline": timeline,
            "memberships": memberships,
        }
    if ref.entity_type not in {"order", "revision", "item", "listing", "retailer", "source"}:
        raise GraphReadError("invalid_input")
    record = read_record(connection, ref)
    if record is None:
        raise GraphReadError("not_found")
    return {
        "record": record,
        "details": {"id": ref.row_id, **record.attributes},
        "timeline": None,
        "memberships": (),
    }


def _membership(row: sqlite3.Row) -> dict[str, Any]:
    try:
        support = tuple(
            EvidenceRef(item["entity_type"], int(item["row_id"])) for item in json.loads(row[9])
        )
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise GraphReadError("invalid_input") from exc
    return {
        "id": int(row[0]),
        "product_id": int(row[1]),
        "family_id": int(row[2]),
        "version": int(row[3]),
        "state": "accepted",
        "event_id": int(row[4]),
        "proposal_event_id": int(row[5]),
        "origin": row[6],
        "method": row[7],
        "rationale": row[8],
        "support_refs": support,
    }


def _timeline_error(error: TimelineError) -> GraphReadError:
    return GraphReadError(
        error.code if error.code in {"invalid_input", "scope_too_large"} else "invalid_input"
    )
