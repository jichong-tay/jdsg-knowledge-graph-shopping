from __future__ import annotations

from shopping.ingestion.pipeline import import_eml
from shopping.purchases.queries import count_current_orders, list_current_orders, list_orders
from shopping.storage.connection import connect_database, transaction


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
    third_page = list_orders(settings.database_path, page=3, page_size=10)
    assert third_page["total"] == 25
    assert third_page["page"] == 3
    assert len(third_page["items"]) == 5

    highest_total = list_orders(settings.database_path, sort="total_desc", page=1, page_size=10)
    soonest_delivery = list_orders(
        settings.database_path, sort="delivery_asc", page=1, page_size=10
    )
    expected_ids = [f"order-{index}" for index in range(24, 14, -1)]
    assert [item["external_order_id"] for item in highest_total["items"]] == expected_ids
    assert [item["external_order_id"] for item in soonest_delivery["items"]] == expected_ids


def test_order_search_matches_products_and_treats_wildcards_literally(
    settings, fixture_dir
) -> None:
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)

    matching = list_orders(settings.database_path, query="Oat")
    wildcard = list_orders(settings.database_path, query="%")

    assert matching["total"] == 1
    assert matching["items"][0]["external_order_id"] == "EXAMPLE01"
    assert wildcard["total"] == 0
