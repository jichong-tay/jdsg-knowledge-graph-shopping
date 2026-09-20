"""Small checksum-aware SQL migration runner."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shopping.storage.connection import connect_database, transaction

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{3,})_(?P<name>[a-z0-9_]+)\.sql$")
_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version       INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    checksum      TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    applied_at    TEXT,
    is_dirty      INTEGER NOT NULL DEFAULT 1 CHECK (is_dirty IN (0,1)),
    CHECK ((is_dirty = 1 AND applied_at IS NULL) OR
           (is_dirty = 0 AND applied_at IS NOT NULL))
) STRICT
"""


class MigrationError(RuntimeError):
    """Raised when migrations are incomplete, modified, or invalid."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    checksum: str
    sql: str
    path: Path


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied_versions: tuple[int, ...]
    current_version: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def discover_migrations(migrations_dir: Path) -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    seen_versions: set[int] = set()
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"Invalid migration filename: {path.name}")
        version = int(match.group("version"))
        if version in seen_versions:
            raise MigrationError(f"Duplicate migration version: {version}")
        seen_versions.add(version)
        raw = path.read_bytes()
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                checksum=hashlib.sha256(raw).hexdigest(),
                sql=raw.decode("utf-8"),
                path=path,
            )
        )
    if not migrations:
        raise MigrationError(f"No migrations found in {migrations_dir}")
    return tuple(migrations)


def _statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise MigrationError("Migration ends with an incomplete SQL statement")
    return tuple(statements)


@contextmanager
def _migration_lock(database_path: Path) -> Generator[None]:
    database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = database_path.with_name(f".{database_path.name}.migrate.lock")
    with lock_path.open("a+b") as lock_file:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def migrate(database_path: Path, migrations_dir: Path) -> MigrationResult:
    migrations = discover_migrations(migrations_dir)
    with _migration_lock(database_path):
        return _migrate_locked(database_path, migrations)


def _migrate_locked(database_path: Path, migrations: tuple[Migration, ...]) -> MigrationResult:
    connection = connect_database(database_path, create=True)
    applied: list[int] = []
    try:
        connection.execute(_LEDGER_SQL)
        known_versions = {migration.version for migration in migrations}
        recorded_versions = {
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        unknown_versions = recorded_versions - known_versions
        if unknown_versions:
            versions = ", ".join(str(version) for version in sorted(unknown_versions))
            raise MigrationError(
                f"Database contains migration version(s) not supported by this code: {versions}"
            )
        for migration in migrations:
            existing = connection.execute(
                "SELECT checksum, is_dirty FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if existing is not None:
                if existing["checksum"] != migration.checksum:
                    raise MigrationError(
                        f"Migration {migration.path.name} changed after it was recorded"
                    )
                if existing["is_dirty"]:
                    raise MigrationError(
                        f"Migration {migration.path.name} is marked dirty; restore before retrying"
                    )
                continue

            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO schema_migrations
                        (version, name, checksum, started_at, applied_at, is_dirty)
                    VALUES (?, ?, ?, ?, NULL, 1)
                    """,
                    (migration.version, migration.name, migration.checksum, _utc_now()),
                )

            try:
                with transaction(connection):
                    for statement in _statements(migration.sql):
                        connection.execute(statement)
                    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if integrity != "ok":
                        raise MigrationError(f"SQLite integrity check failed: {integrity}")
                    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if foreign_key_errors:
                        raise MigrationError(
                            f"SQLite foreign-key check failed: {foreign_key_errors!r}"
                        )
                    connection.execute(
                        """
                        UPDATE schema_migrations
                        SET applied_at = ?, is_dirty = 0
                        WHERE version = ?
                        """,
                        (_utc_now(), migration.version),
                    )
            except sqlite3.Error as error:
                raise MigrationError(f"Migration {migration.path.name} failed: {error}") from error
            applied.append(migration.version)

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise MigrationError(f"SQLite integrity check failed: {integrity}")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise MigrationError(f"SQLite foreign-key check failed: {foreign_key_errors!r}")
        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations WHERE is_dirty = 0"
        ).fetchone()[0]
        return MigrationResult(tuple(applied), int(current))
    finally:
        connection.close()


def current_schema_version(database_path: Path) -> tuple[int, bool]:
    if not database_path.exists():
        return 0, False
    connection = connect_database(database_path)
    try:
        ledger = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if ledger is None:
            return 0, False
        row = connection.execute(
            """
            SELECT COALESCE(MAX(CASE WHEN is_dirty = 0 THEN version END), 0),
                   COALESCE(MAX(is_dirty), 0)
            FROM schema_migrations
            """
        ).fetchone()
        return int(row[0]), bool(row[1])
    finally:
        connection.close()


def assert_schema_current(database_path: Path, migrations_dir: Path) -> int:
    """Verify the schema without applying or modifying any migration."""

    migrations = discover_migrations(migrations_dir)
    if not database_path.exists():
        raise MigrationError("Database is not initialized; run `shopping migrate` first")
    connection = connect_database(database_path)
    try:
        ledger = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if ledger is None:
            raise MigrationError("Migration ledger is missing; run `shopping migrate` first")
        rows = connection.execute(
            "SELECT version, checksum, is_dirty FROM schema_migrations"
        ).fetchall()
        recorded = {int(row["version"]): row for row in rows}
        expected = {migration.version: migration for migration in migrations}
        unknown = set(recorded) - set(expected)
        if unknown:
            versions = ", ".join(str(version) for version in sorted(unknown))
            raise MigrationError(f"Database schema is newer than this code: {versions}")
        for version, migration in expected.items():
            row = recorded.get(version)
            if row is None:
                raise MigrationError(
                    f"Database schema is behind at migration {version}; run `shopping migrate`"
                )
            if row["checksum"] != migration.checksum:
                raise MigrationError(f"Migration {migration.path.name} checksum does not match")
            if row["is_dirty"]:
                raise MigrationError(f"Migration {migration.path.name} is marked dirty")
        return max(expected)
    finally:
        connection.close()
