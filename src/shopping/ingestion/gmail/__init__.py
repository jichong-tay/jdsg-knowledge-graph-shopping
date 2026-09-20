"""Read-only Gmail OAuth and REST transport."""

from shopping.ingestion.gmail.auth import (
    GMAIL_READONLY_SCOPE,
    GMAIL_SCOPES,
    GmailAuthError,
    authorize_gmail,
    credentials_summary,
    load_gmail_credentials,
    save_gmail_credentials,
)
from shopping.ingestion.gmail.client import (
    MAX_RAW_MESSAGE_BYTES,
    GmailAPIError,
    GmailClient,
    GmailHistoryMessage,
    GmailHistoryPage,
    GmailMessagePage,
    GmailMessageRef,
    GmailProfile,
    GmailRawMessage,
)

__all__ = [
    "GMAIL_READONLY_SCOPE",
    "GMAIL_SCOPES",
    "MAX_RAW_MESSAGE_BYTES",
    "GmailAPIError",
    "GmailAuthError",
    "GmailClient",
    "GmailHistoryMessage",
    "GmailHistoryPage",
    "GmailMessagePage",
    "GmailMessageRef",
    "GmailProfile",
    "GmailRawMessage",
    "authorize_gmail",
    "credentials_summary",
    "load_gmail_credentials",
    "save_gmail_credentials",
]
