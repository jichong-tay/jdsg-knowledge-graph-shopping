"""Small, bounded authoritative record reads for graph views."""
# ruff: noqa: E501

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from shopping.knowledge.models import GraphReadError, GraphRecord, RecordRef
from shopping.purchases.family_models import PurchaseScope
from shopping.purchases.normalization import normalize_text

MAX_ROOTS = 80
_MAX_ID = 2**63 - 1
_TABLES = {"order", "revision", "item", "listing", "product", "family", "retailer", "source"}


def _ref(ref: RecordRef) -> None:
    if (
        type(ref) is not RecordRef
        or type(ref.entity_type) is not str
        or ref.entity_type not in _TABLES
        or type(ref.row_id) is not int
        or not 0 < ref.row_id <= _MAX_ID
    ):
        raise GraphReadError("invalid_input")


def _record(ref: RecordRef, row: sqlite3.Row) -> GraphRecord:
    values = dict(row)
    kind = ref.entity_type
    label = str(values.pop("_label"))
    url = f"/{kind}s/{ref.row_id}" if kind in {"product", "order"} else None
    values.pop("id", None)
    if "unassigned" in values:
        values["unassigned"] = bool(values["unassigned"])
    return GraphRecord(ref, label, values, url)


def read_record(connection: sqlite3.Connection, ref: RecordRef) -> GraphRecord | None:
    _ref(ref)
    q: dict[str, tuple[str, tuple[Any, ...]]] = {
        "product": (
            "SELECT p.id,p.canonical_name AS _label,p.canonical_name,p.variant,p.package_quantity,p.package_unit,p.is_active,CASE WHEN EXISTS (SELECT 1 FROM retailer_products rp WHERE rp.product_id=p.id AND rp.match_status<>'confirmed') OR NOT EXISTS (SELECT 1 FROM retailer_products rp WHERE rp.product_id=p.id) THEN 'provisional' ELSE 'confirmed' END AS identity_status,NOT EXISTS (SELECT 1 FROM product_family_memberships m JOIN product_family_events e ON e.membership_id=m.id AND e.kind='accepted' WHERE m.product_id=p.id AND NOT EXISTS (SELECT 1 FROM product_family_events n WHERE n.membership_id=e.membership_id AND n.version>e.version)) AS unassigned FROM products p WHERE p.id=?",
            (ref.row_id,),
        ),
        "family": (
            "SELECT id,name AS _label,definition,created_at FROM product_families WHERE id=?",
            (ref.row_id,),
        ),
        "retailer": (
            "SELECT id,name AS _label,name,slug,country FROM retailers WHERE id=?",
            (ref.row_id,),
        ),
        "source": (
            "SELECT id,'Source #'||id AS _label,source_kind,parse_status,parser_version,received_at,source_sent_at,fetched_at,parsed_at FROM email_messages WHERE id=?",
            (ref.row_id,),
        ),
        "order": (
            "SELECT o.id,o.external_order_id AS _label,o.external_order_id,o.retailer_id,o.created_at,current_rev.status,current_rev.delivery_at FROM orders o LEFT JOIN order_revisions current_rev ON current_rev.order_id=o.id AND current_rev.is_current=1 WHERE o.id=?",
            (ref.row_id,),
        ),
        "revision": (
            "SELECT id,'Revision #'||id AS _label,order_id,revision_number,revision_kind,status,is_current,delivery_at,ordered_at,source_event_at,parser_version,currency,total_cents,subtotal_cents,discount_cents,delivery_fee_cents,service_fee_cents,other_fee_cents,tax_cents,included_tax_cents,created_at FROM order_revisions WHERE id=?",
            (ref.row_id,),
        ),
        "item": (
            "SELECT oi.id,'Item #'||oi.id AS _label,oi.order_revision_id,oi.retailer_product_id,oi.raw_name,oi.quantity,oi.unit,oi.unit_price_cents,oi.gross_cents,oi.discount_cents,oi.net_cents FROM order_items oi WHERE oi.id=?",
            (ref.row_id,),
        ),
        "listing": (
            "SELECT rp.id,rp.latest_name AS _label,rp.product_id,rp.retailer_id,rp.match_method AS match_origin,rp.match_status,rp.latest_name,rp.latest_size_text FROM retailer_products rp WHERE rp.id=?",
            (ref.row_id,),
        ),
    }
    sql, args = q[ref.entity_type]
    row = connection.execute(sql, args).fetchone()
    return None if row is None else _record(ref, row)


def product_purchase_counts(
    connection: sqlite3.Connection, product_ids: tuple[int, ...], scope: PurchaseScope
) -> dict[int, int]:
    """Count qualifying logical Orders for visible Products in one bounded query."""
    ids = tuple(dict.fromkeys(product_ids))
    if not ids:
        return {}
    if len(ids) > 201:
        raise GraphReadError("scope_too_large")
    placeholders = ",".join("?" for _ in ids)
    sg = ZoneInfo("Asia/Singapore")
    end = (
        datetime.combine(scope.analysis_date + timedelta(days=1), time.min, sg)
        .astimezone(UTC)
        .isoformat()
    )
    args: list[Any] = [*ids, end]
    sql = f"""SELECT p.id, COUNT(DISTINCT o.id)
        FROM products p
        LEFT JOIN retailer_products rp ON rp.product_id=p.id
        LEFT JOIN order_items oi ON oi.retailer_product_id=rp.id
        LEFT JOIN order_revisions rev ON rev.id=oi.order_revision_id AND rev.is_current=1
        LEFT JOIN orders o ON o.id=rev.order_id
        WHERE p.id IN ({placeholders})
          AND rev.status IN ('placed','completed')
          AND rev.delivery_at IS NOT NULL AND rev.delivery_at < ?"""
    if scope.start_date:
        start = datetime.combine(scope.start_date, time.min, sg).astimezone(UTC).isoformat()
        sql += " AND rev.delivery_at >= ?"
        args.append(start)
    if scope.end_date:
        finish = (
            datetime.combine(scope.end_date + timedelta(days=1), time.min, sg)
            .astimezone(UTC)
            .isoformat()
        )
        sql += " AND rev.delivery_at < ?"
        args.append(finish)
    rows = connection.execute(sql + " GROUP BY p.id", args).fetchall()
    result = {int(row[0]): int(row[1]) for row in rows}
    return {product_id: result.get(product_id, 0) for product_id in ids}


def read_roots(
    connection: sqlite3.Connection,
    *,
    query: str,
    after: tuple[str, int] | None = None,
    limit: int = 41,
) -> tuple[GraphRecord, ...]:
    if (
        type(query) is not str
        or "\x00" in query
        or len(query) > 200
        or type(limit) is not int
        or not 1 <= limit <= MAX_ROOTS + 1
    ):
        raise GraphReadError("invalid_input")
    if after is not None and (
        type(after) is not tuple
        or len(after) != 2
        or type(after[0]) is not str
        or type(after[1]) is not int
        or not 0 < after[1] <= 2**63 - 1
    ):
        raise GraphReadError("invalid_cursor")
    needle = normalize_text(query)
    like = f"%{needle.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
    params: list[Any] = [needle, like, needle, like]
    cursor = ""
    if after is not None:
        if after[0] not in {"product", "family"}:
            raise GraphReadError("invalid_cursor")
        cursor = " WHERE (kind>? OR (kind=? AND id>?))"
        params.extend((after[0], after[0], after[1]))
    rows = connection.execute(
        "SELECT id,kind,label FROM (SELECT id,'product' AS kind,canonical_name AS label FROM products WHERE ?='' OR normalized_name LIKE ? ESCAPE '\\' UNION ALL SELECT id,'family',name FROM product_families WHERE ?='' OR normalized_name LIKE ? ESCAPE '\\') "
        + cursor
        + " ORDER BY kind,id LIMIT ?",
        (*params, limit),
    ).fetchall()
    return tuple(
        record
        for r in rows
        if (record := read_record(connection, RecordRef(str(r[1]), int(r[0])))) is not None
    )
