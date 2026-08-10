"""Create and verify one SQLite online backup for the deployment helper."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def create_verified_backup(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("backup source and destination must differ")

    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    with (
        sqlite3.connect(source_uri, uri=True) as source_connection,
        sqlite3.connect(destination) as destination_connection,
    ):
        source_connection.backup(destination_connection)
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError("SQLite backup failed its integrity check")
        foreign_key_errors = destination_connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError("SQLite backup failed its foreign-key check")
        migration_table = destination_connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """
        ).fetchone()
        if migration_table is None:
            raise RuntimeError("SQLite source is not a migrated shopping database")
        migration_count, dirty_count = destination_connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(is_dirty), 0)
            FROM schema_migrations
            """
        ).fetchone()
        if migration_count == 0 or dirty_count:
            raise RuntimeError("SQLite source has an incomplete or dirty migration state")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        raise SystemExit("usage: sqlite_backup.py SOURCE DESTINATION")
    create_verified_backup(Path(arguments[0]), Path(arguments[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
