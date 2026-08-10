from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

import app.ingestion
from app.db.connection import connect_database
from app.db.repository import persist_parsed_email
from app.email.archive import MAX_EMAIL_BYTES, archive_raw_email
from app.email.normalize import utc_iso
from app.email.parsers import UnsupportedEmailError, parse_order_email
from app.ingestion import import_eml


def _counts(database_path: Path) -> dict[str, int]:
    connection = connect_database(database_path)
    try:
        tables = (
            "email_messages",
            "orders",
            "order_revisions",
            "order_revision_sources",
            "order_items",
        )
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
    finally:
        connection.close()


def test_import_and_exact_repeat_are_idempotent(settings, fixture_dir: Path) -> None:
    path = fixture_dir / "fairprice_order_minimal.eml"
    first = import_eml(path, settings)
    before = _counts(settings.database_path)
    second = import_eml(path, settings)

    assert first.outcome == "imported"
    assert second.outcome == "duplicate_source"
    assert second.email_message_id == first.email_message_id
    assert second.order_id == first.order_id
    assert second.order_revision_id == first.order_revision_id
    assert (
        _counts(settings.database_path)
        == before
        == {
            "email_messages": 1,
            "orders": 1,
            "order_revisions": 1,
            "order_revision_sources": 1,
            "order_items": 2,
        }
    )
    archived = Path(first.archived_path)
    assert archived.read_bytes() == path.read_bytes()
    assert archived.stat().st_mode & 0o777 == 0o600
    assert archived.parent.name == archived.stem[:2]
    assert archived.parent.parent.name == "manual"


def test_second_wrapper_links_to_same_revision(settings, fixture_dir: Path) -> None:
    first = import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    second = import_eml(fixture_dir / "fairprice_order_forwarded_again.eml", settings)

    assert second.outcome == "duplicate_revision"
    assert second.email_message_id != first.email_message_id
    assert second.order_revision_id == first.order_revision_id
    assert _counts(settings.database_path)["email_messages"] == 2
    assert _counts(settings.database_path)["order_revisions"] == 1
    assert _counts(settings.database_path)["order_revision_sources"] == 2


def test_concurrent_repeat_creates_one_revision(settings, fixture_dir: Path) -> None:
    path = fixture_dir / "fairprice_order_minimal.eml"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: import_eml(path, settings), range(2)))

    assert sorted(result.outcome for result in results) == ["duplicate_source", "imported"]
    assert _counts(settings.database_path) == {
        "email_messages": 1,
        "orders": 1,
        "order_revisions": 1,
        "order_revision_sources": 1,
        "order_items": 2,
    }


def test_later_source_preserves_old_revision_and_becomes_current(
    settings, fixture_dir: Path
) -> None:
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    adjusted = import_eml(fixture_dir / "fairprice_order_adjusted.eml", settings)

    assert adjusted.outcome == "imported"
    connection = connect_database(settings.database_path)
    try:
        revisions = connection.execute(
            """
            SELECT revision_number, revision_kind, is_current
            FROM order_revisions ORDER BY revision_number
            """
        ).fetchall()
        assert [tuple(row) for row in revisions] == [
            (1, "confirmation", 0),
            (2, "confirmation", 1),
        ]
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 4
        # An acknowledgement is still placed, so it is not yet a completed purchase fact.
        assert connection.execute("SELECT COUNT(*) FROM purchase_history").fetchone()[0] == 0
    finally:
        connection.close()


def test_older_confirmation_imported_late_stays_historical(settings, fixture_dir: Path) -> None:
    import_eml(fixture_dir / "fairprice_order_adjusted.eml", settings)
    confirmation = import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)

    assert confirmation.outcome == "imported"
    connection = connect_database(settings.database_path)
    try:
        revisions = connection.execute(
            """
            SELECT revision_number, revision_kind, is_current
            FROM order_revisions ORDER BY revision_number
            """
        ).fetchall()
        assert [tuple(row) for row in revisions] == [
            (1, "confirmation", 1),
            (2, "confirmation", 0),
        ]
        assert connection.execute("SELECT COUNT(*) FROM purchase_history").fetchone()[0] == 0
    finally:
        connection.close()


def test_later_source_reverting_to_earlier_facts_becomes_current(
    settings, fixture_dir: Path, tmp_path: Path
) -> None:
    first = import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    second = import_eml(fixture_dir / "fairprice_order_adjusted.eml", settings)
    reverted_raw = (
        (fixture_dir / "fairprice_order_minimal.eml")
        .read_bytes()
        .replace(b"10:00:00", b"12:00:00", 1)
        .replace(b"fairprice-order-example01-v1", b"fairprice-order-example01-v3", 1)
    )
    reverted_path = tmp_path / "fairprice-order-reverted.eml"
    reverted_path.write_bytes(reverted_raw)

    reverted = import_eml(reverted_path, settings)

    assert reverted.outcome == "imported"
    assert reverted.order_revision_id not in {
        first.order_revision_id,
        second.order_revision_id,
    }
    connection = connect_database(settings.database_path)
    try:
        revisions = connection.execute(
            """
            SELECT revision_number, total_cents, source_event_at, is_current
            FROM order_revisions ORDER BY revision_number
            """
        ).fetchall()
        assert [row["revision_number"] for row in revisions] == [1, 2, 3]
        assert [row["total_cents"] for row in revisions] == [1_400, 1_890, 1_400]
        assert [row["is_current"] for row in revisions] == [0, 0, 1]
        assert revisions[0]["source_event_at"] < revisions[1]["source_event_at"]
        assert revisions[1]["source_event_at"] < revisions[2]["source_event_at"]
    finally:
        connection.close()


def test_unsupported_email_is_archived_and_recorded_without_order(
    settings, fixture_dir: Path
) -> None:
    path = fixture_dir / "unsupported.eml"
    with pytest.raises(UnsupportedEmailError):
        import_eml(path, settings)

    connection = connect_database(settings.database_path)
    try:
        source = connection.execute(
            "SELECT parse_status, raw_path, parse_error FROM email_messages"
        ).fetchone()
        assert source["parse_status"] == "failed"
        assert Path(source["raw_path"]).read_bytes() == path.read_bytes()
        assert "E_VENDOR_LAYOUT" in source["parse_error"]
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    finally:
        connection.close()


def test_successful_reparse_refreshes_failed_source_provenance(settings, fixture_dir: Path) -> None:
    path = fixture_dir / "fairprice_order_minimal.eml"
    without_fixture_sender = replace(settings, allow_synthetic_fixtures=False)
    with pytest.raises(UnsupportedEmailError):
        import_eml(path, without_fixture_sender)

    connection = connect_database(settings.database_path)
    try:
        failed = connection.execute(
            """
            SELECT id, source_fingerprint, original_message_id, source_sent_at, parse_status
            FROM email_messages
            """
        ).fetchone()
        assert failed["source_fingerprint"] == sha256(path.read_bytes()).hexdigest()
        assert failed["original_message_id"] is None
        assert failed["source_sent_at"] is None
        assert failed["parse_status"] == "failed"
        failed_id = int(failed["id"])
    finally:
        connection.close()

    imported = import_eml(path, settings)
    expected = parse_order_email(path.read_bytes(), allow_synthetic_fixtures=True)
    assert expected.metadata.source_sent_at is not None

    assert imported.outcome == "imported"
    assert imported.email_message_id == failed_id
    connection = connect_database(settings.database_path)
    try:
        refreshed = connection.execute(
            """
            SELECT source_kind, rfc822_message_id, original_message_id,
                   source_fingerprint, sender, recipient, subject, received_at,
                   source_sent_at, parse_status, parser_version, parse_error
            FROM email_messages WHERE id = ?
            """,
            (failed_id,),
        ).fetchone()
        assert refreshed["source_kind"] == expected.metadata.source_kind
        assert refreshed["rfc822_message_id"] == expected.metadata.rfc822_message_id
        assert refreshed["original_message_id"] == expected.metadata.original_message_id
        assert refreshed["source_fingerprint"] == expected.metadata.source_fingerprint
        assert refreshed["sender"] == expected.metadata.sender
        assert refreshed["recipient"] == expected.metadata.recipient
        assert refreshed["subject"] == expected.metadata.subject
        assert refreshed["received_at"] == utc_iso(expected.metadata.received_at)
        assert refreshed["source_sent_at"] == utc_iso(expected.metadata.source_sent_at)
        assert refreshed["parse_status"] == "parsed"
        assert refreshed["parser_version"] == expected.parser_version
        assert refreshed["parse_error"] is None
        assert connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 1
    finally:
        connection.close()


def test_persistence_constraint_rolls_back_order_facts(settings, fixture_dir: Path) -> None:
    connection = connect_database(settings.database_path)
    try:
        connection.execute(
            """
            CREATE TRIGGER reject_items BEFORE INSERT ON order_items
            BEGIN SELECT RAISE(ABORT, 'test rejection'); END
            """
        )
    finally:
        connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="test rejection"):
        import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)

    counts = _counts(settings.database_path)
    assert counts["email_messages"] == 0
    assert counts["orders"] == 0
    assert counts["order_revisions"] == 0
    assert list(settings.raw_email_dir.rglob("*.eml"))


def test_parser_regression_does_not_downgrade_a_parsed_source(
    settings, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = fixture_dir / "fairprice_order_minimal.eml"
    imported = import_eml(path, settings)

    def reject(*args, **kwargs):
        del args, kwargs
        raise UnsupportedEmailError("simulated parser regression")

    monkeypatch.setattr(app.ingestion, "parse_order_email", reject)
    with pytest.raises(UnsupportedEmailError, match="regression"):
        import_eml(path, settings)

    connection = connect_database(settings.database_path)
    try:
        row = connection.execute(
            "SELECT parse_status, parse_error FROM email_messages WHERE id = ?",
            (imported.email_message_id,),
        ).fetchone()
        assert tuple(row) == ("parsed", None)
        assert connection.execute("SELECT COUNT(*) FROM order_revisions").fetchone()[0] == 1
    finally:
        connection.close()


def test_distinct_skus_with_same_name_remain_distinct_products(settings, fixture_dir: Path) -> None:
    raw = (fixture_dir / "fairprice_order_minimal.eml").read_bytes()
    archived = archive_raw_email(raw, settings.raw_email_dir)
    parsed = parse_order_email(
        raw,
        source_message_key=archived.sha256,
        allow_synthetic_fixtures=True,
    )
    first, second = parsed.order.items
    shared_name = "Example Shared Listing"
    items = (
        first.model_copy(update={"name": shared_name, "external_sku": "SKU-A"}),
        second.model_copy(update={"name": shared_name, "external_sku": "SKU-B"}),
    )
    order = parsed.order.model_copy(update={"items": items})
    persist_parsed_email(
        settings.database_path,
        parsed.model_copy(update={"order": order}),
        archived,
    )

    connection = connect_database(settings.database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
        product_ids = connection.execute(
            "SELECT product_id FROM retailer_products ORDER BY external_sku"
        ).fetchall()
        assert len({row["product_id"] for row in product_ids}) == 2
    finally:
        connection.close()


def test_oversized_email_is_rejected_before_archive(settings, tmp_path: Path) -> None:
    path = tmp_path / "oversized.eml"
    with path.open("wb") as file:
        file.truncate(MAX_EMAIL_BYTES + 1)

    with pytest.raises(ValueError, match="exceeds"):
        import_eml(path, settings)

    assert not list(settings.raw_email_dir.rglob("*.eml"))
