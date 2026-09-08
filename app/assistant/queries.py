"""Bounded current-fact reads. Missing Purchase Dates sort last, then IDs descend.

Pages read live state, not snapshots across requests. Each page uses one short read
transaction so its parent facts and item rows describe the same current revisions.
"""

from pathlib import Path
from typing import Any

from app.db.connection import connect_database, transaction

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
