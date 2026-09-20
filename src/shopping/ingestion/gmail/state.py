"""Persistence helpers for Gmail sync cursors and outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shopping.ingestion.models import GmailSyncState
from shopping.purchases.normalization import utc_iso
from shopping.storage.connection import connect_database, transaction


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _database_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def get_gmail_sync_state(database_path: Path, account_key: str) -> GmailSyncState | None:
    connection = connect_database(database_path)
    try:
        row = connection.execute(
            "SELECT * FROM email_sync_state WHERE account_key = ?", (account_key,)
        ).fetchone()
        if row is None:
            return None
        scan_watermark_at = _database_datetime(str(row["scan_watermark_at"]))
        updated_at = _database_datetime(str(row["updated_at"]))
        if scan_watermark_at is None or updated_at is None:
            raise RuntimeError("Gmail sync state contains an invalid required timestamp")
        return GmailSyncState(
            account_key=str(row["account_key"]),
            gmail_history_id=(
                str(row["gmail_history_id"]) if row["gmail_history_id"] is not None else None
            ),
            scan_watermark_at=scan_watermark_at,
            overlap_seconds=int(row["overlap_seconds"]),
            last_success_at=_database_datetime(row["last_success_at"]),
            last_error_at=_database_datetime(row["last_error_at"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            updated_at=updated_at,
        )
    finally:
        connection.close()


def record_gmail_sync_success(
    database_path: Path,
    *,
    account_key: str,
    history_id: str,
    scan_watermark_at: datetime,
    overlap_seconds: int = 86_400,
) -> None:
    if not history_id or not history_id.isdecimal():
        raise ValueError("Gmail history ID must contain decimal digits")
    if scan_watermark_at.utcoffset() is None:
        raise ValueError("Gmail scan watermark must be timezone-aware")
    if overlap_seconds < 0:
        raise ValueError("Gmail overlap must not be negative")
    now = _utc_now()
    connection = connect_database(database_path)
    try:
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO email_sync_state (
                    account_key, gmail_history_id, scan_watermark_at,
                    overlap_seconds, last_success_at, last_error_at,
                    last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)
                ON CONFLICT(account_key) DO UPDATE SET
                    gmail_history_id = excluded.gmail_history_id,
                    scan_watermark_at = excluded.scan_watermark_at,
                    overlap_seconds = excluded.overlap_seconds,
                    last_success_at = excluded.last_success_at,
                    last_error_at = NULL,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    account_key,
                    history_id,
                    utc_iso(scan_watermark_at),
                    overlap_seconds,
                    now,
                    now,
                ),
            )
    finally:
        connection.close()


def record_gmail_sync_error(
    database_path: Path,
    *,
    account_key: str,
    scan_watermark_at: datetime,
    error_code: str,
    overlap_seconds: int = 86_400,
) -> None:
    if scan_watermark_at.utcoffset() is None:
        raise ValueError("Gmail scan watermark must be timezone-aware")
    if not error_code or len(error_code) > 200:
        raise ValueError("Gmail sync error must be a short stable code")
    now = _utc_now()
    connection = connect_database(database_path)
    try:
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO email_sync_state (
                    account_key, gmail_history_id, scan_watermark_at,
                    overlap_seconds, last_success_at, last_error_at,
                    last_error, updated_at
                ) VALUES (?, NULL, ?, ?, NULL, ?, ?, ?)
                ON CONFLICT(account_key) DO UPDATE SET
                    last_error_at = excluded.last_error_at,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    account_key,
                    utc_iso(scan_watermark_at),
                    overlap_seconds,
                    now,
                    error_code,
                    now,
                ),
            )
    finally:
        connection.close()
