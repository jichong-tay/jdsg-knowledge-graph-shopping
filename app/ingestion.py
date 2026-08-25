"""Coordinates crash-safe archive, deterministic parsing, and persistence."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

from app.config import Settings
from app.db.repository import (
    NeedsReviewError,
    persist_parsed_email,
    record_failed_source,
)
from app.email.archive import MAX_EMAIL_BYTES, archive_raw_email
from app.email.parsers import UnsupportedEmailError, parse_order_email
from app.models import GmailSource, ImportResult


def _failure_headers(raw: bytes) -> tuple[str, str | None, str, datetime]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
        sender = str(message.get("From", "unknown"))
        recipient = str(message.get("To", "")) or None
        subject = str(message.get("Subject", "")) or "(no subject)"
        raw_date = str(message.get("Date", ""))
        received_at = parsedate_to_datetime(raw_date) if raw_date else datetime.now(UTC)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        return sender, recipient, subject, received_at
    except Exception:
        return "unknown", None, "(unreadable message)", datetime.now(UTC)


def import_raw_email(raw: bytes, settings: Settings) -> ImportResult:
    """Import a message explicitly selected by the trusted local operator.

    Automatic Gmail ingestion must authenticate message provenance before it calls
    this boundary; matching an inner From header is extraction filtering only.
    """

    settings.prepare_private_directories()
    archived = archive_raw_email(raw, settings.raw_email_dir)
    source_message_key = archived.sha256
    try:
        parsed = parse_order_email(
            raw,
            source_message_key=source_message_key,
            allow_synthetic_fixtures=settings.allow_synthetic_fixtures,
        )
        return persist_parsed_email(settings.database_path, parsed, archived)
    except UnsupportedEmailError as error:
        sender, recipient, subject, received_at = _failure_headers(raw)
        record_failed_source(
            settings.database_path,
            archived,
            source_message_key=source_message_key,
            sender=sender,
            recipient=recipient,
            subject=subject,
            received_at=received_at,
            error=str(error),
        )
        raise
    except NeedsReviewError as error:
        sender, recipient, subject, received_at = _failure_headers(raw)
        record_failed_source(
            settings.database_path,
            archived,
            source_message_key=source_message_key,
            sender=sender,
            recipient=recipient,
            subject=subject,
            received_at=received_at,
            error=str(error),
            needs_review=True,
        )
        raise


def import_eml(path: Path, settings: Settings) -> ImportResult:
    with path.open("rb") as file:
        initial = os.fstat(file.fileno())
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError("email source must be a regular file")
        if initial.st_size > MAX_EMAIL_BYTES:
            raise ValueError(f"email exceeds the {MAX_EMAIL_BYTES}-byte limit")
        raw = file.read(MAX_EMAIL_BYTES + 1)
        final = os.fstat(file.fileno())
    if len(raw) > MAX_EMAIL_BYTES:
        raise ValueError(f"email exceeds the {MAX_EMAIL_BYTES}-byte limit")
    if (
        initial.st_size != final.st_size
        or initial.st_mtime_ns != final.st_mtime_ns
        or len(raw) != final.st_size
    ):
        raise ValueError("email changed while it was being read")
    if not raw:
        raise ValueError("email is empty")
    return import_raw_email(raw, settings)


def import_gmail_raw_email(
    raw: bytes,
    settings: Settings,
    *,
    source: GmailSource,
    provenance_verified: bool,
    provenance_code: str,
) -> ImportResult:
    """Archive and import one Gmail RAW response with trusted API metadata.

    Gmail mailbox membership and an inner From header are not authentication.
    Callers must pass the fail-closed result of the provenance verifier. An
    unverified or unsupported candidate is durably retained for review, without
    creating order facts.
    """

    settings.prepare_private_directories()
    archived = archive_raw_email(raw, settings.raw_email_dir, namespace="gmail")
    sender, recipient, subject, received_at = _failure_headers(raw)
    failure_arguments = {
        "source_message_key": source.source_message_key,
        "sender": sender,
        "recipient": recipient,
        "subject": subject,
        "received_at": received_at,
        "needs_review": True,
        "source_kind": "gmail",
        "gmail_message_id": source.message_id,
        "gmail_thread_id": source.thread_id,
        "gmail_internal_at": source.internal_at,
    }
    if not provenance_verified:
        email_id = record_failed_source(
            settings.database_path,
            archived,
            error=f"E_GMAIL_PROVENANCE:{provenance_code}"[:1000],
            **failure_arguments,
        )
        return ImportResult(
            outcome="needs_review",
            email_message_id=email_id,
            archived_path=str(archived.path),
        )

    try:
        parsed = parse_order_email(
            raw,
            source_message_key=source.source_message_key,
            allow_synthetic_fixtures=settings.allow_synthetic_fixtures,
        )
        metadata = parsed.metadata.model_copy(
            update={
                "source_kind": "gmail",
                "gmail_message_id": source.message_id,
                "gmail_thread_id": source.thread_id,
                "gmail_internal_at": source.internal_at,
            }
        )
        return persist_parsed_email(
            settings.database_path,
            parsed.model_copy(update={"metadata": metadata}),
            archived,
        )
    except (UnsupportedEmailError, NeedsReviewError) as error:
        email_id = record_failed_source(
            settings.database_path,
            archived,
            error=str(error),
            **failure_arguments,
        )
        return ImportResult(
            outcome="needs_review",
            email_message_id=email_id,
            archived_path=str(archived.path),
        )
