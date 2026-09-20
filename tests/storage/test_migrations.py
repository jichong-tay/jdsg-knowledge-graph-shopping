from __future__ import annotations

import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shopping.storage.connection import connect_database
from shopping.storage.runtime import get_runtime_info
from shopping.storage.schema import MigrationError, assert_schema_current, migrate


def test_migration_is_repeatable_and_connection_pragmas_are_enabled(
    tmp_path: Path, settings
) -> None:
    first = migrate(settings.database_path, settings.migrations_dir)
    second = migrate(settings.database_path, settings.migrations_dir)

    assert first.current_version == 3
    assert second.current_version == 3
    assert second.applied_versions == ()
    connection = connect_database(settings.database_path)
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        expected_journal = "wal" if get_runtime_info().sqlite_wal_safe else "delete"
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == expected_journal
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


@pytest.mark.parametrize("filename", ["001_ingestion.sql", "002_conversations.sql"])
def test_modified_applied_migration_is_rejected(tmp_path: Path, settings, filename) -> None:
    copied = tmp_path / "migrations"
    shutil.copytree(settings.migrations_dir, copied)
    database = tmp_path / "checksum.sqlite3"
    migrate(database, copied)
    migration = copied / filename
    migration.write_text(migration.read_text() + "\n-- changed\n")

    with pytest.raises(MigrationError, match="changed after it was recorded"):
        migrate(database, copied)


def test_failed_migration_leaves_dirty_marker(tmp_path: Path) -> None:
    migrations = tmp_path / "bad-migrations"
    migrations.mkdir()
    (migrations / "001_bad.sql").write_text("CREATE TABLE broken (id INTEGER, );\n")
    database = tmp_path / "dirty.sqlite3"

    with pytest.raises(MigrationError, match="failed"):
        migrate(database, migrations)
    with pytest.raises(MigrationError, match="marked dirty"):
        migrate(database, migrations)


def test_newer_database_schema_is_rejected(settings) -> None:
    connection = connect_database(settings.database_path)
    try:
        connection.execute(
            """
            INSERT INTO schema_migrations
                (version, name, checksum, started_at, applied_at, is_dirty)
            VALUES (999, 'future', 'test', 'now', 'now', 0)
            """
        )
    finally:
        connection.close()

    with pytest.raises(MigrationError, match="not supported by this code: 999"):
        migrate(settings.database_path, settings.migrations_dir)


def test_foreign_keys_reject_invalid_rows(settings) -> None:
    connection = connect_database(settings.database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO orders (retailer_id, external_order_id, created_at)
                VALUES (999, 'x', 'now')
                """
            )
    finally:
        connection.close()


def test_connect_database_refuses_to_create_a_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"

    with pytest.raises(FileNotFoundError):
        connect_database(missing)
    assert not missing.exists()


def test_connect_database_create_flag_creates_a_new_database(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.sqlite3"

    connection = connect_database(fresh, create=True)
    connection.close()

    assert fresh.exists()


def test_concurrent_migration_is_serialized(tmp_path: Path, settings) -> None:
    database = tmp_path / "concurrent.sqlite3"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: migrate(database, settings.migrations_dir),
                range(2),
            )
        )

    assert sorted(result.applied_versions for result in results) == [(), (1, 2, 3)]
    assert assert_schema_current(database, settings.migrations_dir) == 3


def test_schema_check_does_not_initialize_database(tmp_path: Path, settings) -> None:
    database = tmp_path / "not-created.sqlite3"

    with pytest.raises(MigrationError, match="not initialized"):
        assert_schema_current(database, settings.migrations_dir)

    assert not database.exists()


def test_conversation_migration_preserves_existing_ingestion(settings, fixture_dir, tmp_path):
    from dataclasses import replace

    from shopping.ingestion.pipeline import import_eml
    from shopping.purchases.queries import count_current_orders

    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    shutil.copy(settings.migrations_dir / "001_ingestion.sql", old_migrations)
    shutil.copy(settings.migrations_dir / "002_conversations.sql", old_migrations)
    old = replace(
        settings, database_path=tmp_path / "upgrade.sqlite3", migrations_dir=old_migrations
    )
    migrate(old.database_path, old.migrations_dir)
    import_eml(fixture_dir / "fairprice_order_minimal.eml", old)
    connection = connect_database(old.database_path)
    try:
        connection.execute("INSERT INTO conversation_keys (id) VALUES ('conversation-1')")
        connection.execute(
            "INSERT INTO conversations (id,title,endpoint,model,created_at,activity_at) "
            "VALUES ('conversation-1','Saved','chat','synthetic',"
            "'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(MigrationError, match="behind"):
        assert_schema_current(old.database_path, settings.migrations_dir)
    upgraded = migrate(old.database_path, settings.migrations_dir)
    assert upgraded.applied_versions == (3,)
    assert count_current_orders(old.database_path) == 1
    connection = connect_database(old.database_path)
    try:
        assert (
            connection.execute(
                "SELECT title FROM conversations WHERE id='conversation-1'"
            ).fetchone()[0]
            == "Saved"
        )
        assert connection.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
    finally:
        connection.close()
    assert assert_schema_current(old.database_path, settings.migrations_dir) == 3
    with pytest.raises(MigrationError, match="newer"):
        assert_schema_current(old.database_path, old_migrations)


def test_failed_additive_migration_can_restore_verified_previous_database(
    settings, fixture_dir, tmp_path, sqlite_backup_module
):
    from dataclasses import replace

    from shopping.ingestion.pipeline import import_eml
    from shopping.purchases.queries import count_current_orders

    old_dir = tmp_path / "old-schema"
    old_dir.mkdir()
    shutil.copy(settings.migrations_dir / "001_ingestion.sql", old_dir)
    old = replace(settings, database_path=tmp_path / "old.sqlite3", migrations_dir=old_dir)
    migrate(old.database_path, old_dir)
    import_eml(fixture_dir / "fairprice_order_minimal.eml", old)
    backup = tmp_path / "verified.sqlite3"
    sqlite_backup_module.create_verified_backup(old.database_path, backup)
    broken_dir = tmp_path / "broken-schema"
    shutil.copytree(settings.migrations_dir, broken_dir)
    migration = broken_dir / "002_conversations.sql"
    migration.write_text(migration.read_text() + "\nINVALID SQL;\n")
    with pytest.raises(MigrationError, match="failed"):
        migrate(old.database_path, broken_dir)
    with pytest.raises(MigrationError, match="dirty"):
        assert_schema_current(old.database_path, broken_dir)
    # A separate restored file avoids copying over an open database or WAL sidecars.
    restored = tmp_path / "restored.sqlite3"
    sqlite_backup_module.create_verified_backup(backup, restored)
    assert assert_schema_current(restored, old_dir) == 1
    assert count_current_orders(restored) == 1
    assert migrate(restored, settings.migrations_dir).applied_versions == (2, 3)
