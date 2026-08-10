"""Short-lived SQLite connections configured consistently."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from app.runtime import get_runtime_info


def connect_database(database_path: Path, *, create: bool = False) -> sqlite3.Connection:
    if not create and not database_path.exists():
        raise FileNotFoundError(
            f"{database_path} does not exist; run `shopping migrate` to create it"
        )
    parent_existed = database_path.parent.exists()
    database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not parent_existed:
        database_path.parent.chmod(0o700)
    connection = sqlite3.connect(database_path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    journal_mode = "WAL" if get_runtime_info().sqlite_wal_safe else "DELETE"
    selected_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    if selected_mode.casefold() != journal_mode.casefold():
        selected_mode = str(
            connection.execute(f"PRAGMA journal_mode = {journal_mode}").fetchone()[0]
        )
    if selected_mode.casefold() != journal_mode.casefold():
        connection.close()
        raise RuntimeError(f"SQLite did not enter required {journal_mode} journal mode")
    if database_path.exists():
        os.chmod(database_path, 0o600)
    return connection


@contextmanager
def transaction(
    connection: sqlite3.Connection, *, immediate: bool = True
) -> Generator[sqlite3.Connection]:
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
