from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from shopping import config as shopping_config
from shopping.config import Settings
from shopping.storage.schema import migrate


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "email"


@pytest.fixture
def sqlite_backup_module():
    path = Path(__file__).parent.parent / "deploy" / "sqlite_backup.py"
    spec = importlib.util.spec_from_file_location("shopping_test_sqlite_backup", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    value = Settings(
        environment="development",
        data_dir=data_dir,
        database_path=data_dir / "shopping.sqlite3",
        raw_email_dir=data_dir / "raw-email",
        migrations_dir=Path(shopping_config.__file__).resolve().parent / "storage" / "migrations",
        allow_synthetic_fixtures=True,
    )
    value.prepare_private_directories()
    migrate(value.database_path, value.migrations_dir)
    return value


@pytest.fixture
def purchase_facts(settings, fixture_dir):
    """Synthetic current orders with tied/missing dates and more than one item page."""
    from shopping.ingestion.pipeline import import_eml
    from shopping.storage.connection import connect_database, transaction

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


@pytest.fixture
def monthly_purchase_facts(purchase_facts):
    """Synthetic August rows covering boundaries, repeats, status, and revisions."""
    from shopping.storage.connection import connect_database, transaction

    connection = connect_database(purchase_facts.database_path)
    try:
        with transaction(connection):
            for index in range(12):
                order_id = 10 + index
                revision_id = 10 + index
                delivery = f"2026-08-{2 + index:02d}T10:00:00+00:00"
                connection.execute(
                    "INSERT INTO orders VALUES (?, 1, ?, '2026-01-01T00:00:00+00:00')",
                    (order_id, f"MONTH{order_id:02}"),
                )
                status = "cancelled" if index == 11 else "placed"
                connection.execute(
                    """INSERT INTO order_revisions (
                        id, order_id, email_message_id, revision_number, revision_kind,
                        revision_fingerprint, parser_version, source_event_at, ordered_at,
                        delivery_at, currency, total_cents, status, is_current, created_at
                    ) VALUES (?, ?, 1, 1, 'confirmation', ?, 'synthetic', ?, ?, ?,
                              'SGD', 125, ?, 1, '2026-01-01T00:00:00+00:00')""",
                    (
                        revision_id,
                        order_id,
                        f"month-{order_id}",
                        delivery,
                        delivery,
                        delivery,
                        status,
                    ),
                )
                for line in range(1, 3 if index == 0 else 2):
                    connection.execute(
                        """INSERT INTO order_items (
                            id, order_revision_id, line_number, line_fingerprint,
                            retailer_product_id, raw_name, quantity, unit, net_cents, created_at
                        ) VALUES (?, ?, ?, ?, 1, 'Monthly item', 1, 'item', 125,
                                  '2026-01-01T00:00:00+00:00')""",
                        (
                            1000 + index * 2 + line - 1,
                            revision_id,
                            line,
                            f"month-line-{order_id}-{line}",
                        ),
                    )
            connection.execute(
                """INSERT INTO orders VALUES (23, 1, 'MONTH23', '2026-01-01T00:00:00+00:00')"""
            )
            connection.execute(
                """INSERT INTO order_revisions (
                    id, order_id, email_message_id, revision_number, revision_kind,
                    revision_fingerprint, parser_version, source_event_at, ordered_at,
                    delivery_at, currency, total_cents, status, is_current, created_at
                ) VALUES (23, 23, 1, 1, 'confirmation', 'unknown-month', 'synthetic',
                          '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                          NULL, 'SGD', 125, 'placed', 1, '2026-01-01T00:00:00+00:00')"""
            )
            connection.execute(
                """INSERT INTO order_items (
                    order_revision_id, line_number, line_fingerprint,
                    retailer_product_id, raw_name, quantity, unit, net_cents, created_at
                ) VALUES (23, 1, 'unknown-month-line', 1, 'Unknown date', 1, 'item', 125,
                          '2026-01-01T00:00:00+00:00')"""
            )
            boundary_rows = (
                (30, "2026-07-31T15:59:59.999999+00:00", 2000),
                (31, "2026-07-31T16:00:00+00:00", 2001),
                (32, "2026-08-31T15:59:59.999999+00:00", 2002),
                (33, "2026-08-31T16:00:00+00:00", 2003),
            )
            for order_id, delivery, item_id in boundary_rows:
                connection.execute(
                    "INSERT INTO orders VALUES (?, 1, ?, ?)",
                    (order_id, f"BOUNDARY{order_id}", delivery),
                )
                connection.execute(
                    """INSERT INTO order_revisions (
                        id, order_id, email_message_id, revision_number, revision_kind,
                        revision_fingerprint, parser_version, source_event_at, ordered_at,
                        delivery_at, currency, total_cents, status, is_current, created_at
                    ) VALUES (?, ?, 1, 1, 'confirmation', ?, 'synthetic', ?, ?, ?,
                              'SGD', 125, 'placed', 1, ?)""",
                    (
                        order_id,
                        order_id,
                        f"boundary-{order_id}",
                        delivery,
                        delivery,
                        delivery,
                        delivery,
                    ),
                )
                connection.execute(
                    """INSERT INTO order_items (
                        id, order_revision_id, line_number, line_fingerprint,
                        retailer_product_id, raw_name, quantity, unit, net_cents, created_at
                    ) VALUES (?, ?, 1, ?, 1, 'Boundary item', 1, 'item', 125, ?)""",
                    (item_id, order_id, f"boundary-line-{order_id}", delivery),
                )
            connection.execute(
                "INSERT INTO orders VALUES (34, 1, 'HISTORIC-AUG', '2026-08-10T00:00:00+00:00')"
            )
            for revision_id, delivery, current in (
                (34, "2026-08-20T10:00:00+00:00", 0),
                (35, "2026-09-02T10:00:00+00:00", 1),
            ):
                connection.execute(
                    """INSERT INTO order_revisions (
                        id, order_id, email_message_id, revision_number, revision_kind,
                        revision_fingerprint, parser_version, source_event_at, ordered_at,
                        delivery_at, currency, total_cents, status, is_current, created_at
                    ) VALUES (?, 34, 1, ?, 'confirmation', ?, 'synthetic', ?, ?, ?,
                              'SGD', 125, 'placed', ?, ?)""",
                    (
                        revision_id,
                        revision_id - 33,
                        f"historic-{revision_id}",
                        delivery,
                        delivery,
                        delivery,
                        current,
                        delivery,
                    ),
                )
            for item_id, revision_id in ((2004, 34), (2005, 35)):
                connection.execute(
                    """INSERT INTO order_items (
                        id, order_revision_id, line_number, line_fingerprint,
                        retailer_product_id, raw_name, quantity, unit, net_cents, created_at
                    ) VALUES (?, ?, 1, ?, 1, 'Historic item', 1, 'item', 125, ?)""",
                    (item_id, revision_id, f"historic-line-{item_id}", "2026-01-01T00:00:00+00:00"),
                )
    finally:
        connection.close()
    return purchase_facts
