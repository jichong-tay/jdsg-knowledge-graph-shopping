"""Small typed Gmail REST transport built on google-auth's AuthorizedSession."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote

import requests
from google.auth.credentials import Credentials
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession

_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]*={0,2}$")
_MAX_PAGE_TOKEN_LENGTH = 4096
MAX_RAW_MESSAGE_BYTES = 20 * 1024 * 1024
_MAX_RAW_ENCODED_BYTES = ((MAX_RAW_MESSAGE_BYTES + 2) // 3) * 4

ErrorKind = Literal["authentication", "rate_limit", "transient", "request", "invalid_response"]


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _Session(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, object] | None = None, timeout: float
    ) -> _Response: ...


class GmailAPIError(RuntimeError):
    """A sanitized Gmail transport failure with actionable classifications."""

    def __init__(
        self,
        operation: str,
        kind: ErrorKind,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        authentication_error: bool = False,
    ) -> None:
        self.operation = operation
        self.kind = kind
        self.status_code = status_code
        self.retryable = retryable
        self.authentication_error = authentication_error
        status = f"HTTP {status_code}" if status_code is not None else "no HTTP response"
        super().__init__(f"Gmail API {operation} failed ({status}; {kind})")


@dataclass(frozen=True, slots=True)
class GmailProfile:
    email_address: str
    messages_total: int
    threads_total: int
    history_id: str


@dataclass(frozen=True, slots=True)
class GmailMessageRef:
    message_id: str
    thread_id: str


@dataclass(frozen=True, slots=True)
class GmailMessagePage:
    messages: tuple[GmailMessageRef, ...]
    next_page_token: str | None
    result_size_estimate: int


@dataclass(frozen=True, slots=True)
class GmailHistoryMessage:
    history_id: str
    message: GmailMessageRef


@dataclass(frozen=True, slots=True)
class GmailHistoryPage:
    messages_added: tuple[GmailHistoryMessage, ...]
    history_id: str
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class GmailRawMessage:
    message_id: str
    thread_id: str
    history_id: str
    internal_at: datetime
    raw_bytes: bytes


def _required_mapping(value: object, operation: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(operation)
    return cast(Mapping[str, object], value)


def _required_string(
    document: Mapping[str, object], key: str, operation: str, *, maximum: int = 4096
) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _invalid(operation)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise _invalid(operation)
    return value


def _gmail_id(document: Mapping[str, object], key: str, operation: str) -> str:
    value = _required_string(document, key, operation, maximum=256)
    if _SAFE_ID.fullmatch(value) is None:
        raise _invalid(operation)
    return value


def _history_id(document: Mapping[str, object], key: str, operation: str) -> str:
    value = _required_string(document, key, operation, maximum=64)
    if not value.isascii() or not value.isdecimal():
        raise _invalid(operation)
    return value


def _optional_page_token(document: Mapping[str, object], operation: str) -> str | None:
    value = document.get("nextPageToken")
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > _MAX_PAGE_TOKEN_LENGTH:
        raise _invalid(operation)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise _invalid(operation)
    return value


def _nonnegative_integer(document: Mapping[str, object], key: str, operation: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid(operation)
    return value


def _invalid(operation: str) -> GmailAPIError:
    return GmailAPIError(operation, "invalid_response")


def _status_error(operation: str, status_code: int) -> GmailAPIError:
    if status_code in {401, 403}:
        return GmailAPIError(
            operation,
            "authentication",
            status_code=status_code,
            authentication_error=True,
        )
    if status_code == 429:
        return GmailAPIError(operation, "rate_limit", status_code=status_code, retryable=True)
    if status_code in {408, 425} or 500 <= status_code <= 599:
        return GmailAPIError(operation, "transient", status_code=status_code, retryable=True)
    return GmailAPIError(operation, "request", status_code=status_code)


def _decode_raw(encoded: str, operation: str) -> bytes:
    try:
        encoded_ascii = encoded.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _invalid(operation) from exc
    if len(encoded_ascii) > _MAX_RAW_ENCODED_BYTES or _BASE64URL.fullmatch(encoded) is None:
        raise _invalid(operation)
    unpadded = encoded.rstrip("=")
    if len(unpadded) % 4 == 1:
        raise _invalid(operation)
    expected_padding = (-len(unpadded)) % 4
    if len(encoded) - len(unpadded) not in {0, expected_padding}:
        raise _invalid(operation)
    normalized = unpadded + ("=" * expected_padding)
    try:
        decoded = base64.b64decode(normalized, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _invalid(operation) from exc
    if len(decoded) > MAX_RAW_MESSAGE_BYTES:
        raise _invalid(operation)
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if canonical != unpadded:
        raise _invalid(operation)
    return decoded


class GmailClient:
    """A narrow, fakeable Gmail client for mailbox discovery and raw-message fetches."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        session: _Session | None = None,
        timeout_seconds: float = 30.0,
        base_url: str = _BASE_URL,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("Gmail timeout must be between 0 and 300 seconds")
        if not base_url.startswith("https://"):
            raise ValueError("Gmail API base URL must use HTTPS")
        self._session: _Session = session or cast(_Session, AuthorizedSession(credentials))
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url.rstrip("/")

    def _get(
        self, operation: str, path: str = "", *, params: Mapping[str, object] | None = None
    ) -> Mapping[str, object]:
        try:
            response = self._session.get(
                f"{self._base_url}{path}", params=params, timeout=self._timeout_seconds
            )
        except RefreshError as exc:
            raise GmailAPIError(operation, "authentication", authentication_error=True) from exc
        except TransportError as exc:
            raise GmailAPIError(operation, "transient", retryable=True) from exc
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise GmailAPIError(operation, "transient", retryable=True) from exc
        except requests.RequestException as exc:
            raise GmailAPIError(operation, "request") from exc
        if isinstance(response.status_code, bool) or not isinstance(response.status_code, int):
            raise _invalid(operation)
        if not 200 <= response.status_code <= 299:
            raise _status_error(operation, response.status_code)
        try:
            document = response.json()
        except (ValueError, TypeError) as exc:
            raise _invalid(operation) from exc
        return _required_mapping(document, operation)

    def get_profile(self) -> GmailProfile:
        operation = "get_profile"
        document = self._get(operation, "/profile")
        email_address = _required_string(document, "emailAddress", operation, maximum=320)
        if "@" not in email_address or email_address.startswith("@") or email_address.endswith("@"):
            raise _invalid(operation)
        return GmailProfile(
            email_address=email_address,
            messages_total=_nonnegative_integer(document, "messagesTotal", operation),
            threads_total=_nonnegative_integer(document, "threadsTotal", operation),
            history_id=_history_id(document, "historyId", operation),
        )

    def list_messages(
        self,
        *,
        query: str | None = None,
        page_token: str | None = None,
        max_results: int = 500,
    ) -> GmailMessagePage:
        operation = "list_messages"
        if isinstance(max_results, bool) or not 1 <= max_results <= 500:
            raise ValueError("max_results must be between 1 and 500")
        params: dict[str, object] = {"maxResults": max_results}
        if query is not None:
            if not query or len(query) > 4096 or any(ord(value) < 0x20 for value in query):
                raise ValueError("Gmail query must be non-empty, bounded text")
            params["q"] = query
        if page_token is not None:
            if not page_token or len(page_token) > _MAX_PAGE_TOKEN_LENGTH:
                raise ValueError("invalid Gmail page token")
            params["pageToken"] = page_token
        document = self._get(operation, "/messages", params=params)
        raw_messages = document.get("messages", ())
        if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, str | bytes):
            raise _invalid(operation)
        messages: list[GmailMessageRef] = []
        for raw_message in raw_messages:
            message = _required_mapping(raw_message, operation)
            messages.append(
                GmailMessageRef(
                    message_id=_gmail_id(message, "id", operation),
                    thread_id=_gmail_id(message, "threadId", operation),
                )
            )
        estimate = document.get("resultSizeEstimate", 0)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise _invalid(operation)
        return GmailMessagePage(
            messages=tuple(messages),
            next_page_token=_optional_page_token(document, operation),
            result_size_estimate=estimate,
        )

    def iter_messages(
        self, *, query: str | None = None, max_results: int = 500
    ) -> Iterator[GmailMessageRef]:
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            page = self.list_messages(query=query, page_token=page_token, max_results=max_results)
            yield from page.messages
            page_token = page.next_page_token
            if page_token is None:
                return
            if page_token in seen_page_tokens:
                raise _invalid("list_messages")
            seen_page_tokens.add(page_token)

    def list_history(
        self,
        start_history_id: str,
        *,
        page_token: str | None = None,
        max_results: int = 500,
    ) -> GmailHistoryPage:
        operation = "list_history"
        if not start_history_id.isascii() or not start_history_id.isdecimal():
            raise ValueError("start_history_id must be a decimal Gmail history ID")
        if isinstance(max_results, bool) or not 1 <= max_results <= 500:
            raise ValueError("max_results must be between 1 and 500")
        params: dict[str, object] = {
            "startHistoryId": start_history_id,
            "historyTypes": "messageAdded",
            "maxResults": max_results,
        }
        if page_token is not None:
            if not page_token or len(page_token) > _MAX_PAGE_TOKEN_LENGTH:
                raise ValueError("invalid Gmail page token")
            params["pageToken"] = page_token
        document = self._get(operation, "/history", params=params)
        raw_history = document.get("history", ())
        if not isinstance(raw_history, Sequence) or isinstance(raw_history, str | bytes):
            raise _invalid(operation)
        messages_added: list[GmailHistoryMessage] = []
        for raw_record in raw_history:
            record = _required_mapping(raw_record, operation)
            record_history_id = _history_id(record, "id", operation)
            additions = record.get("messagesAdded", ())
            if not isinstance(additions, Sequence) or isinstance(additions, str | bytes):
                raise _invalid(operation)
            for raw_addition in additions:
                addition = _required_mapping(raw_addition, operation)
                message = _required_mapping(addition.get("message"), operation)
                messages_added.append(
                    GmailHistoryMessage(
                        history_id=record_history_id,
                        message=GmailMessageRef(
                            message_id=_gmail_id(message, "id", operation),
                            thread_id=_gmail_id(message, "threadId", operation),
                        ),
                    )
                )
        return GmailHistoryPage(
            messages_added=tuple(messages_added),
            history_id=_history_id(document, "historyId", operation),
            next_page_token=_optional_page_token(document, operation),
        )

    def iter_history_messages(
        self, start_history_id: str, *, max_results: int = 500
    ) -> Iterator[GmailHistoryMessage]:
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            page = self.list_history(
                start_history_id, page_token=page_token, max_results=max_results
            )
            yield from page.messages_added
            page_token = page.next_page_token
            if page_token is None:
                return
            if page_token in seen_page_tokens:
                raise _invalid("list_history")
            seen_page_tokens.add(page_token)

    def get_raw_message(self, message_id: str) -> GmailRawMessage:
        operation = "get_raw_message"
        if _SAFE_ID.fullmatch(message_id) is None:
            raise ValueError("invalid Gmail message ID")
        document = self._get(
            operation,
            f"/messages/{quote(message_id, safe='')}",
            params={"format": "raw"},
        )
        returned_message_id = _gmail_id(document, "id", operation)
        if returned_message_id != message_id:
            raise _invalid(operation)
        internal_date = _required_string(document, "internalDate", operation, maximum=32)
        if not internal_date.isascii() or not internal_date.isdecimal():
            raise _invalid(operation)
        milliseconds = int(internal_date)
        try:
            internal_at = datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise _invalid(operation) from exc
        raw_encoded = _required_string(document, "raw", operation, maximum=_MAX_RAW_ENCODED_BYTES)
        return GmailRawMessage(
            message_id=returned_message_id,
            thread_id=_gmail_id(document, "threadId", operation),
            history_id=_history_id(document, "historyId", operation),
            internal_at=internal_at,
            raw_bytes=_decode_raw(raw_encoded, operation),
        )
