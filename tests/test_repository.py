from __future__ import annotations

from app.db.connection import connect_database, transaction
from app.db.repository import count_current_orders, list_current_orders


def test_dashboard_count_reflects_all_orders_beyond_the_list_cap(settings) -> None:
    connection = connect_database(settings.database_path)
    try:
        with transaction(connection):
            connection.execute(
                "INSERT INTO retailers (slug, name, country, created_at) "
                "VALUES ('bulk', 'Bulk Retailer', 'SG', 'now')"
            )
            retailer_id = connection.execute(
                "SELECT id FROM retailers WHERE slug = 'bulk'"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO email_messages (
                    source_kind, source_message_key, source_fingerprint, sender,
                    subject, received_at, raw_sha256, raw_path, parse_status, fetched_at
                ) VALUES ('manual', 'bulk-key', 'fp', 'sender@example.invalid',
                          'subject', 'now', 'sha', '/tmp/bulk.eml', 'parsed', 'now')
                """
            )
            email_message_id = connection.execute(
                "SELECT id FROM email_messages WHERE source_message_key = 'bulk-key'"
            ).fetchone()[0]
            for index in range(25):
                connection.execute(
                    """
                    INSERT INTO orders (retailer_id, external_order_id, created_at)
                    VALUES (?, ?, 'now')
                    """,
                    (retailer_id, f"order-{index}"),
                )
                order_id = connection.execute(
                    "SELECT id FROM orders WHERE retailer_id = ? AND external_order_id = ?",
                    (retailer_id, f"order-{index}"),
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO order_revisions (
                        order_id, email_message_id, revision_number, revision_kind,
                        revision_fingerprint, parser_version, source_event_at,
                        currency, total_cents, is_current, created_at
                    ) VALUES (?, ?, 1, 'confirmation', ?, 'test', 'now', 'SGD', 100, 1, 'now')
                    """,
                    (order_id, email_message_id, f"fingerprint-{index}"),
                )
    finally:
        connection.close()

    assert count_current_orders(settings.database_path) == 25
    assert len(list_current_orders(settings.database_path)) == 20
