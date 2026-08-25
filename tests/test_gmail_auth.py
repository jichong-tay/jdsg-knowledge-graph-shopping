from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from app.gmail import auth


class FakeCredentials:
    def __init__(
        self,
        *,
        scopes: tuple[str, ...] = auth.GMAIL_SCOPES,
        valid: bool = True,
        expired: bool = False,
        refresh_token: str | None = "opaque-refresh-value",
    ) -> None:
        self.scopes = scopes
        self.granted_scopes: tuple[str, ...] | None = scopes
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self.refreshed = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "token": "opaque-access-value",
                "refresh_token": self.refresh_token,
                "client_id": "synthetic-client-id",
                "client_secret": "synthetic-client-secret",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": list(self.scopes),
            }
        )

    def refresh(self, request: object) -> None:
        del request
        self.refreshed = True
        self.valid = True
        self.expired = False


def _private_file(path: Path, content: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_authorize_requests_only_readonly_scope_and_saves_private_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_file = _private_file(tmp_path / "oauth" / "credentials.json")
    token_path = tmp_path / "tokens" / "gmail-token.json"
    credentials = FakeCredentials()
    captured: dict[str, Any] = {}

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, path: str, *, scopes: list[str]) -> FakeFlow:
            captured["client_path"] = path
            captured["scopes"] = scopes
            return cls()

        def run_local_server(self, **kwargs: Any) -> FakeCredentials:
            captured["server"] = kwargs
            return credentials

    monkeypatch.setattr(auth, "InstalledAppFlow", FakeFlow)

    returned = auth.authorize_gmail(client_file, token_path)

    assert returned is credentials
    assert captured["client_path"] == str(client_file)
    assert captured["scopes"] == [auth.GMAIL_READONLY_SCOPE]
    assert captured["server"]["host"] == "127.0.0.1"
    assert captured["server"]["port"] == 0
    assert captured["server"]["open_browser"] is True
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert json.loads(token_path.read_text(encoding="utf-8"))["scopes"] == [
        auth.GMAIL_READONLY_SCOPE
    ]
    assert not tuple(token_path.parent.glob(f".{token_path.name}.*.tmp"))


@pytest.mark.parametrize("mode", [0o604, 0o640, 0o644, 0o660])
def test_authorize_rejects_insecure_client_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    client_file = _private_file(tmp_path / "credentials.json")
    client_file.chmod(mode)

    class FlowMustNotRun:
        @classmethod
        def from_client_secrets_file(cls, path: str, *, scopes: list[str]) -> None:
            del path, scopes
            raise AssertionError("interactive flow must not run")

    monkeypatch.setattr(auth, "InstalledAppFlow", FlowMustNotRun)
    with pytest.raises(auth.GmailAuthError, match="group or other"):
        auth.authorize_gmail(client_file, tmp_path / "token.json")


def test_authorize_rejects_client_file_symlink(tmp_path: Path) -> None:
    client_file = _private_file(tmp_path / "real-client.json")
    link = tmp_path / "client-link.json"
    link.symlink_to(client_file)

    with pytest.raises(auth.GmailAuthError, match="symlink"):
        auth.authorize_gmail(link, tmp_path / "token.json")


def test_save_refuses_to_replace_a_token_symlink(tmp_path: Path) -> None:
    target = _private_file(tmp_path / "target.json", "unchanged")
    token_link = tmp_path / "token.json"
    token_link.symlink_to(target)

    with pytest.raises(auth.GmailAuthError, match="symlink"):
        auth.save_gmail_credentials(FakeCredentials(), token_link)  # type: ignore[arg-type]
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_save_rejects_scopes_broader_than_readonly(tmp_path: Path) -> None:
    credentials = FakeCredentials(scopes=(auth.GMAIL_READONLY_SCOPE, "mail.google.com"))

    with pytest.raises(auth.GmailAuthError, match="exactly"):
        auth.save_gmail_credentials(credentials, tmp_path / "token.json")  # type: ignore[arg-type]


def test_load_refreshes_expired_token_and_persists_it_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = _private_file(
        tmp_path / "token.json",
        json.dumps({"scopes": [auth.GMAIL_READONLY_SCOPE]}),
    )
    credentials = FakeCredentials(valid=False, expired=True)

    class FakeCredentialsType:
        @staticmethod
        def from_authorized_user_file(path: str, *, scopes: list[str]) -> FakeCredentials:
            assert path == str(token_path)
            assert scopes == [auth.GMAIL_READONLY_SCOPE]
            return credentials

    monkeypatch.setattr(auth, "Credentials", FakeCredentialsType)
    monkeypatch.setattr(auth, "Request", object)

    returned = auth.load_gmail_credentials(token_path)

    assert returned is credentials
    assert credentials.refreshed is True
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert json.loads(token_path.read_text(encoding="utf-8"))["token"] == "opaque-access-value"


def test_load_never_reads_insecure_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_path = _private_file(tmp_path / "token.json")
    token_path.chmod(0o644)

    class CredentialsMustNotLoad:
        @staticmethod
        def from_authorized_user_file(path: str, *, scopes: list[str]) -> None:
            del path, scopes
            raise AssertionError("insecure token must not be read")

    monkeypatch.setattr(auth, "Credentials", CredentialsMustNotLoad)
    with pytest.raises(auth.GmailAuthError, match="group or other"):
        auth.load_gmail_credentials(token_path)


def test_load_requires_reauthorization_when_refresh_is_impossible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = _private_file(
        tmp_path / "token.json",
        json.dumps({"scopes": [auth.GMAIL_READONLY_SCOPE]}),
    )
    credentials = FakeCredentials(valid=False, expired=True, refresh_token=None)

    class FakeCredentialsType:
        @staticmethod
        def from_authorized_user_file(path: str, *, scopes: list[str]) -> FakeCredentials:
            del path, scopes
            return credentials

    monkeypatch.setattr(auth, "Credentials", FakeCredentialsType)
    with pytest.raises(auth.GmailAuthError, match="authorize Gmail again"):
        auth.load_gmail_credentials(token_path)


def test_load_rejects_stored_token_with_broader_scope_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = _private_file(
        tmp_path / "token.json",
        json.dumps({"scopes": [auth.GMAIL_READONLY_SCOPE, "mail.google.com"]}),
    )

    class CredentialsMustNotLoad:
        @staticmethod
        def from_authorized_user_file(path: str, *, scopes: list[str]) -> None:
            del path, scopes
            raise AssertionError("broadly scoped token must not be parsed")

    monkeypatch.setattr(auth, "Credentials", CredentialsMustNotLoad)
    with pytest.raises(auth.GmailAuthError, match="exactly"):
        auth.load_gmail_credentials(token_path)


def test_credentials_summary_contains_no_token_material() -> None:
    summary = auth.credentials_summary(FakeCredentials())  # type: ignore[arg-type]

    assert summary == {
        "valid": True,
        "expired": False,
        "scope": auth.GMAIL_READONLY_SCOPE,
    }
