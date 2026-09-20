from __future__ import annotations

import fcntl
import sqlite3
from collections import deque
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shopping.ingestion.gmail import sync as gmail_sync
from shopping.ingestion.gmail.client import (
    GmailAPIError,
    GmailHistoryMessage,
    GmailHistoryPage,
    GmailMessagePage,
    GmailMessageRef,
    GmailProfile,
    GmailRawMessage,
)
from shopping.ingestion.gmail.provenance import GmailProvenanceResult
from shopping.ingestion.gmail.state import get_gmail_sync_state, record_gmail_sync_success
from shopping.storage.connection import connect_database

_SCAN_AT = datetime(2026, 8, 12, 4, 0, tzinfo=UTC)
_INTERNAL_AT = datetime(2026, 1, 11, 2, 0, tzinfo=UTC)


class FakeGmailClient:
    def __init__(
        self,
        *,
        profiles: tuple[GmailProfile | Exception, ...] = (),
        message_pages: tuple[GmailMessagePage | Exception, ...] = (),
        history_pages: tuple[GmailHistoryPage | Exception, ...] = (),
        raw_messages: dict[str, tuple[GmailRawMessage | Exception, ...]] | None = None,
    ) -> None:
        self.profiles = deque(profiles)
        self.message_pages = deque(message_pages)
        self.history_pages = deque(history_pages)
        self.raw_messages = {
            key: deque(responses) for key, responses in (raw_messages or {}).items()
        }
        self.calls: list[tuple[object, ...]] = []

    @staticmethod
    def _next[T](values: deque[T | Exception]) -> T:
        if not values:
            raise AssertionError("unexpected fake Gmail call")
        value = values.popleft()
        if isinstance(value, Exception):
            raise value
        return value

    def get_profile(self) -> GmailProfile:
        self.calls.append(("profile",))
        value = self._next(self.profiles)
        assert isinstance(value, GmailProfile)
        return value

    def list_messages(
        self,
        *,
        query: str | None = None,
        page_token: str | None = None,
        max_results: int = 500,
    ) -> GmailMessagePage:
        self.calls.append(("messages", query, page_token, max_results))
        value = self._next(self.message_pages)
        assert isinstance(value, GmailMessagePage)
        return value

    def list_history(
        self,
        start_history_id: str,
        *,
        page_token: str | None = None,
        max_results: int = 500,
    ) -> GmailHistoryPage:
        self.calls.append(("history", start_history_id, page_token, max_results))
        value = self._next(self.history_pages)
        assert isinstance(value, GmailHistoryPage)
        return value

    def get_raw_message(self, message_id: str) -> GmailRawMessage:
        self.calls.append(("raw", message_id))
        values = self.raw_messages.get(message_id)
        if values is None:
            raise AssertionError("unexpected fake raw-message call")
        value = self._next(values)
        assert isinstance(value, GmailRawMessage)
        return value


def _profile(history_id: str = "100") -> GmailProfile:
    return GmailProfile(
        email_address="private-mailbox@example.invalid",
        messages_total=10,
        threads_total=8,
        history_id=history_id,
    )


def _reference(message_id: str = "message-1", thread_id: str = "thread-1") -> GmailMessageRef:
    return GmailMessageRef(message_id=message_id, thread_id=thread_id)


def _history_message(
    history_id: str,
    message_id: str = "message-1",
    thread_id: str = "thread-1",
) -> GmailHistoryMessage:
    return GmailHistoryMessage(
        history_id=history_id,
        message=_reference(message_id, thread_id),
    )


def _raw(
    raw_bytes: bytes,
    *,
    message_id: str = "message-1",
    thread_id: str = "thread-1",
    history_id: str = "101",
) -> GmailRawMessage:
    return GmailRawMessage(
        message_id=message_id,
        thread_id=thread_id,
        history_id=history_id,
        internal_at=_INTERNAL_AT,
        raw_bytes=raw_bytes,
    )


def _verified(*_args: object, **_kwargs: object) -> GmailProvenanceResult:
    return GmailProvenanceResult(
        verified=True,
        method="gmail_authentication_results_dkim",
        code="verified_aligned_dkim",
    )


def _unverified(*_args: object, **_kwargs: object) -> GmailProvenanceResult:
    return GmailProvenanceResult(
        verified=False,
        method="none",
        code="authentication_results_missing",
    )


def _order_raw(fixture_dir: Path) -> bytes:
    return (fixture_dir / "fairprice_order_minimal.eml").read_bytes()


def _seed_history(settings, history_id: str = "100") -> None:
    record_gmail_sync_success(
        settings.database_path,
        account_key="primary",
        history_id=history_id,
        scan_watermark_at=_SCAN_AT - timedelta(days=1),
    )


def _email_count(settings) -> int:
    connection = connect_database(settings.database_path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0])
    finally:
        connection.close()


def test_first_scan_uses_profile_cursor_broad_query_and_deduplicates_message_ids(
    settings, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _reference()
    client = FakeGmailClient(
        profiles=(_profile("110"),),
        message_pages=(
            GmailMessagePage(
                messages=(reference, reference),
                next_page_token=None,
                result_size_estimate=2,
            ),
        ),
        raw_messages={"message-1": (_raw(_order_raw(fixture_dir)),)},
    )
    monkeypatch.setattr(gmail_sync, "verify_gmail_provenance", _verified)

    summary = gmail_sync.sync_gmail(client, settings, clock=lambda: _SCAN_AT)

    assert summary.mode == "full"
    assert summary.messages_listed == 2
    assert summary.messages_deduplicated == 1
    assert summary.messages_fetched == 1
    assert summary.messages_imported == 1
    assert summary.history_id == "110"
    assert client.calls[:2] == [("profile",), ("messages", "fairprice", None, 500)]
    state = get_gmail_sync_state(settings.database_path, "primary")
    assert state is not None
    assert state.gmail_history_id == "110"
    assert state.scan_watermark_at == _SCAN_AT
    with pytest.raises(FrozenInstanceError):
        summary.messages_imported = 2  # type: ignore[misc]


def test_history_scan_skips_only_raw_without_marker_and_retains_unverified_candidate(
    settings, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_history(settings)
    relevant = _order_raw(fixture_dir)
    irrelevant = b"From: sender@example.invalid\r\nSubject: unrelated\r\n\r\nHello\r\n"
    client = FakeGmailClient(
        history_pages=(
            GmailHistoryPage(
                messages_added=(
                    _history_message("105", "candidate", "candidate-thread"),
                    _history_message("106", "irrelevant", "irrelevant-thread"),
                ),
                history_id="120",
                next_page_token=None,
            ),
        ),
        raw_messages={
            "candidate": (
                _raw(
                    relevant,
                    message_id="candidate",
                    thread_id="candidate-thread",
                    history_id="105",
                ),
            ),
            "irrelevant": (
                _raw(
                    irrelevant,
                    message_id="irrelevant",
                    thread_id="irrelevant-thread",
                    history_id="106",
                ),
            ),
        },
    )
    monkeypatch.setattr(gmail_sync, "verify_gmail_provenance", _unverified)

    summary = gmail_sync.sync_gmail(client, settings, clock=lambda: _SCAN_AT)

    assert summary.mode == "history"
    assert summary.messages_fetched == 2
    assert summary.messages_needs_review == 1
    assert summary.messages_skipped == 1
    assert _email_count(settings) == 1
    state = get_gmail_sync_state(settings.database_path, "primary")
    assert state is not None
    assert state.gmail_history_id == "120"


def test_expired_history_cursor_falls_back_to_profile_at_start_and_full_scan(settings) -> None:
    _seed_history(settings)
    client = FakeGmailClient(
        profiles=(_profile("200"),),
        history_pages=(GmailAPIError("list_history", "request", status_code=404),),
        message_pages=(
            GmailMessagePage(messages=(), next_page_token=None, result_size_estimate=0),
        ),
    )

    summary = gmail_sync.sync_gmail(client, settings, clock=lambda: _SCAN_AT)

    assert summary.mode == "full_fallback"
    assert summary.history_id == "200"
    assert client.calls == [
        ("history", "100", None, 500),
        ("profile",),
        ("messages", "fairprice", None, 500),
    ]
    state = get_gmail_sync_state(settings.database_path, "primary")
    assert state is not None
    assert state.gmail_history_id == "200"


def test_partial_history_failure_keeps_cursor_and_rerun_is_idempotent(
    settings, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_history(settings)
    raw = _order_raw(fixture_dir)
    first_page = GmailHistoryPage(
        messages_added=(_history_message("105"),),
        history_id="110",
        next_page_token="next-page",
    )
    first_client = FakeGmailClient(
        history_pages=(
            first_page,
            GmailAPIError("list_history", "request", status_code=400),
        ),
        raw_messages={"message-1": (_raw(raw, history_id="105"),)},
    )
    monkeypatch.setattr(gmail_sync, "verify_gmail_provenance", _verified)

    with pytest.raises(gmail_sync.GmailSyncError) as captured:
        gmail_sync.sync_gmail(first_client, settings, clock=lambda: _SCAN_AT)

    assert captured.value.code == "gmail_api_list_history_request"
    assert _email_count(settings) == 1
    failed_state = get_gmail_sync_state(settings.database_path, "primary")
    assert failed_state is not None
    assert failed_state.gmail_history_id == "100"
    assert failed_state.last_error == "gmail_api_list_history_request"

    second_client = FakeGmailClient(
        history_pages=(
            GmailHistoryPage(
                messages_added=(_history_message("105"),),
                history_id="120",
                next_page_token=None,
            ),
        ),
        raw_messages={"message-1": (_raw(raw, history_id="105"),)},
    )

    summary = gmail_sync.sync_gmail(
        second_client,
        settings,
        clock=lambda: _SCAN_AT + timedelta(minutes=1),
    )

    assert summary.messages_duplicate == 1
    assert summary.messages_imported == 0
    assert _email_count(settings) == 1
    succeeded_state = get_gmail_sync_state(settings.database_path, "primary")
    assert succeeded_state is not None
    assert succeeded_state.gmail_history_id == "120"
    assert succeeded_state.last_error is None


def test_retryable_api_failure_uses_bounded_injected_backoff(settings) -> None:
    sleeps: list[float] = []
    client = FakeGmailClient(
        profiles=(
            GmailAPIError("get_profile", "transient", status_code=503, retryable=True),
            _profile(),
        ),
        message_pages=(
            GmailMessagePage(messages=(), next_page_token=None, result_size_estimate=0),
        ),
    )

    summary = gmail_sync.sync_gmail(
        client,
        settings,
        sleeper=sleeps.append,
        max_attempts=2,
        clock=lambda: _SCAN_AT,
    )

    assert summary.history_id == "100"
    assert sleeps == [1.0]
    assert client.calls[:2] == [("profile",), ("profile",)]


def test_per_account_lock_is_nonblocking(settings) -> None:
    settings.prepare_gmail_directory()
    lock_path = settings.gmail_dir / "sync-primary.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        client = FakeGmailClient()

        with pytest.raises(gmail_sync.GmailSyncLockedError) as captured:
            gmail_sync.sync_gmail(client, settings, clock=lambda: _SCAN_AT)

        assert captured.value.code == "gmail_sync_locked"
        assert client.calls == []


def test_listed_thread_must_match_raw_thread(settings, fixture_dir: Path) -> None:
    client = FakeGmailClient(
        profiles=(_profile(),),
        message_pages=(
            GmailMessagePage(
                messages=(_reference(thread_id="listed-thread"),),
                next_page_token=None,
                result_size_estimate=1,
            ),
        ),
        raw_messages={"message-1": (_raw(_order_raw(fixture_dir), thread_id="different-thread"),)},
    )

    with pytest.raises(gmail_sync.GmailSyncError) as captured:
        gmail_sync.sync_gmail(client, settings, clock=lambda: _SCAN_AT)

    assert captured.value.code == "gmail_raw_thread_mismatch"
    state = get_gmail_sync_state(settings.database_path, "primary")
    assert state is not None
    assert state.gmail_history_id is None
    assert state.last_error == "gmail_raw_thread_mismatch"
    assert _email_count(settings) == 0


def test_database_failure_records_only_stable_code_and_emits_no_private_data(
    settings,
    fixture_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_marker = "DO_NOT_PRINT_PRIVATE_MAILBOX_DATA"
    client = FakeGmailClient(
        profiles=(_profile(),),
        message_pages=(
            GmailMessagePage(
                messages=(_reference(),),
                next_page_token=None,
                result_size_estimate=1,
            ),
        ),
        raw_messages={"message-1": (_raw(_order_raw(fixture_dir)),)},
    )
    monkeypatch.setattr(gmail_sync, "verify_gmail_provenance", _verified)

    def fail_import(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError(private_marker)

    monkeypatch.setattr(gmail_sync, "import_gmail_raw_email", fail_import)

    with pytest.raises(gmail_sync.GmailSyncError) as captured:
        gmail_sync.sync_gmail(client, settings, clock=lambda: _SCAN_AT)

    assert captured.value.code == "gmail_database_error"
    assert private_marker not in str(captured.value)
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    state = get_gmail_sync_state(settings.database_path, "primary")
    assert state is not None
    assert state.gmail_history_id is None
    assert state.last_error == "gmail_database_error"
