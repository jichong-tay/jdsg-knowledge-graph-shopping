from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import requests
from google.auth.exceptions import RefreshError, TransportError

from app.gmail import client as gmail_client


class FakeResponse:
    def __init__(self, status_code: int, document: object, *, json_error: Exception | None = None):
        self.status_code = status_code
        self._document = document
        self._json_error = json_error

    def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._document


class FakeSession:
    def __init__(self, *responses: FakeResponse | Exception):
        self._responses = list(responses)
        self.calls: list[tuple[str, Mapping[str, object] | None, float]] = []

    def get(
        self, url: str, *, params: Mapping[str, object] | None = None, timeout: float
    ) -> FakeResponse:
        self.calls.append((url, params, timeout))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _client(session: FakeSession) -> gmail_client.GmailClient:
    return gmail_client.GmailClient(cast(Any, object()), session=session, timeout_seconds=12.5)


def test_get_profile_returns_validated_typed_profile() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {
                "emailAddress": "shopper@example.invalid",
                "messagesTotal": 42,
                "threadsTotal": 31,
                "historyId": "987654321",
            },
        )
    )

    profile = _client(session).get_profile()

    assert profile == gmail_client.GmailProfile(
        email_address="shopper@example.invalid",
        messages_total=42,
        threads_total=31,
        history_id="987654321",
    )
    assert session.calls == [
        (
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            None,
            12.5,
        )
    ]


def test_iter_messages_follows_page_tokens() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {
                "messages": [{"id": "abc_123", "threadId": "thread-1"}],
                "nextPageToken": "next-token",
                "resultSizeEstimate": 2,
            },
        ),
        FakeResponse(
            200,
            {
                "messages": [{"id": "def-456", "threadId": "thread_2"}],
                "resultSizeEstimate": 1,
            },
        ),
    )

    messages = tuple(_client(session).iter_messages(query="from:shop.example", max_results=100))

    assert messages == (
        gmail_client.GmailMessageRef("abc_123", "thread-1"),
        gmail_client.GmailMessageRef("def-456", "thread_2"),
    )
    assert session.calls[0][1] == {"maxResults": 100, "q": "from:shop.example"}
    assert session.calls[1][1] == {
        "maxResults": 100,
        "q": "from:shop.example",
        "pageToken": "next-token",
    }


def test_iter_messages_rejects_repeated_page_token() -> None:
    page = FakeResponse(200, {"messages": [], "nextPageToken": "repeat"})
    session = FakeSession(page, page)

    with pytest.raises(gmail_client.GmailAPIError, match="invalid_response"):
        tuple(_client(session).iter_messages())


def test_list_history_returns_only_messages_added() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {
                "history": [
                    {
                        "id": "201",
                        "messagesAdded": [{"message": {"id": "message_1", "threadId": "thread_1"}}],
                        "messagesDeleted": [{"message": {"id": "ignored", "threadId": "ignored"}}],
                    },
                    {"id": "202"},
                ],
                "historyId": "205",
                "nextPageToken": "history-next",
            },
        )
    )

    page = _client(session).list_history("200", max_results=50)

    assert page == gmail_client.GmailHistoryPage(
        messages_added=(
            gmail_client.GmailHistoryMessage(
                history_id="201",
                message=gmail_client.GmailMessageRef("message_1", "thread_1"),
            ),
        ),
        history_id="205",
        next_page_token="history-next",
    )
    assert session.calls[0][1] == {
        "startHistoryId": "200",
        "historyTypes": "messageAdded",
        "maxResults": 50,
    }


def test_get_raw_message_decodes_strict_base64url_and_timestamp() -> None:
    raw = b"From: sender@example.invalid\r\n\r\nSynthetic body.\r\n"
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    session = FakeSession(
        FakeResponse(
            200,
            {
                "id": "message_1",
                "threadId": "thread_1",
                "historyId": "300",
                "internalDate": "1704067200123",
                "raw": encoded,
            },
        )
    )

    message = _client(session).get_raw_message("message_1")

    assert message.raw_bytes == raw
    assert message.internal_at == datetime(2024, 1, 1, 0, 0, 0, 123000, tzinfo=UTC)
    assert session.calls[0][0].endswith("/messages/message_1")
    assert session.calls[0][1] == {"format": "raw"}


@pytest.mark.parametrize("encoded", ["not+url/safe", "A", "YQ===", "YQ==junk", "===="])
def test_get_raw_message_rejects_noncanonical_base64url(encoded: str) -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {
                "id": "message_1",
                "threadId": "thread_1",
                "historyId": "300",
                "internalDate": "1704067200000",
                "raw": encoded,
            },
        )
    )

    with pytest.raises(gmail_client.GmailAPIError, match="invalid_response"):
        _client(session).get_raw_message("message_1")


def test_get_raw_message_rejects_decoded_payload_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gmail_client, "MAX_RAW_MESSAGE_BYTES", 3)
    monkeypatch.setattr(gmail_client, "_MAX_RAW_ENCODED_BYTES", 100)
    encoded = base64.urlsafe_b64encode(b"four").decode("ascii").rstrip("=")
    session = FakeSession(
        FakeResponse(
            200,
            {
                "id": "message_1",
                "threadId": "thread_1",
                "historyId": "300",
                "internalDate": "1704067200000",
                "raw": encoded,
            },
        )
    )

    with pytest.raises(gmail_client.GmailAPIError, match="invalid_response"):
        _client(session).get_raw_message("message_1")


@pytest.mark.parametrize(
    ("status", "kind", "authentication_error", "retryable"),
    [
        (401, "authentication", True, False),
        (403, "authentication", True, False),
        (429, "rate_limit", False, True),
        (503, "transient", False, True),
        (400, "request", False, False),
    ],
)
def test_http_errors_are_sanitized_and_classified(
    status: int, kind: str, authentication_error: bool, retryable: bool
) -> None:
    private_payload = "private-user@example.invalid secret-message-body"
    session = FakeSession(FakeResponse(status, {"error": private_payload}))

    with pytest.raises(gmail_client.GmailAPIError) as captured:
        _client(session).get_profile()

    error = captured.value
    assert error.kind == kind
    assert error.authentication_error is authentication_error
    assert error.retryable is retryable
    assert error.status_code == status
    assert private_payload not in str(error)


def test_network_timeout_is_retryable_and_sanitized() -> None:
    private_url = "https://example.invalid/?token=private"
    session = FakeSession(requests.Timeout(private_url))

    with pytest.raises(gmail_client.GmailAPIError) as captured:
        _client(session).get_profile()

    assert captured.value.kind == "transient"
    assert captured.value.retryable is True
    assert private_url not in str(captured.value)


@pytest.mark.parametrize(
    ("failure", "kind", "authentication_error", "retryable"),
    [
        (RefreshError("private refresh response"), "authentication", True, False),
        (TransportError("private network detail"), "transient", False, True),
    ],
)
def test_google_auth_transport_errors_are_sanitized_and_classified(
    failure: Exception, kind: str, authentication_error: bool, retryable: bool
) -> None:
    session = FakeSession(failure)

    with pytest.raises(gmail_client.GmailAPIError) as captured:
        _client(session).get_profile()

    assert captured.value.kind == kind
    assert captured.value.authentication_error is authentication_error
    assert captured.value.retryable is retryable
    assert "private" not in str(captured.value)


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"emailAddress": "missing-at", "messagesTotal": 1, "threadsTotal": 1, "historyId": "1"},
        {
            "emailAddress": "user@example.invalid",
            "messagesTotal": True,
            "threadsTotal": 1,
            "historyId": "1",
        },
        {
            "emailAddress": "user@example.invalid",
            "messagesTotal": 1,
            "threadsTotal": 1,
            "historyId": "not-decimal",
        },
    ],
)
def test_profile_rejects_malformed_response(document: object) -> None:
    with pytest.raises(gmail_client.GmailAPIError, match="invalid_response"):
        _client(FakeSession(FakeResponse(200, document))).get_profile()


def test_invalid_json_is_a_sanitized_response_error() -> None:
    session = FakeSession(FakeResponse(200, None, json_error=ValueError("private response")))

    with pytest.raises(gmail_client.GmailAPIError) as captured:
        _client(session).get_profile()

    assert captured.value.kind == "invalid_response"
    assert "private response" not in str(captured.value)
