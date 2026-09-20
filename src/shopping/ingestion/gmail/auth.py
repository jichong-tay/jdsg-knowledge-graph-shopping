"""OAuth helpers for read-only Gmail access.

The token is deliberately kept outside configuration and is always supplied as an
explicit path by the caller.  This module never logs or returns serialized OAuth
material.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SCOPES = (GMAIL_READONLY_SCOPE,)
_MAX_TOKEN_BYTES = 64 * 1024
_MAX_CLIENT_SECRETS_BYTES = 1024 * 1024


class GmailAuthError(RuntimeError):
    """A sanitized local OAuth or credential-storage failure."""


def _private_regular_file(path: Path, *, description: str) -> os.stat_result:
    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise GmailAuthError(f"{description} does not exist: {path}") from exc
    except OSError as exc:
        raise GmailAuthError(f"could not inspect {description}: {path}") from exc

    if stat.S_ISLNK(file_stat.st_mode):
        raise GmailAuthError(f"refusing symlink for {description}: {path}")
    if not stat.S_ISREG(file_stat.st_mode):
        raise GmailAuthError(f"{description} is not a regular file: {path}")
    mode = stat.S_IMODE(file_stat.st_mode)
    if mode & 0o077:
        raise GmailAuthError(
            f"{description} must not be accessible by group or other users: {path}"
        )
    if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
        raise GmailAuthError(f"{description} is not owned by the current user: {path}")
    return file_stat


def _private_directory(path: Path) -> None:
    try:
        directory_stat = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(parents=True, mode=0o700)
            path.chmod(0o700)
        except OSError as exc:
            raise GmailAuthError(f"could not create private credential directory: {path}") from exc
        directory_stat = path.lstat()
    except OSError as exc:
        raise GmailAuthError(f"could not inspect credential directory: {path}") from exc

    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise GmailAuthError(f"credential directory must be a real directory: {path}")
    mode = stat.S_IMODE(directory_stat.st_mode)
    if mode & 0o077:
        raise GmailAuthError(
            f"credential directory must not be accessible by group or other users: {path}"
        )
    if hasattr(os, "getuid") and directory_stat.st_uid != os.getuid():
        raise GmailAuthError(f"credential directory is not owned by the current user: {path}")


def _scope_values(value: object) -> tuple[str, ...] | None:
    if isinstance(value, str):
        return tuple(part for part in value.split() if part)
    if isinstance(value, list | tuple) and all(isinstance(part, str) for part in value):
        return tuple(value)
    return None


def _require_exact_scopes(credentials: Credentials) -> None:
    scopes = _scope_values(credentials.scopes)
    if scopes is None or len(scopes) != 1 or scopes[0] != GMAIL_READONLY_SCOPE:
        raise GmailAuthError("OAuth credentials do not contain exactly the Gmail read-only scope")

    granted_scopes = _scope_values(credentials.granted_scopes)
    if granted_scopes is not None and set(granted_scopes) != {GMAIL_READONLY_SCOPE}:
        raise GmailAuthError("Google granted OAuth scopes other than Gmail read-only")


def _validate_token_document(serialized: str) -> None:
    try:
        document = json.loads(serialized)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GmailAuthError("OAuth library produced an invalid token document") from exc
    if not isinstance(document, Mapping):
        raise GmailAuthError("OAuth library produced an invalid token document")
    scopes = _scope_values(document.get("scopes"))
    if scopes is None or len(scopes) != 1 or scopes[0] != GMAIL_READONLY_SCOPE:
        raise GmailAuthError("refusing to save a token without exactly Gmail read-only access")


def _read_bounded_private_text(path: Path, *, description: str, maximum_bytes: int) -> str:
    file_stat = _private_regular_file(path, description=description)
    if file_stat.st_size <= 0 or file_stat.st_size > maximum_bytes:
        raise GmailAuthError(f"{description} has an invalid size: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GmailAuthError(f"could not read {description}: {path}") from exc


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        directory_fd = os.open(path, flags)
    except OSError as exc:
        raise GmailAuthError(f"could not open credential directory for sync: {path}") from exc
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        raise GmailAuthError(f"could not sync credential directory: {path}") from exc
    finally:
        os.close(directory_fd)


def save_gmail_credentials(credentials: Credentials, token_path: Path) -> None:
    """Atomically persist an OAuth token as a private regular file."""
    _require_exact_scopes(credentials)
    try:
        serialized = credentials.to_json()
    except (TypeError, ValueError) as exc:
        raise GmailAuthError("OAuth library could not serialize the Gmail token") from exc
    _validate_token_document(serialized)

    token_path = Path(token_path)
    _private_directory(token_path.parent)
    if token_path.exists() or token_path.is_symlink():
        _private_regular_file(token_path, description="Gmail token file")

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{token_path.name}.", suffix=".tmp", dir=token_path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
            token_file.write(serialized)
            token_file.write("\n")
            token_file.flush()
            os.fsync(token_file.fileno())
        os.replace(temporary_path, token_path)
        temporary_path = None
        token_path.chmod(0o600)
        _fsync_directory(token_path.parent)
    except GmailAuthError:
        raise
    except OSError as exc:
        raise GmailAuthError(f"could not save Gmail token: {token_path}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def authorize_gmail(
    client_secrets_path: Path,
    token_path: Path,
    *,
    open_browser: bool = True,
) -> Credentials:
    """Run the only interactive OAuth flow and store the resulting read-only token."""
    client_secrets_path = Path(client_secrets_path)
    _read_bounded_private_text(
        client_secrets_path,
        description="Gmail OAuth client file",
        maximum_bytes=_MAX_CLIENT_SECRETS_BYTES,
    )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secrets_path), scopes=list(GMAIL_SCOPES)
        )
        credentials = cast(
            Credentials,
            flow.run_local_server(
                host="127.0.0.1",
                port=0,
                open_browser=open_browser,
                authorization_prompt_message=(
                    "Open this URL to authorize read-only Gmail access: {url}"
                ),
                success_message="Gmail authorization completed. You may close this browser tab.",
            ),
        )
    except (GoogleAuthError, OSError, ValueError) as exc:
        raise GmailAuthError("Gmail authorization did not complete") from exc
    _require_exact_scopes(credentials)
    save_gmail_credentials(credentials, Path(token_path))
    return credentials


def load_gmail_credentials(token_path: Path) -> Credentials:
    """Load, validate, and refresh a previously authorized read-only Gmail token."""
    token_path = Path(token_path)
    serialized = _read_bounded_private_text(
        token_path, description="Gmail token file", maximum_bytes=_MAX_TOKEN_BYTES
    )
    _validate_token_document(serialized)
    try:
        credentials = Credentials.from_authorized_user_file(
            str(token_path), scopes=list(GMAIL_SCOPES)
        )
    except (GoogleAuthError, OSError, ValueError) as exc:
        raise GmailAuthError("stored Gmail credentials could not be loaded") from exc
    _require_exact_scopes(credentials)

    if credentials.valid:
        return credentials
    if not credentials.expired or not credentials.refresh_token:
        raise GmailAuthError("stored Gmail credentials are not usable; authorize Gmail again")
    try:
        credentials.refresh(Request())
    except GoogleAuthError as exc:
        raise GmailAuthError("stored Gmail credentials could not be refreshed") from exc
    if not credentials.valid:
        raise GmailAuthError("stored Gmail credentials remained invalid after refresh")
    _require_exact_scopes(credentials)
    save_gmail_credentials(credentials, token_path)
    return credentials


def redact_auth_exception(exc: BaseException) -> GmailAuthError:
    """Convert an unexpected adapter error without carrying secret-bearing text."""
    return GmailAuthError(f"Gmail credential operation failed ({type(exc).__name__})")


def credentials_summary(credentials: Credentials) -> dict[str, Any]:
    """Return only non-secret state suitable for a local health view."""
    return {
        "valid": bool(credentials.valid),
        "expired": bool(credentials.expired),
        "scope": GMAIL_READONLY_SCOPE,
    }
