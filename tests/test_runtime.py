from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.db.connection
from app.db.connection import connect_database
from app.runtime import sqlite_has_wal_reset_fix


@pytest.mark.parametrize(
    "version",
    ((3, 51, 3), (3, 52, 0), (3, 50, 7), (3, 44, 6)),
)
def test_wal_fixed_sqlite_versions_are_accepted(version: tuple[int, ...]) -> None:
    assert sqlite_has_wal_reset_fix(version)


@pytest.mark.parametrize(
    "version",
    ((3, 51, 2), (3, 50, 6), (3, 49, 9), (3, 44, 5)),
)
def test_affected_sqlite_versions_are_rejected(version: tuple[int, ...]) -> None:
    assert not sqlite_has_wal_reset_fix(version)


def test_affected_runtime_uses_rollback_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        app.db.connection,
        "get_runtime_info",
        lambda: SimpleNamespace(sqlite_wal_safe=False),
    )
    connection = connect_database(tmp_path / "rollback.sqlite3", create=True)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()
