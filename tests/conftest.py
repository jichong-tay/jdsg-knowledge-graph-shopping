from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db.migrations import migrate


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "email"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    value = Settings(
        environment="development",
        data_dir=data_dir,
        database_path=data_dir / "shopping.sqlite3",
        raw_email_dir=data_dir / "raw-email",
        migrations_dir=Path(__file__).parent.parent / "app" / "migrations",
        allow_synthetic_fixtures=True,
    )
    value.prepare_private_directories()
    migrate(value.database_path, value.migrations_dir)
    return value
