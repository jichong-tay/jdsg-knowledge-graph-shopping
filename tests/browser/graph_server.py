"""Run a disposable synthetic server for Graph browser checks."""

from __future__ import annotations

import argparse
import importlib.util
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import uvicorn

from shopping.purchases.families import create_family, propose_membership, review_membership
from shopping.storage.connection import connect_database, transaction
from shopping.web import create_app


def _fixtures(project: Path):
    spec = importlib.util.spec_from_file_location(
        "ticket21_fixtures", project / "tests/conftest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_model(*args, **kwargs):
    raise AssertionError("Graph browser validation must not call a model")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--unassigned", action="store_true", help="skip accepted family seed")
    parser.add_argument("--empty", action="store_true", help="skip synthetic facts and family seed")
    parser.add_argument(
        "--many-products", action="store_true", help="add 40 unassigned synthetic products"
    )
    parser.add_argument(
        "--purchase-focused",
        action="store_true",
        help="seed frequent/once products and distinct dated order neighbors",
    )
    parser.add_argument("--purchase-orders", type=int, choices=(6, 12), default=6)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    fixtures = _fixtures(project)
    with tempfile.TemporaryDirectory(prefix="shopping-graph-browser-") as directory:
        state = Path(directory)
        settings = fixtures.settings.__wrapped__(state)
        if not args.empty:
            fixtures.purchase_facts.__wrapped__(settings, project / "tests/fixtures/email")
        if args.many_products:
            with connect_database(settings.database_path) as connection:
                with transaction(connection):
                    connection.executemany(
                        "INSERT INTO products(id,canonical_key,canonical_name,normalized_name,"
                        "is_active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
                        [
                            (
                                1000 + i,
                                f"many-product-{i}",
                                f"Synthetic Product {i}",
                                f"synthetic product {i}",
                                "2010-01-01T00:00:00+00:00",
                                "2010-01-01T00:00:00+00:00",
                            )
                            for i in range(1, 41)
                        ],
                    )
        if args.purchase_focused:
            _seed_purchase_focus(settings, order_count=args.purchase_orders)
        settings = replace(settings, app_origin=f"http://127.0.0.1:{args.port}")
        if not args.empty and not args.unassigned:
            family = create_family(
                settings,
                command_id=uuid4().hex,
                name="Breakfast staples",
                definition="Include synthetic oat drinks. Exclude other products.",
            )
            proposal = propose_membership(
                settings,
                command_id=uuid4().hex,
                product_id=1,
                family_id=family.id,
                expected_version=0,
                origin="manual",
                method="synthetic fixture",
                rationale="Browser acceptance example",
            )
            review_membership(
                settings,
                command_id=uuid4().hex,
                membership_id=proposal.id,
                proposal_event_id=proposal.event_id,
                expected_version=proposal.version,
                decision="accepted",
                reason="Synthetic fixture review",
            )
        app = create_app(settings, chat_runner=no_model)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def _seed_purchase_focus(settings, *, order_count: int = 6) -> None:
    """Add synthetic purchase-frequency facts without touching the operator DB."""
    now = "2026-01-01T00:00:00+00:00"
    connection = connect_database(settings.database_path)
    try:
        with transaction(connection):
            connection.executemany(
                "INSERT INTO products(id,canonical_key,canonical_name,normalized_name,is_active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",  # noqa: E501
                [
                    (
                        90,
                        "focus-frequent",
                        "Synthetic Frequent Product",
                        "synthetic frequent product",
                        now,
                        now,
                    ),
                    (
                        91,
                        "focus-once",
                        "Synthetic Once Product",
                        "synthetic once product",
                        now,
                        now,
                    ),
                ],
            )
            connection.executemany(
                "INSERT INTO retailer_products(id,retailer_id,external_sku,listing_key,product_id,latest_name,latest_size_text,match_status,match_method,match_confidence,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,'confirmed','manual',1.0,?,?)",  # noqa: E501
                [
                    (
                        90,
                        1,
                        "FOCUS-FREQUENT",
                        "focus-frequent",
                        90,
                        "Synthetic Frequent Product",
                        "500 g",
                        now,
                        now,
                    ),
                    (
                        91,
                        1,
                        "FOCUS-ONCE",
                        "focus-once",
                        91,
                        "Synthetic Once Product",
                        "1 item",
                        now,
                        now,
                    ),
                ],
            )
            for order_id in range(920, 920 + order_count):
                delivery = f"2026-08-{order_id - 919:02d}T10:00:00+00:00"
                connection.execute(
                    "INSERT INTO orders VALUES (?, 1, ?, ?)",
                    (order_id, f"FOCUS{order_id}", now),
                )
                connection.execute(
                    """INSERT INTO order_revisions (
                        id, order_id, email_message_id, revision_number, revision_kind,
                        revision_fingerprint, parser_version, source_event_at, ordered_at,
                        delivery_at, currency, total_cents, status, created_at
                    ) VALUES (?, ?, 1, 1, 'confirmation', ?, 'synthetic', ?, ?, ?, 'SGD', 500, 'completed', ?)""",  # noqa: E501
                    (
                        order_id,
                        order_id,
                        f"focus-revision-{order_id}",
                        delivery,
                        delivery,
                        delivery,
                        now,
                    ),
                )
                line_count = 2 if order_id == 920 else 1
                for line_number in range(1, line_count + 1):
                    connection.execute(
                        """INSERT INTO order_items (
                            order_revision_id, line_number, line_fingerprint,
                            retailer_product_id, raw_name, quantity, unit, unit_price_cents,
                            gross_cents, discount_cents, net_cents, created_at
                        ) VALUES (?, ?, ?, 90, 'Synthetic Frequent Product', 1, 'item', 250, 250, 0, 250, ?)""",  # noqa: E501
                        (order_id, line_number, f"focus-line-{order_id}-{line_number}", now),
                    )
            connection.execute("INSERT INTO orders VALUES (940, 1, 'FOCUS940', ?)", (now,))
            connection.execute(
                """INSERT INTO order_revisions (
                    id, order_id, email_message_id, revision_number, revision_kind,
                    revision_fingerprint, parser_version, source_event_at, ordered_at,
                    delivery_at, currency, total_cents, status, created_at
                ) VALUES (940, 940, 1, 1, 'confirmation', 'focus-revision-940', 'synthetic',
                          '2026-09-01T10:00:00+00:00', '2026-09-01T10:00:00+00:00',
                          '2026-09-01T10:00:00+00:00', 'SGD', 125, 'completed', ?)""",
                (now,),
            )
            connection.execute(
                """INSERT INTO order_items (
                    order_revision_id, line_number, line_fingerprint, retailer_product_id,
                    raw_name, quantity, unit, unit_price_cents, gross_cents, discount_cents,
                    net_cents, created_at
                ) VALUES (940, 1, 'focus-line-940-1', 91, 'Synthetic Once Product', 1, 'item', 125, 125, 0, 125, ?)""",  # noqa: E501
                (now,),
            )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
