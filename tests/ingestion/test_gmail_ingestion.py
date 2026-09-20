from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shopping.ingestion.gmail.state import (
    get_gmail_sync_state,
    record_gmail_sync_error,
    record_gmail_sync_success,
)
from shopping.ingestion.models import GmailSource
from shopping.ingestion.pipeline import import_eml, import_gmail_raw_email
from shopping.ingestion.store import NeedsReviewError
from shopping.purchases.normalization import utc_iso
from shopping.storage.connection import connect_database

_GMAIL_INTERNAL_AT = datetime(2026, 1, 11, 3, 5, tzinfo=UTC)


def _gmail_source(
    *,
    message_id: str = "gmail-message-1",
    thread_id: str = "gmail-thread-1",
) -> GmailSource:
    return GmailSource(
        account_key="primary",
        message_id=message_id,
        thread_id=thread_id,
        internal_at=_GMAIL_INTERNAL_AT,
    )


def _current_raw(fixture_dir: Path) -> bytes:
    return (fixture_dir / "fairprice_order_minimal.eml").read_bytes()


def _legacy_placeholder_raw() -> bytes:
    return b"\r\n".join(
        (
            b"From: FairPrice Online <orders@fairprice.example.invalid>",
            b"To: Example Shopper <shopper@example.invalid>",
            b"Date: Thu, 01 Jan 2015 10:00:00 +0800",
            b"Message-ID: <synthetic-legacy-order@example.invalid>",
            b"Subject: Thank you for your order LEGACY01",
            b"MIME-Version: 1.0",
            b'Content-Type: text/html; charset="utf-8"',
            b"",
            b"<html><body>",
            b"<p>This is a synthetic placeholder for an older, unsupported layout.</p>",
            b"<p>Reference LEGACY01</p>",
            b"</body></html>",
            b"",
        )
    )


def _message_counts(database_path: Path) -> tuple[int, int, int]:
    connection = connect_database(database_path)
    try:
        return (
            int(connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0]),
            int(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]),
            int(connection.execute("SELECT COUNT(*) FROM order_revisions").fetchone()[0]),
        )
    finally:
        connection.close()


def test_verified_gmail_import_persists_api_identity_and_archives_raw(
    settings, fixture_dir: Path
) -> None:
    raw = _current_raw(fixture_dir)
    source = _gmail_source()

    result = import_gmail_raw_email(
        raw,
        settings,
        source=source,
        provenance_verified=True,
        provenance_code="verified_dkim",
    )

    assert result.outcome == "imported"
    archived = Path(result.archived_path)
    assert archived.read_bytes() == raw
    assert archived.parent.parent == settings.raw_email_dir / "gmail"
    assert archived.stat().st_mode & 0o777 == 0o600

    connection = connect_database(settings.database_path)
    try:
        row = connection.execute(
            """
            SELECT source_kind, source_message_key, gmail_message_id,
                   gmail_thread_id, gmail_internal_at, parse_status
            FROM email_messages WHERE id = ?
            """,
            (result.email_message_id,),
        ).fetchone()
        assert tuple(row) == (
            "gmail",
            source.source_message_key,
            source.message_id,
            source.thread_id,
            utc_iso(source.internal_at),
            "parsed",
        )
    finally:
        connection.close()


def test_verified_gmail_repeat_is_idempotent(settings, fixture_dir: Path) -> None:
    raw = _current_raw(fixture_dir)
    source = _gmail_source()

    first = import_gmail_raw_email(
        raw,
        settings,
        source=source,
        provenance_verified=True,
        provenance_code="verified_dkim",
    )
    before = _message_counts(settings.database_path)
    second = import_gmail_raw_email(
        raw,
        settings,
        source=source,
        provenance_verified=True,
        provenance_code="verified_dkim",
    )

    assert first.outcome == "imported"
    assert second.outcome == "duplicate_source"
    assert second.email_message_id == first.email_message_id
    assert second.order_id == first.order_id
    assert second.order_revision_id == first.order_revision_id
    assert _message_counts(settings.database_path) == before == (1, 1, 1)
    assert second.archived_path == first.archived_path


def test_unverified_gmail_message_is_retained_without_order_facts(
    settings, fixture_dir: Path
) -> None:
    result = import_gmail_raw_email(
        _current_raw(fixture_dir),
        settings,
        source=_gmail_source(),
        provenance_verified=False,
        provenance_code="authentication_results_missing",
    )

    assert result.outcome == "needs_review"
    assert _message_counts(settings.database_path) == (1, 0, 0)
    connection = connect_database(settings.database_path)
    try:
        row = connection.execute(
            """
            SELECT source_kind, gmail_message_id, gmail_thread_id,
                   gmail_internal_at, parse_status, parse_error
            FROM email_messages
            """
        ).fetchone()
        assert tuple(row) == (
            "gmail",
            "gmail-message-1",
            "gmail-thread-1",
            utc_iso(_GMAIL_INTERNAL_AT),
            "needs_review",
            "E_GMAIL_PROVENANCE:authentication_results_missing",
        )
    finally:
        connection.close()


def test_verified_unsupported_legacy_layout_is_retained_for_review(settings) -> None:
    raw = _legacy_placeholder_raw()

    result = import_gmail_raw_email(
        raw,
        settings,
        source=_gmail_source(message_id="legacy-message", thread_id="legacy-thread"),
        provenance_verified=True,
        provenance_code="verified_dmarc",
    )

    assert result.outcome == "needs_review"
    assert Path(result.archived_path).read_bytes() == raw
    assert _message_counts(settings.database_path) == (1, 0, 0)
    connection = connect_database(settings.database_path)
    try:
        row = connection.execute("SELECT parse_status, parse_error FROM email_messages").fetchone()
        assert row["parse_status"] == "needs_review"
        assert str(row["parse_error"]).startswith("E_VENDOR_LAYOUT:")
    finally:
        connection.close()


def test_manual_then_gmail_exact_raw_deduplicates_across_source_kinds(
    settings, fixture_dir: Path
) -> None:
    path = fixture_dir / "fairprice_order_minimal.eml"
    manual = import_eml(path, settings)
    gmail = import_gmail_raw_email(
        path.read_bytes(),
        settings,
        source=_gmail_source(),
        provenance_verified=True,
        provenance_code="verified_dkim",
    )

    assert gmail.outcome == "duplicate_source"
    assert gmail.email_message_id == manual.email_message_id
    assert _message_counts(settings.database_path) == (1, 1, 1)
    assert Path(manual.archived_path).parent.parent.name == "manual"
    assert Path(gmail.archived_path).parent.parent.name == "gmail"

    connection = connect_database(settings.database_path)
    try:
        row = connection.execute(
            """
            SELECT source_kind, gmail_message_id, gmail_thread_id, parse_status
            FROM email_messages
            """
        ).fetchone()
        assert tuple(row) == (
            "manual",
            "gmail-message-1",
            "gmail-thread-1",
            "parsed",
        )
    finally:
        connection.close()


def test_gmail_then_manual_exact_raw_deduplicates_across_source_kinds(
    settings, fixture_dir: Path
) -> None:
    path = fixture_dir / "fairprice_order_minimal.eml"
    gmail = import_gmail_raw_email(
        path.read_bytes(),
        settings,
        source=_gmail_source(),
        provenance_verified=True,
        provenance_code="verified_dkim",
    )
    manual = import_eml(path, settings)

    assert gmail.outcome == "imported"
    assert manual.outcome == "duplicate_source"
    assert manual.email_message_id == gmail.email_message_id
    assert _message_counts(settings.database_path) == (1, 1, 1)
    assert Path(gmail.archived_path).parent.parent.name == "gmail"
    assert Path(manual.archived_path).parent.parent.name == "manual"

    connection = connect_database(settings.database_path)
    try:
        row = connection.execute(
            "SELECT source_kind, gmail_message_id, parse_status FROM email_messages"
        ).fetchone()
        assert tuple(row) == ("gmail", "gmail-message-1", "parsed")
    finally:
        connection.close()


def test_same_gmail_id_with_different_raw_bytes_fails_closed(settings, fixture_dir: Path) -> None:
    raw = _current_raw(fixture_dir)
    changed_raw = raw.replace(
        b"To: Example Shopper <shopper@example.invalid>",
        b"To: Different Shopper <different@example.invalid>",
        1,
    )
    assert changed_raw != raw
    source = _gmail_source()

    imported = import_gmail_raw_email(
        raw,
        settings,
        source=source,
        provenance_verified=True,
        provenance_code="verified_dkim",
    )
    with pytest.raises(NeedsReviewError, match="different raw bytes"):
        import_gmail_raw_email(
            changed_raw,
            settings,
            source=source,
            provenance_verified=True,
            provenance_code="verified_dkim",
        )

    assert _message_counts(settings.database_path) == (1, 1, 1)
    connection = connect_database(settings.database_path)
    try:
        row = connection.execute(
            "SELECT id, parse_status, parse_error FROM email_messages"
        ).fetchone()
        assert tuple(row) == (imported.email_message_id, "parsed", None)
    finally:
        connection.close()


def test_review_attempt_cannot_downgrade_a_parsed_gmail_source(settings, fixture_dir: Path) -> None:
    raw = _current_raw(fixture_dir)
    source = _gmail_source()
    imported = import_gmail_raw_email(
        raw,
        settings,
        source=source,
        provenance_verified=True,
        provenance_code="verified_dkim",
    )

    review = import_gmail_raw_email(
        raw,
        settings,
        source=source,
        provenance_verified=False,
        provenance_code="simulated_reverification_failure",
    )

    assert review.email_message_id == imported.email_message_id
    assert _message_counts(settings.database_path) == (1, 1, 1)
    connection = connect_database(settings.database_path)
    try:
        row = connection.execute(
            "SELECT parse_status, parse_error FROM email_messages WHERE id = ?",
            (imported.email_message_id,),
        ).fetchone()
        assert tuple(row) == ("parsed", None)
    finally:
        connection.close()


def test_gmail_sync_state_error_success_and_later_error_semantics(settings) -> None:
    account_key = "primary"
    initial_watermark = datetime(2025, 1, 1, tzinfo=UTC)
    successful_watermark = initial_watermark + timedelta(days=2)

    assert get_gmail_sync_state(settings.database_path, account_key) is None

    record_gmail_sync_error(
        settings.database_path,
        account_key=account_key,
        scan_watermark_at=initial_watermark,
        error_code="gmail_transient",
        overlap_seconds=3_600,
    )
    failed = get_gmail_sync_state(settings.database_path, account_key)
    assert failed is not None
    assert failed.gmail_history_id is None
    assert failed.scan_watermark_at == initial_watermark
    assert failed.overlap_seconds == 3_600
    assert failed.last_success_at is None
    assert failed.last_error_at is not None
    assert failed.last_error == "gmail_transient"

    record_gmail_sync_success(
        settings.database_path,
        account_key=account_key,
        history_id="123456789",
        scan_watermark_at=successful_watermark,
        overlap_seconds=7_200,
    )
    succeeded = get_gmail_sync_state(settings.database_path, account_key)
    assert succeeded is not None
    assert succeeded.gmail_history_id == "123456789"
    assert succeeded.scan_watermark_at == successful_watermark
    assert succeeded.overlap_seconds == 7_200
    assert succeeded.last_success_at is not None
    assert succeeded.last_error_at is None
    assert succeeded.last_error is None

    record_gmail_sync_error(
        settings.database_path,
        account_key=account_key,
        scan_watermark_at=successful_watermark + timedelta(days=10),
        error_code="oauth_revoked",
        overlap_seconds=1,
    )
    failed_again = get_gmail_sync_state(settings.database_path, account_key)
    assert failed_again is not None
    assert failed_again.gmail_history_id == succeeded.gmail_history_id
    assert failed_again.scan_watermark_at == succeeded.scan_watermark_at
    assert failed_again.overlap_seconds == succeeded.overlap_seconds
    assert failed_again.last_success_at == succeeded.last_success_at
    assert failed_again.last_error_at is not None
    assert failed_again.last_error == "oauth_revoked"
