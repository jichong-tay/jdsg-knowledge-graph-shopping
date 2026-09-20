"""Reviewer-proposed bounded relationship reader for Luna to apply and verify."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, time, timedelta
from typing import Literal, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from shopping.knowledge.models import (
    NODE_TYPE_SET,
    PREDICATES,
    GraphReadError,
    GraphRelation,
    GraphViewRequest,
    RecordRef,
)
from shopping.purchases.family_models import PurchaseScope

RelationKey = tuple[str, str, int, str, int, int]
MAX_RELATION_ROWS = 61
_MAX_ID = 2**63 - 1
_SG = ZoneInfo("Asia/Singapore")
_COLUMNS = (
    "predicate, source_type, source_id, target_type, target_id, event_id, membership_id, state"
)
_KEY_COLUMNS = "predicate, source_type, source_id, target_type, target_id, event_id"


def _utc_end(scope: PurchaseScope) -> str:
    return (
        datetime.combine(scope.analysis_date + timedelta(days=1), time.min, _SG)
        .astimezone(UTC)
        .isoformat()
    )


def relation_key(relation: GraphRelation) -> RelationKey:
    event_id = next(
        (ref.row_id for ref in relation.support if ref.entity_type == "membership_event"), 0
    )
    return (
        relation.type,
        relation.source.entity_type,
        relation.source.row_id,
        relation.target.entity_type,
        relation.target.row_id,
        event_id,
    )


def _validate(
    ref: RecordRef, mode: str, scope: PurchaseScope, after: RelationKey | None, limit: int
) -> None:
    if (
        type(ref) is not RecordRef
        or type(ref.entity_type) is not str
        or ref.entity_type not in NODE_TYPE_SET
        or type(ref.row_id) is not int
        or not 0 < ref.row_id <= _MAX_ID
        or type(mode) is not str
        or mode not in {"current", "history"}
        or type(limit) is not int
        or not 1 <= limit <= MAX_RELATION_ROWS
    ):
        raise GraphReadError("invalid_input")
    try:
        GraphViewRequest(purchase_scope=scope)
    except ValidationError:
        raise GraphReadError("invalid_input") from None
    if after is None:
        return
    if (
        type(after) is not tuple
        or len(after) != 6
        or any(type(after[i]) is not str for i in (0, 1, 3))
        or any(type(after[i]) is not int for i in (2, 4, 5))
        or after[0] not in PREDICATES
        or after[3] not in PREDICATES[after[0]].get(after[1], set())
        or not 0 < after[2] <= _MAX_ID
        or not 0 < after[4] <= _MAX_ID
        or not 0 <= after[5] <= _MAX_ID
        or (after[0] == "MEMBER_OF") != (after[5] > 0)
        or (ref.entity_type, ref.row_id) not in ((after[1], after[2]), (after[3], after[4]))
    ):
        raise GraphReadError("invalid_cursor")


def _branches(ref: RecordRef, mode: str, scope: PurchaseScope) -> tuple[list[str], list[str | int]]:
    """Build only incident, parameterized branches from fixed application templates."""
    queries: list[str] = []
    parameters: list[str | int] = []
    start = (
        datetime.combine(scope.start_date, time.min, _SG).astimezone(UTC).isoformat()
        if scope.start_date
        else None
    )
    end = (
        datetime.combine(scope.end_date + timedelta(days=1), time.min, _SG)
        .astimezone(UTC)
        .isoformat()
        if scope.end_date
        else None
    )

    def add(
        predicate: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        from_sql: str,
        *,
        revision: str | None = None,
        filter_current: bool = True,
        always_current: bool = False,
        condition: str | None = None,
        event_id: str = "0",
        membership_id: str = "0",
        state: str = "'active'",
    ) -> None:
        if ref.entity_type == source_type:
            root_column = source_id
        elif ref.entity_type == target_type:
            root_column = target_id
        else:
            return
        clauses = [f"{root_column} = ?"]
        args: list[str | int] = [ref.row_id]
        if condition:
            clauses.append(condition)
        if revision:
            if always_current or (filter_current and mode == "current"):
                clauses.append(f"{revision}.is_current = 1")
            dates: list[str] = []
            if start:
                dates.append(f"{revision}.delivery_at >= ?")
                args.append(start)
            if end:
                dates.append(f"{revision}.delivery_at < ?")
                args.append(end)
            if dates:
                clauses.append(f"({revision}.delivery_at IS NULL OR ({' AND '.join(dates)}))")
        queries.append(
            f"SELECT '{predicate}' AS predicate, '{source_type}' AS source_type, "
            f"{source_id} AS source_id, '{target_type}' AS target_type, "
            f"{target_id} AS target_id, {event_id} AS event_id, "
            f"{membership_id} AS membership_id, {state} AS state "
            f"FROM {from_sql} WHERE {' AND '.join(clauses)}"
        )
        parameters.extend(args)

    for predicate in ("HAS_REVISION", "CURRENT_REVISION"):
        add(
            predicate,
            "order",
            "rev.order_id",
            "revision",
            "rev.id",
            "order_revisions rev",
            revision="rev",
            always_current=predicate == "CURRENT_REVISION",
        )
    add(
        "ORDERED_FROM",
        "order",
        "o.id",
        "retailer",
        "o.retailer_id",
        "orders o LEFT JOIN order_revisions current_rev "
        "ON current_rev.order_id=o.id AND current_rev.is_current=1",
        revision="current_rev",
        filter_current=False,
    )
    items_from = "order_items oi JOIN order_revisions rev ON rev.id=oi.order_revision_id"
    add("HAS_ITEM", "revision", "rev.id", "item", "oi.id", items_from, revision="rev")
    add(
        "REFERS_TO_LISTING",
        "item",
        "oi.id",
        "listing",
        "oi.retailer_product_id",
        items_from,
        revision="rev",
    )
    add(
        "LISTED_BY",
        "listing",
        "rp.id",
        "retailer",
        "rp.retailer_id",
        "retailer_products rp",
    )
    add(
        "MAPS_TO_PRODUCT",
        "listing",
        "rp.id",
        "product",
        "rp.product_id",
        "retailer_products rp",
    )
    latest = (
        "NOT EXISTS (SELECT 1 FROM product_family_events newer "
        "WHERE newer.membership_id=m.id AND newer.version>e.version)"
    )
    add(
        "MEMBER_OF",
        "product",
        "m.product_id",
        "family",
        "m.family_id",
        "product_family_memberships m JOIN product_family_events e ON e.membership_id=m.id",
        condition="e.kind='accepted'" + (f" AND {latest}" if mode == "current" else ""),
        event_id="e.id",
        membership_id="m.id",
        state=f"CASE WHEN {latest} THEN 'active' ELSE 'inactive' END",
    )
    add(
        "SUPPORTED_BY",
        "revision",
        "rev.id",
        "source",
        "rev.email_message_id",
        "order_revisions rev",
        revision="rev",
    )
    add(
        "SUPPORTED_BY",
        "revision",
        "rev.id",
        "source",
        "s.email_message_id",
        "order_revision_sources s JOIN order_revisions rev ON rev.id=s.order_revision_id",
        revision="rev",
    )
    # Product purchase occasions are a bounded, scope-aware convenience relation.
    # Grouping here prevents repeated item lines from multiplying an Order edge.
    if ref.entity_type in {"product", "order"}:
        root_column = "p.id" if ref.entity_type == "product" else "o.id"
        date_clause = " AND rev.delivery_at >= ?" if scope.start_date else ""
        purchase_sql = (
            "SELECT 'PURCHASED_IN' AS predicate, 'product' AS source_type, p.id AS source_id, "
            "'order' AS target_type, o.id AS target_id, 0 AS event_id, 0 AS membership_id, "
            "'active' AS state FROM order_items oi "
            "JOIN retailer_products rp ON rp.id=oi.retailer_product_id "
            "JOIN products p ON p.id=rp.product_id "
            "JOIN order_revisions rev ON rev.id=oi.order_revision_id AND rev.is_current=1 "
            "JOIN orders o ON o.id=rev.order_id "
            f"WHERE {root_column}=? AND rev.status IN ('placed','completed') "
            f"AND rev.delivery_at IS NOT NULL AND rev.delivery_at < ?{date_clause} "
            "GROUP BY p.id,o.id"
        )
        queries.append(purchase_sql)
        parameters.extend([ref.row_id, _utc_end(scope)])
        if scope.start_date:
            parameters.append(
                datetime.combine(scope.start_date, time.min, _SG).astimezone(UTC).isoformat()
            )
    return queries, parameters


def read_relations(
    connection: sqlite3.Connection,
    ref: RecordRef,
    *,
    mode: str,
    scope: PurchaseScope,
    after: RelationKey | None = None,
    limit: int = MAX_RELATION_ROWS,
) -> tuple[GraphRelation, ...]:
    """Read one keyset page. The caller owns the transaction and SQLite work budget."""
    _validate(ref, mode, scope, after, limit)
    branches, args = _branches(ref, mode, scope)
    if not branches:
        return ()
    # UNION also deduplicates a Source referenced both as primary and association.
    sql = f"SELECT {_COLUMNS} FROM ({' UNION '.join(branches)})"
    if after is not None:
        sql += f" WHERE ({_KEY_COLUMNS}) > (?, ?, ?, ?, ?, ?)"
        args.extend(after)
    sql += f" ORDER BY {_KEY_COLUMNS} LIMIT ?"
    args.append(limit)
    rows = connection.execute(sql, args).fetchall()
    purchased_support: dict[tuple[int, int], tuple[RecordRef, ...]] = {}
    pairs = [(int(row[2]), int(row[4])) for row in rows if row[0] == "PURCHASED_IN"]
    if pairs:
        pair_sql = " UNION ALL ".join("SELECT ? AS product_id, ? AS order_id" for _ in pairs)
        values = [value for pair in pairs for value in pair]
        support_rows = connection.execute(
            "SELECT q.product_id,q.order_id,MIN(rev.id),MIN(oi.id) FROM (" + pair_sql + ") q "
            "JOIN retailer_products rp ON rp.product_id=q.product_id "
            "JOIN order_items oi ON oi.retailer_product_id=rp.id "
            "JOIN order_revisions rev ON rev.id=oi.order_revision_id "
            "AND rev.is_current=1 AND rev.order_id=q.order_id "
            "GROUP BY q.product_id,q.order_id",
            values,
        ).fetchall()
        purchased_support = {
            (int(row[0]), int(row[1])): (
                RecordRef("revision", int(row[2])),
                RecordRef("item", int(row[3])),
            )
            for row in support_rows
        }
    result: list[GraphRelation] = []
    for predicate, stype, sid, ttype, tid, event_id, membership_id, state in rows:
        source, target = RecordRef(stype, sid), RecordRef(ttype, tid)
        support = (source, target)
        if predicate == "PURCHASED_IN":
            support += purchased_support.get((int(sid), int(tid)), ())
        if predicate == "MEMBER_OF":
            support += (
                RecordRef("membership", membership_id),
                RecordRef("membership_event", event_id),
            )
        result.append(
            GraphRelation(
                predicate, source, target, cast(Literal["active", "inactive"], state), support
            )
        )
    return tuple(result)
