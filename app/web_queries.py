"""Read-only query models for the server-rendered web interface."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from app.db.connection import connect_database

_ORDER_SORTS = {
    "source_desc": "rev.source_event_at DESC, o.id DESC",
    "source_asc": "rev.source_event_at ASC, o.id ASC",
    "delivery_asc": (
        "rev.delivery_at IS NULL, rev.delivery_at ASC, rev.source_event_at DESC, o.id DESC"
    ),
    "total_desc": "rev.total_cents DESC, rev.source_event_at DESC, o.id DESC",
}

_STABLE_ERROR = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")


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


def overview_snapshot(database_path: Path) -> dict[str, Any]:
    """Return aggregate current facts without double-counting revisions."""

    connection = connect_database(database_path)
    try:
        current_orders = int(
            connection.execute(
                "SELECT COUNT(*) FROM order_revisions WHERE is_current = 1"
            ).fetchone()[0]
        )
        current_item_lines = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM order_items item
                JOIN order_revisions revision ON revision.id = item.order_revision_id
                WHERE revision.is_current = 1
                """
            ).fetchone()[0]
        )
        archived_messages = int(
            connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0]
        )
        recorded_values = [
            dict(row)
            for row in connection.execute(
                """
                SELECT currency, SUM(total_cents) AS total_cents
                FROM order_revisions
                WHERE is_current = 1
                GROUP BY currency
                ORDER BY currency
                """
            ).fetchall()
        ]
        attention = {
            str(row["kind"]): int(row["count"])
            for row in connection.execute(
                """
                SELECT parse_status AS kind, COUNT(*) AS count
                FROM email_messages
                WHERE parse_status IN ('failed', 'needs_review')
                GROUP BY parse_status
                UNION ALL
                SELECT 'gmail_sync_error' AS kind, COUNT(*) AS count
                FROM email_sync_state
                WHERE last_error IS NOT NULL
                UNION ALL
                SELECT 'unknown_order' AS kind, COUNT(*) AS count
                FROM order_revisions
                WHERE is_current = 1 AND status = 'unknown'
                """
            ).fetchall()
            if int(row["count"])
        }
        return {
            "current_orders": current_orders,
            "current_item_lines": current_item_lines,
            "archived_messages": archived_messages,
            "recorded_values": recorded_values,
            "attention": attention,
            "attention_count": sum(attention.values()),
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


def _stable_error_code(value: object) -> str:
    raw = str(value or "").strip().split(maxsplit=1)[0].rstrip(":")
    return raw if _STABLE_ERROR.fullmatch(raw) else "source_error"


def system_snapshot(database_path: Path) -> dict[str, Any]:
    """Return current operational evidence with private account identifiers omitted."""

    connection = connect_database(database_path)
    try:
        ingestion = {
            str(row["parse_status"]): int(row["count"])
            for row in connection.execute(
                "SELECT parse_status, COUNT(*) AS count FROM email_messages GROUP BY parse_status"
            ).fetchall()
        }
        sync_states = [
            {
                "last_success_at": row["last_success_at"],
                "last_error_at": row["last_error_at"],
                "last_error": _stable_error_code(row["last_error"]),
                "updated_at": row["updated_at"],
            }
            for row in connection.execute(
                """
                SELECT last_success_at, last_error_at, last_error, updated_at
                FROM email_sync_state
                ORDER BY updated_at DESC
                """
            ).fetchall()
        ]
        normalization = {
            "provisional": int(
                connection.execute(
                    "SELECT COUNT(*) FROM retailer_products WHERE match_status = 'provisional'"
                ).fetchone()[0]
            ),
            "rejected": int(
                connection.execute(
                    "SELECT COUNT(*) FROM retailer_products WHERE match_status = 'rejected'"
                ).fetchone()[0]
            ),
            "unreviewed_aliases": int(
                connection.execute(
                    "SELECT COUNT(*) FROM product_aliases WHERE review_status = 'unreviewed'"
                ).fetchone()[0]
            ),
        }
        return {
            "ingestion": ingestion,
            "gmail_sync": sync_states,
            "normalization": normalization,
        }
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


def list_recent_sources(database_path: Path, *, limit: int = 5) -> list[dict[str, Any]]:
    """Return privacy-minimised source activity for the Overview."""

    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT source_kind, parse_status, received_at, parsed_at,
                   sender, raw_sha256, parse_error
            FROM email_messages
            ORDER BY COALESCE(parsed_at, received_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            address = parseaddr(str(row["sender"]))[1]
            domain = address.rpartition("@")[2].casefold() if "@" in address else "unknown"
            result.append(
                {
                    "source_kind": str(row["source_kind"]),
                    "parse_status": str(row["parse_status"]),
                    "event_at": row["parsed_at"] or row["received_at"],
                    "sender_domain": domain,
                    "raw_hash_prefix": str(row["raw_sha256"])[:8],
                    "error_code": (
                        _stable_error_code(row["parse_error"])
                        if row["parse_error"] is not None
                        else None
                    ),
                }
            )
        return result
    finally:
        connection.close()
