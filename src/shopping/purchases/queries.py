"""Bounded current-fact reads. Missing Purchase Dates sort last, then IDs descend.

Pages read live state, not snapshots across requests. Each page uses one short read
transaction so its parent facts and item rows describe the same current revisions.
"""

import math
import re
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from shopping.storage.connection import connect_database, transaction

_ORDER_FROM = """
    FROM orders o
    JOIN retailers r ON r.id = o.retailer_id
    JOIN order_revisions rev ON rev.order_id = o.id AND rev.is_current = 1
"""
_ITEM_FROM = (
    _ORDER_FROM
    + """
    JOIN order_items oi ON oi.order_revision_id = rev.id
    JOIN retailer_products rp ON rp.id = oi.retailer_product_id
    JOIN products p ON p.id = rp.product_id
"""
)
_ORDER_FIELDS = """
    o.id AS order_id, o.external_order_id, r.name AS retailer_name,
    rev.delivery_at AS purchase_date, rev.status, rev.currency, rev.total_cents,
    (SELECT COUNT(*) FROM order_items WHERE order_revision_id = rev.id) AS item_count
"""
_ITEM_FIELDS = """
    oi.id AS order_item_id, oi.line_number, p.id AS product_id,
    p.canonical_name, oi.raw_name, oi.quantity, oi.unit,
    oi.unit_price_cents, oi.gross_cents, oi.discount_cents, oi.net_cents
"""
_DATE_ORDER = "rev.delivery_at IS NULL, rev.delivery_at DESC, o.id DESC"


def read_page(
    database_path: Path, name: str, arguments: dict[str, Any], *, offset: int, limit: int
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return parent facts and at most limit + 1 whole rows for validated inputs."""
    connection = connect_database(database_path)
    try:
        connection.execute("PRAGMA query_only = ON")
        with transaction(connection, immediate=False):
            parent: dict[str, Any] = {}
            parameters: tuple = ()
            if name == "search_products":
                # instr treats SQL wildcard characters as literal product text.
                sql = """
                    SELECT p.id AS product_id, p.canonical_name,
                        CASE WHEN lower(p.canonical_name) = lower(?) THEN 'exact'
                             WHEN instr(lower(p.canonical_name), lower(?)) = 1 THEN 'prefix'
                             ELSE 'contains' END AS match_kind
                    FROM products p
                    WHERE instr(lower(p.canonical_name), lower(?)) > 0
                    ORDER BY CASE match_kind WHEN 'exact' THEN 0 WHEN 'prefix' THEN 1 ELSE 2 END,
                             p.canonical_name COLLATE NOCASE, p.id
                """
                parameters = (arguments["query"],) * 3
            elif name == "get_product_history":
                product = connection.execute(
                    "SELECT id AS product_id, canonical_name FROM products WHERE id = ?",
                    (arguments["product_id"],),
                ).fetchone()
                if product is None:
                    return None, []
                parent = dict(product)
                sql = (
                    f"SELECT {_ITEM_FIELDS}, o.id AS order_id, o.external_order_id, "
                    "r.name AS retailer_name, rev.delivery_at AS purchase_date, "
                    f"rev.status, rev.currency {_ITEM_FROM} WHERE p.id = ? "
                    f"ORDER BY {_DATE_ORDER}, oi.line_number, oi.id"
                )
                parameters = (arguments["product_id"],)
            elif name == "list_recent_orders":
                sql = f"SELECT {_ORDER_FIELDS} {_ORDER_FROM} ORDER BY {_DATE_ORDER}"
            elif name == "get_order":
                order = connection.execute(
                    f"SELECT {_ORDER_FIELDS}, rev.ordered_at, rev.subtotal_cents, "
                    "rev.discount_cents, rev.delivery_fee_cents, rev.service_fee_cents, "
                    "rev.other_fee_cents, rev.tax_cents, rev.included_tax_cents "
                    f"{_ORDER_FROM} WHERE o.id = ?",
                    (arguments["order_id"],),
                ).fetchone()
                if order is None:
                    return None, []
                parent = dict(order)
                sql = (
                    f"SELECT {_ITEM_FIELDS} {_ITEM_FROM} WHERE o.id = ? "
                    "ORDER BY oi.line_number, oi.id"
                )
                parameters = (arguments["order_id"],)
            else:
                raise ValueError("Unknown read tool")
            rows = connection.execute(
                sql + " LIMIT ? OFFSET ?", (*parameters, limit + 1, offset)
            ).fetchall()
            return parent, [dict(row) for row in rows]
    finally:
        connection.close()


_ORDER_SORTS = {
    "source_desc": "rev.source_event_at DESC, o.id DESC",
    "source_asc": "rev.source_event_at ASC, o.id ASC",
    "delivery_asc": (
        "rev.delivery_at IS NULL, rev.delivery_at ASC, rev.source_event_at DESC, o.id DESC"
    ),
    "total_desc": "rev.total_cents DESC, rev.source_event_at DESC, o.id DESC",
}

_STABLE_ERROR = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")


def _stable_error_code(value: object) -> str:
    raw = str(value or "").strip().split(maxsplit=1)[0].rstrip(":")
    return raw if _STABLE_ERROR.fullmatch(raw) else "source_error"


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_orders(
    database_path: Path,
    *,
    query: str = "",
    retailer: str = "",
    status: str = "",
    sort: str = "source_desc",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Return one filtered page of current logical orders."""

    clean_query = query.strip()[:200]
    clean_retailer = retailer.strip()[:100]
    clean_status = status.strip()[:32]
    page_size = min(max(page_size, 1), 100)
    where = ["rev.is_current = 1"]
    parameters: list[object] = []

    if clean_query:
        pattern = _like_pattern(clean_query)
        where.append(
            """
            (
                o.external_order_id LIKE ? ESCAPE '\\' COLLATE NOCASE
                OR r.name LIKE ? ESCAPE '\\' COLLATE NOCASE
                OR EXISTS (
                    SELECT 1
                    FROM order_items search_item
                    JOIN retailer_products search_listing
                      ON search_listing.id = search_item.retailer_product_id
                    JOIN products search_product ON search_product.id = search_listing.product_id
                    WHERE search_item.order_revision_id = rev.id
                      AND (
                          search_item.raw_name LIKE ? ESCAPE '\\' COLLATE NOCASE
                          OR search_product.canonical_name LIKE ? ESCAPE '\\' COLLATE NOCASE
                          OR COALESCE(search_listing.external_sku, '')
                             LIKE ? ESCAPE '\\' COLLATE NOCASE
                      )
                )
            )
            """
        )
        parameters.extend((pattern, pattern, pattern, pattern, pattern))
    if clean_retailer:
        where.append("r.slug = ?")
        parameters.append(clean_retailer)
    if clean_status:
        where.append("rev.status = ?")
        parameters.append(clean_status)

    where_sql = " AND ".join(where)
    order_sql = _ORDER_SORTS.get(sort, _ORDER_SORTS["source_desc"])
    connection = connect_database(database_path)
    try:
        total = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM orders o
                JOIN retailers r ON r.id = o.retailer_id
                JOIN order_revisions rev ON rev.order_id = o.id
                WHERE {where_sql}
                """,
                parameters,
            ).fetchone()[0]
        )
        pages = max(1, math.ceil(total / page_size))
        current_page = min(max(page, 1), pages)
        offset = (current_page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT
                o.id,
                o.external_order_id,
                r.slug AS retailer_slug,
                r.name AS retailer_name,
                rev.source_event_at,
                rev.delivery_at,
                rev.currency,
                rev.total_cents,
                rev.status,
                (SELECT COUNT(*) FROM order_items item
                 WHERE item.order_revision_id = rev.id) AS item_count,
                (SELECT COUNT(*) FROM order_revisions history
                 WHERE history.order_id = o.id) AS revision_count,
                (SELECT GROUP_CONCAT(item.raw_name, ' · ')
                 FROM order_items item
                 WHERE item.order_revision_id = rev.id) AS item_names
            FROM orders o
            JOIN retailers r ON r.id = o.retailer_id
            JOIN order_revisions rev ON rev.order_id = o.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*parameters, page_size, offset),
        ).fetchall()
        retailers = connection.execute(
            "SELECT slug, name FROM retailers ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": current_page,
            "pages": pages,
            "page_size": page_size,
            "retailers": [dict(row) for row in retailers],
        }
    finally:
        connection.close()


def get_order_history(database_path: Path, order_id: int) -> list[dict[str, Any]]:
    """Return revisions in source-event order with compact provenance counts."""

    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                revision.id,
                revision.revision_number,
                revision.revision_kind,
                revision.source_event_at,
                revision.ordered_at,
                revision.delivery_at,
                revision.currency,
                revision.total_cents,
                revision.status,
                revision.is_current,
                revision.parser_version,
                revision.created_at,
                (SELECT COUNT(*) FROM order_items item
                 WHERE item.order_revision_id = revision.id) AS item_count,
                (SELECT COUNT(*) FROM order_revision_sources source
                 WHERE source.order_revision_id = revision.id) AS source_count
            FROM order_revisions revision
            WHERE revision.order_id = ?
            ORDER BY revision.source_event_at DESC, revision.revision_number DESC
            """,
            (order_id,),
        ).fetchall()
        revisions = [dict(row) for row in rows]
        if not revisions:
            return []
        identifiers = [int(revision["id"]) for revision in revisions]
        placeholders = ", ".join("?" for _ in identifiers)
        sources_by_revision: dict[int, list[dict[str, Any]]] = {
            identifier: [] for identifier in identifiers
        }
        source_rows = connection.execute(
            f"""
            SELECT
                source_link.order_revision_id,
                message.source_kind,
                message.parse_status,
                message.source_sent_at,
                message.received_at,
                message.sender,
                message.raw_sha256,
                message.parse_error
            FROM order_revision_sources source_link
            JOIN email_messages message ON message.id = source_link.email_message_id
            WHERE source_link.order_revision_id IN ({placeholders})
            ORDER BY message.received_at DESC
            """,
            identifiers,
        ).fetchall()
        for row in source_rows:
            address = parseaddr(str(row["sender"]))[1]
            domain = address.rpartition("@")[2].casefold() if "@" in address else "unknown"
            sources_by_revision[int(row["order_revision_id"])].append(
                {
                    "source_kind": str(row["source_kind"]),
                    "parse_status": str(row["parse_status"]),
                    "source_sent_at": row["source_sent_at"],
                    "received_at": row["received_at"],
                    "sender_domain": domain,
                    "raw_hash_prefix": str(row["raw_sha256"])[:8],
                    "error_code": (
                        _stable_error_code(row["parse_error"])
                        if row["parse_error"] is not None
                        else None
                    ),
                }
            )
        for revision in revisions:
            revision["sources"] = sources_by_revision[int(revision["id"])]
        return revisions
    finally:
        connection.close()


def list_scheduled_deliveries(
    database_path: Path, *, now: datetime | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    """Return future dated deliveries without inferring fulfilment state."""

    reference = now or datetime.now(UTC)
    if reference.utcoffset() is None:
        raise ValueError("delivery reference time must be timezone-aware")
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                orders.id,
                orders.external_order_id,
                retailers.name AS retailer_name,
                revision.delivery_at,
                revision.currency,
                revision.total_cents,
                revision.status
            FROM orders
            JOIN retailers ON retailers.id = orders.retailer_id
            JOIN order_revisions revision
              ON revision.order_id = orders.id AND revision.is_current = 1
            WHERE revision.delivery_at IS NOT NULL
              AND revision.delivery_at >= ?
              AND revision.status NOT IN ('cancelled', 'refunded')
            ORDER BY revision.delivery_at ASC, orders.id ASC
            LIMIT ?
            """,
            (reference.isoformat(timespec="seconds"), limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_current_orders(database_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT o.id, o.external_order_id, r.name AS retailer_name,
                   rev.ordered_at, rev.delivery_at, rev.currency,
                   rev.total_cents, rev.status,
                   COUNT(oi.id) AS item_count
            FROM orders o
            JOIN retailers r ON r.id = o.retailer_id
            JOIN order_revisions rev ON rev.order_id = o.id AND rev.is_current = 1
            LEFT JOIN order_items oi ON oi.order_revision_id = rev.id
            GROUP BY o.id, rev.id
            ORDER BY COALESCE(rev.delivery_at, rev.ordered_at, rev.source_event_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def count_current_orders(database_path: Path) -> int:
    connection = connect_database(database_path)
    try:
        return int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM order_revisions rev
                WHERE rev.is_current = 1
                """
            ).fetchone()[0]
        )
    finally:
        connection.close()


def get_current_order(database_path: Path, order_id: int) -> dict[str, Any] | None:
    connection = connect_database(database_path)
    try:
        order = connection.execute(
            """
            SELECT o.id, o.external_order_id, r.name AS retailer_name,
                   rev.id AS revision_id, rev.revision_number, rev.revision_kind,
                   rev.ordered_at, rev.delivery_at, rev.currency,
                   rev.subtotal_cents, rev.discount_cents,
                   rev.delivery_fee_cents, rev.service_fee_cents,
                   rev.other_fee_cents, rev.tax_cents, rev.included_tax_cents,
                   rev.total_cents, rev.status
            FROM orders o
            JOIN retailers r ON r.id = o.retailer_id
            JOIN order_revisions rev ON rev.order_id = o.id AND rev.is_current = 1
            WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()
        if order is None:
            return None
        result = dict(order)
        result["items"] = [
            dict(row)
            for row in connection.execute(
                """
                SELECT oi.line_number, p.canonical_name, oi.raw_name, oi.quantity,
                       oi.unit, oi.unit_price_cents, oi.discount_cents, oi.net_cents
                FROM order_items oi
                JOIN retailer_products rp ON rp.id = oi.retailer_product_id
                JOIN products p ON p.id = rp.product_id
                WHERE oi.order_revision_id = ?
                ORDER BY oi.line_number
                """,
                (order["revision_id"],),
            ).fetchall()
        ]
        return result
    finally:
        connection.close()
