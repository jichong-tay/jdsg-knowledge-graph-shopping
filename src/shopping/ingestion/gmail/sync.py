"""One-shot, cursor-based Gmail ingestion orchestration.

The synchronizer deliberately performs no scheduling and emits no output.  A
caller can run it from a CLI, systemd timer, or test while this module preserves
the same locking, retry, cursor, and failure semantics.
"""

from __future__ import annotations

import errno
import fcntl
import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from shopping.config import Settings
from shopping.ingestion.gmail.client import (
    GmailAPIError,
    GmailHistoryPage,
    GmailMessagePage,
    GmailMessageRef,
    GmailProfile,
    GmailRawMessage,
)
from shopping.ingestion.gmail.provenance import verify_gmail_provenance
from shopping.ingestion.gmail.state import (
    get_gmail_sync_state,
    record_gmail_sync_error,
    record_gmail_sync_success,
)
from shopping.ingestion.models import GmailSource, ImportResult
from shopping.ingestion.pipeline import import_gmail_raw_email

DEFAULT_ACCOUNT_KEY = "primary"
DEFAULT_GMAIL_QUERY = "fairprice"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_OVERLAP_SECONDS = 86_400

_ACCOUNT_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_STABLE_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9_]{0,99}$")
_GMAIL_OPERATIONS = frozenset({"get_profile", "list_messages", "list_history", "get_raw_message"})
_GMAIL_ERROR_KINDS = frozenset(
    {"authentication", "rate_limit", "transient", "request", "invalid_response"}
)

SyncMode = Literal["full", "history", "full_fallback"]


class GmailSyncClient(Protocol):
    """The small client surface needed by the one-shot synchronizer."""

    def get_profile(self) -> GmailProfile: ...

    def list_messages(
        self,
        *,
        query: str | None = None,
        page_token: str | None = None,
        max_results: int = 500,
    ) -> GmailMessagePage: ...

    def list_history(
        self,
        start_history_id: str,
        *,
        page_token: str | None = None,
        max_results: int = 500,
    ) -> GmailHistoryPage: ...

    def get_raw_message(self, message_id: str) -> GmailRawMessage: ...


class GmailSyncError(RuntimeError):
    """A sanitized sync failure safe to show in a CLI or store in SQLite."""

    def __init__(self, code: str) -> None:
        if _STABLE_ERROR_CODE.fullmatch(code) is None:
            code = "gmail_sync_internal_error"
        self.code = code
        super().__init__(f"Gmail sync failed ({code})")


class GmailSyncLockedError(GmailSyncError):
    """Another process already owns this account's non-blocking sync lock."""

    def __init__(self) -> None:
        super().__init__("gmail_sync_locked")


@dataclass(frozen=True, slots=True)
class GmailSyncSummary:
    """Non-sensitive totals for one completed mailbox scan."""

    account_key: str
    mode: SyncMode
    messages_listed: int
    messages_deduplicated: int
    messages_fetched: int
    messages_imported: int
    messages_duplicate: int
    messages_needs_review: int
    messages_skipped: int
    history_id: str
    scan_watermark_at: datetime


@dataclass(slots=True)
class _Counts:
    listed: int = 0
    deduplicated: int = 0
    fetched: int = 0
    imported: int = 0
    duplicate: int = 0
    needs_review: int = 0
    skipped: int = 0


@dataclass(slots=True)
class _ScanContext:
    client: GmailSyncClient
    settings: Settings
    account_key: str
    max_attempts: int
    sleeper: Callable[[float], None]
    counts: _Counts
    seen_messages: dict[str, str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _validate_history_id(history_id: str) -> None:
    if not history_id or not history_id.isascii() or not history_id.isdecimal():
        raise GmailSyncError("gmail_history_id_invalid")


def _validate_page_progress(previous: str, current: str) -> None:
    _validate_history_id(current)
    if int(current) < int(previous):
        raise GmailSyncError("gmail_history_id_regressed")


def _api_error_code(error: GmailAPIError) -> str:
    operation = error.operation if error.operation in _GMAIL_OPERATIONS else "unknown"
    kind = error.kind if error.kind in _GMAIL_ERROR_KINDS else "unknown"
    return f"gmail_api_{operation}_{kind}"


def _failure_code(error: Exception) -> str:
    if isinstance(error, GmailSyncError):
        return error.code
    if isinstance(error, GmailAPIError):
        return _api_error_code(error)
    if isinstance(error, (sqlite3.Error, FileNotFoundError)):
        return "gmail_database_error"
    if isinstance(error, OSError):
        return "gmail_local_io_error"
    return "gmail_sync_internal_error"


def _retry[T](
    call: Callable[[], T],
    *,
    max_attempts: int,
    sleeper: Callable[[float], None],
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except GmailAPIError as error:
            if not error.retryable or attempt == max_attempts:
                raise
            sleeper(float(min(2 ** (attempt - 1), 8)))
    raise AssertionError("retry loop ended without returning or raising")


def _lock_path(gmail_dir: Path, account_key: str) -> Path:
    return gmail_dir / f"sync-{account_key}.lock"


@contextmanager
def _account_lock(gmail_dir: Path, account_key: str) -> Iterator[None]:
    path = _lock_path(gmail_dir, account_key)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    locked = False
    try:
        try:
            descriptor = os.open(path, flags, 0o600)
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise GmailSyncError("gmail_sync_lock_invalid")
            if stat.S_IMODE(details.st_mode) != 0o600:
                os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    raise GmailSyncLockedError() from None
                raise
            locked = True
        except GmailSyncError:
            raise
        except OSError:
            raise GmailSyncError("gmail_sync_lock_error") from None
        yield
    finally:
        if descriptor >= 0:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)


def _record_outcome(counts: _Counts, result: ImportResult) -> None:
    if result.outcome == "imported":
        counts.imported += 1
    elif result.outcome in {"duplicate_source", "duplicate_revision"}:
        counts.duplicate += 1
    elif result.outcome == "needs_review":
        counts.needs_review += 1
    else:  # pragma: no cover - Pydantic constrains ImportResult outcomes.
        raise GmailSyncError("gmail_import_outcome_invalid")


def _process_message(
    context: _ScanContext,
    reference: GmailMessageRef,
    *,
    skip_non_candidate: bool,
) -> None:
    counts = context.counts
    counts.listed += 1
    prior_thread = context.seen_messages.get(reference.message_id)
    if prior_thread is not None:
        if prior_thread != reference.thread_id:
            raise GmailSyncError("gmail_listed_thread_mismatch")
        counts.deduplicated += 1
        return
    context.seen_messages[reference.message_id] = reference.thread_id

    raw_message = _retry(
        lambda: context.client.get_raw_message(reference.message_id),
        max_attempts=context.max_attempts,
        sleeper=context.sleeper,
    )
    counts.fetched += 1
    if raw_message.message_id != reference.message_id:
        raise GmailSyncError("gmail_raw_message_id_mismatch")
    if raw_message.thread_id != reference.thread_id:
        raise GmailSyncError("gmail_raw_thread_mismatch")
    if not isinstance(raw_message.raw_bytes, bytes) or not raw_message.raw_bytes:
        raise GmailSyncError("gmail_raw_message_invalid")

    if skip_non_candidate and b"fairprice" not in raw_message.raw_bytes.lower():
        counts.skipped += 1
        return

    provenance = verify_gmail_provenance(
        raw_message.raw_bytes,
        allow_synthetic_fixtures=context.settings.allow_synthetic_fixtures,
    )
    result = import_gmail_raw_email(
        raw_message.raw_bytes,
        context.settings,
        source=GmailSource(
            account_key=context.account_key,
            message_id=raw_message.message_id,
            thread_id=raw_message.thread_id,
            internal_at=raw_message.internal_at,
        ),
        provenance_verified=provenance.verified,
        provenance_code=provenance.code,
    )
    _record_outcome(counts, result)


def _full_scan(context: _ScanContext, query: str) -> str:
    profile = _retry(
        context.client.get_profile,
        max_attempts=context.max_attempts,
        sleeper=context.sleeper,
    )
    _validate_history_id(profile.history_id)
    page_token: str | None = None
    seen_page_tokens: set[str] = set()
    while True:
        page = _retry(
            lambda page_token=page_token: context.client.list_messages(
                query=query,
                page_token=page_token,
                max_results=500,
            ),
            max_attempts=context.max_attempts,
            sleeper=context.sleeper,
        )
        for reference in page.messages:
            _process_message(context, reference, skip_non_candidate=False)
        page_token = page.next_page_token
        if page_token is None:
            return profile.history_id
        if page_token in seen_page_tokens:
            raise GmailSyncError("gmail_message_page_cycle")
        seen_page_tokens.add(page_token)


def _history_scan(context: _ScanContext, start_history_id: str) -> str:
    _validate_history_id(start_history_id)
    page_token: str | None = None
    seen_page_tokens: set[str] = set()
    final_history_id = start_history_id
    while True:
        page = _retry(
            lambda page_token=page_token: context.client.list_history(
                start_history_id,
                page_token=page_token,
                max_results=500,
            ),
            max_attempts=context.max_attempts,
            sleeper=context.sleeper,
        )
        _validate_page_progress(final_history_id, page.history_id)
        final_history_id = page.history_id
        for addition in page.messages_added:
            _process_message(context, addition.message, skip_non_candidate=True)
        page_token = page.next_page_token
        if page_token is None:
            return final_history_id
        if page_token in seen_page_tokens:
            raise GmailSyncError("gmail_history_page_cycle")
        seen_page_tokens.add(page_token)


def _record_failure(
    settings: Settings,
    *,
    account_key: str,
    scan_watermark_at: datetime,
    overlap_seconds: int,
    error: Exception,
) -> GmailSyncError:
    code = _failure_code(error)
    try:
        record_gmail_sync_error(
            settings.database_path,
            account_key=account_key,
            scan_watermark_at=scan_watermark_at,
            error_code=code,
            overlap_seconds=overlap_seconds,
        )
    except Exception:
        return GmailSyncError("gmail_sync_state_error")
    return GmailSyncError(code)


def sync_gmail(
    client: GmailSyncClient,
    settings: Settings,
    *,
    account_key: str = DEFAULT_ACCOUNT_KEY,
    query: str = DEFAULT_GMAIL_QUERY,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    overlap_seconds: int = DEFAULT_OVERLAP_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = _utc_now,
) -> GmailSyncSummary:
    """Run one complete Gmail scan, advancing its cursor only on success.

    The initial run records Gmail's profile history ID *before* listing the broad
    search result. Later runs consume ``messagesAdded`` history. If Gmail has
    expired the saved history cursor (HTTP 404), a new full scan is performed.
    """

    if _ACCOUNT_KEY.fullmatch(account_key) is None:
        raise ValueError("Gmail account key must be a safe local identifier")
    if not query or len(query) > 4096 or any(ord(character) < 0x20 for character in query):
        raise ValueError("Gmail query must be non-empty, bounded text")
    if isinstance(max_attempts, bool) or not 1 <= max_attempts <= 10:
        raise ValueError("Gmail max attempts must be between 1 and 10")
    if isinstance(overlap_seconds, bool) or overlap_seconds < 0:
        raise ValueError("Gmail overlap must not be negative")
    scan_started_at = clock()
    if scan_started_at.utcoffset() is None:
        raise ValueError("Gmail sync clock must return a timezone-aware timestamp")
    scan_started_at = scan_started_at.astimezone(UTC)

    try:
        settings.prepare_gmail_directory()
    except OSError:
        raise GmailSyncError("gmail_directory_error") from None

    with _account_lock(settings.gmail_dir, account_key):
        try:
            state = get_gmail_sync_state(settings.database_path, account_key)
        except Exception as error:
            raise _record_failure(
                settings,
                account_key=account_key,
                scan_watermark_at=scan_started_at,
                overlap_seconds=overlap_seconds,
                error=error,
            ) from None

        effective_overlap = state.overlap_seconds if state is not None else overlap_seconds
        context = _ScanContext(
            client=client,
            settings=settings,
            account_key=account_key,
            max_attempts=max_attempts,
            sleeper=sleeper,
            counts=_Counts(),
            seen_messages={},
        )
        mode: SyncMode
        try:
            if state is None or state.gmail_history_id is None:
                mode = "full"
                history_id = _full_scan(context, query)
            else:
                mode = "history"
                try:
                    history_id = _history_scan(context, state.gmail_history_id)
                except GmailAPIError as error:
                    if error.operation != "list_history" or error.status_code != 404:
                        raise
                    mode = "full_fallback"
                    history_id = _full_scan(context, query)

            record_gmail_sync_success(
                settings.database_path,
                account_key=account_key,
                history_id=history_id,
                scan_watermark_at=scan_started_at,
                overlap_seconds=effective_overlap,
            )
        except Exception as error:
            failure_watermark = state.scan_watermark_at if state is not None else scan_started_at
            raise _record_failure(
                settings,
                account_key=account_key,
                scan_watermark_at=failure_watermark,
                overlap_seconds=effective_overlap,
                error=error,
            ) from None

        counts = context.counts
        return GmailSyncSummary(
            account_key=account_key,
            mode=mode,
            messages_listed=counts.listed,
            messages_deduplicated=counts.deduplicated,
            messages_fetched=counts.fetched,
            messages_imported=counts.imported,
            messages_duplicate=counts.duplicate,
            messages_needs_review=counts.needs_review,
            messages_skipped=counts.skipped,
            history_id=history_id,
            scan_watermark_at=scan_started_at,
        )


__all__ = [
    "DEFAULT_ACCOUNT_KEY",
    "DEFAULT_GMAIL_QUERY",
    "GmailSyncClient",
    "GmailSyncError",
    "GmailSyncLockedError",
    "GmailSyncSummary",
    "sync_gmail",
]
