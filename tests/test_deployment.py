from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from deploy.sqlite_backup import create_verified_backup


def test_deployment_backup_is_complete_and_valid(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                is_dirty INTEGER NOT NULL
            )
            """
        )
        connection.execute("INSERT INTO schema_migrations VALUES (1, 0)")
        connection.execute("CREATE TABLE example (value TEXT NOT NULL)")
        connection.execute("INSERT INTO example VALUES ('preserved')")

    create_verified_backup(source, backup)

    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT value FROM example").fetchone()[0] == "preserved"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_deployment_backup_rejects_foreign_key_corruption(tmp_path: Path) -> None:
    source = tmp_path / "invalid.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                is_dirty INTEGER NOT NULL
            );
            INSERT INTO schema_migrations VALUES (1, 0);
            CREATE TABLE parent (id INTEGER PRIMARY KEY);
            CREATE TABLE child (parent_id INTEGER REFERENCES parent(id));
            INSERT INTO child VALUES (99);
            """
        )

    with pytest.raises(RuntimeError, match="foreign-key"):
        create_verified_backup(source, backup)


@pytest.mark.parametrize("dirty", [None, 1])
def test_deployment_backup_rejects_unmigrated_or_dirty_database(
    tmp_path: Path, dirty: int | None
) -> None:
    source = tmp_path / "invalid.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as connection:
        if dirty is not None:
            connection.execute(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    is_dirty INTEGER NOT NULL
                )
                """
            )
            connection.execute("INSERT INTO schema_migrations VALUES (1, ?)", (dirty,))

    with pytest.raises(RuntimeError, match=r"migrated|dirty"):
        create_verified_backup(source, backup)
