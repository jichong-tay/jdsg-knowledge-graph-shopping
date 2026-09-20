"""Read-only query models for the server-rendered web interface."""

from __future__ import annotations

from email.utils import parseaddr
from pathlib import Path
from typing import Any

from shopping.purchases.queries import _stable_error_code
from shopping.storage.connection import connect_database


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


def ingestion_counts(database_path: Path) -> dict[str, int]:
    connection = connect_database(database_path)
    try:
        return {
            str(row["parse_status"]): int(row["count"])
            for row in connection.execute(
                "SELECT parse_status, COUNT(*) AS count FROM email_messages GROUP BY parse_status"
            ).fetchall()
        }
    finally:
        connection.close()
