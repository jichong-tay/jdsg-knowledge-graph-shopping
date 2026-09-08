from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db.migrations import migrate


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "email"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    value = Settings(
        environment="development",
        data_dir=data_dir,
        database_path=data_dir / "shopping.sqlite3",
        raw_email_dir=data_dir / "raw-email",
        migrations_dir=Path(__file__).parent.parent / "app" / "migrations",
        allow_synthetic_fixtures=True,
    )
    value.prepare_private_directories()
    migrate(value.database_path, value.migrations_dir)
    return value


@pytest.fixture
def purchase_facts(settings, fixture_dir):
    """Synthetic current orders with tied/missing dates and more than one item page."""
    from app.db.connection import connect_database, transaction
    from app.ingestion import import_eml

    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    connection = connect_database(settings.database_path)
    try:
        with transaction(connection):
            for order_id, date in [
                (2, None),
                (3, "2026-01-12T10:00:00+00:00"),
                (4, "2026-01-10T18:00:00+00:00"),
            ]:
                connection.execute(
                    "INSERT INTO orders VALUES (?, 1, ?, '2026-01-01T00:00:00+00:00')",
                    (order_id, f"EXAMPLE{order_id:02}"),
                )
                connection.execute(
                    """INSERT INTO order_revisions (
                        id, order_id, email_message_id, revision_number, revision_kind,
                        revision_fingerprint, parser_version, source_event_at, ordered_at,
                        delivery_at, currency, total_cents, status, created_at
                    ) VALUES (?, ?, 1, 1, 'confirmation', ?, 'synthetic',
                              '2026-02-01T00:00:00+00:00', '2026-02-01T00:00:00+00:00',
                              ?, 'SGD', 125, 'placed', '2026-01-01T00:00:00+00:00')""",
                    (order_id, order_id, f"revision-{order_id}", date),
                )
                for line in range(1, 61 if order_id == 3 else 2):
                    connection.execute(
                        """INSERT INTO order_items (
                            order_revision_id, line_number, line_fingerprint,
                            retailer_product_id, raw_name, quantity, unit, unit_price_cents,
                            gross_cents, discount_cents, net_cents, created_at
                        ) VALUES (?, ?, ?, 1, 'Example Oat Drink 1L', 0.5, 'kg',
                                  NULL, NULL, 0, 125, '2026-01-01T00:00:00+00:00')""",
                        (order_id, line, f"line-{line}"),
                    )
            connection.execute(
                """INSERT INTO order_revisions (
                    id, order_id, email_message_id, revision_number, revision_kind,
                    revision_fingerprint, parser_version, source_event_at, delivery_at,
                    currency, total_cents, status, is_current, created_at
                ) VALUES (5, 1, 1, 2, 'confirmation', 'historical', 'synthetic',
                          '2025-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00',
                          'SGD', 999, 'placed', 0, '2026-01-01T00:00:00+00:00')"""
            )
            connection.execute(
                """INSERT INTO order_items (
                    order_revision_id, line_number, line_fingerprint,
                    retailer_product_id, raw_name, quantity, net_cents, created_at
                ) VALUES (5, 1, 'historical-line', 1, 'Historical oat', 9, 999,
                          '2026-01-01T00:00:00+00:00')"""
            )
    finally:
        connection.close()
    return settings
