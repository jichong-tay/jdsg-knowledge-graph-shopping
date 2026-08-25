from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path

import pytest

from app.cli import main
from app.config import Settings, load_settings
from app.email.parsers import UnsupportedEmailError


def test_server_bind_defaults_to_loopback(settings) -> None:
    assert settings.validate_bind_host() == "127.0.0.1"
    assert settings.validate_bind_host("localhost") == "localhost"


def test_non_loopback_bind_requires_explicit_override(settings) -> None:
    with pytest.raises(ValueError, match="Refusing non-loopback"):
        settings.validate_bind_host("0.0.0.0")

    exposed = replace(settings, allow_non_loopback=True)
    assert exposed.validate_bind_host("0.0.0.0") == "0.0.0.0"


def test_production_requires_an_absolute_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHOPPING_ENV", "production")
    monkeypatch.delenv("SHOPPING_DATA_DIR", raising=False)
    with pytest.raises(ValueError, match="required"):
        load_settings()

    monkeypatch.setenv("SHOPPING_DATA_DIR", "relative-data")
    with pytest.raises(ValueError, match="absolute"):
        load_settings()

    data_dir = tmp_path / "production-data"
    monkeypatch.setenv("SHOPPING_DATA_DIR", str(data_dir))
    production = load_settings()
    assert production.environment == "production"
    assert production.data_dir == data_dir
    with pytest.raises(ValueError, match="absolute"):
        production.with_database(Path("relative.sqlite3"))


@pytest.mark.parametrize("environment", ["test", "staging", "prodution", " Production "])
def test_unknown_environment_is_rejected(
    settings, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("SHOPPING_ENV", environment)
    with pytest.raises(
        ValueError,
        match="SHOPPING_ENV must be one of: development, production",
    ):
        load_settings()

    with pytest.raises(ValueError, match="SHOPPING_ENV must be one of"):
        replace(settings, environment="staging")


def test_explicit_migration_database_does_not_create_default_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHOPPING_ENV", "development")
    monkeypatch.delenv("SHOPPING_DATA_DIR", raising=False)
    monkeypatch.delenv("SHOPPING_DATABASE_PATH", raising=False)
    monkeypatch.delenv("SHOPPING_RAW_EMAIL_DIR", raising=False)
    database = tmp_path / "state" / "shopping.sqlite3"

    assert main(["migrate", "--database", str(database)]) == 0
    assert database.exists()
    assert not (tmp_path / "data").exists()


def test_synthetic_sender_requires_explicit_cli_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_dir: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHOPPING_ENV", "development")
    database = tmp_path / "shopping.sqlite3"
    fixture = fixture_dir / "fairprice_order_minimal.eml"
    assert main(["migrate", "--database", str(database)]) == 0

    with pytest.raises(UnsupportedEmailError):
        main(["import-eml", str(fixture), "--database", str(database)])

    assert (
        main(
            [
                "import-eml",
                str(fixture),
                "--database",
                str(database),
                "--synthetic-fixture",
            ]
        )
        == 0
    )


def _settings_for(data_dir: Path, migrations_dir: Path) -> Settings:
    return Settings(
        environment="development",
        data_dir=data_dir,
        database_path=data_dir / "shopping.sqlite3",
        raw_email_dir=data_dir / "raw-email",
        migrations_dir=migrations_dir,
    )


def test_prepare_private_directories_refuses_preexisting_shared_directory(
    tmp_path: Path, settings: Settings
) -> None:
    value = _settings_for(tmp_path / "shared", settings.migrations_dir)
    value.data_dir.mkdir(parents=True)
    value.data_dir.chmod(0o755)

    with pytest.raises(ValueError, match="refusing to reuse"):
        value.prepare_private_directories()
    assert stat.S_IMODE(value.data_dir.stat().st_mode) == 0o755


def test_prepare_private_directories_accepts_already_private_directory(
    tmp_path: Path, settings: Settings
) -> None:
    value = _settings_for(tmp_path / "private", settings.migrations_dir)
    value.data_dir.mkdir(parents=True)
    value.data_dir.chmod(0o700)

    value.prepare_private_directories()

    assert value.raw_email_dir.is_dir()
    assert stat.S_IMODE(value.raw_email_dir.stat().st_mode) == 0o700


def test_gmail_private_paths_are_derived_from_data_directory(
    tmp_path: Path, settings: Settings
) -> None:
    value = _settings_for(tmp_path / "private", settings.migrations_dir)

    assert value.gmail_dir == value.data_dir / "gmail"
    assert value.gmail_client_secrets_path == value.data_dir / "gmail" / "client_secret.json"
    assert value.gmail_token_path == value.data_dir / "gmail" / "token.json"

    value.prepare_gmail_directory()

    assert value.gmail_dir.is_dir()
    assert stat.S_IMODE(value.gmail_dir.stat().st_mode) == 0o700
