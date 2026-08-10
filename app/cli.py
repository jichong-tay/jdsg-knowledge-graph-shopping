"""Command-line interface used in development and deployment."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import uvicorn

from app.config import Settings, load_settings
from app.db.migrations import assert_schema_current, migrate
from app.ingestion import import_eml
from app.runtime import assert_supported_runtime
from app.web import create_app


def _settings_with_database(settings: Settings, database: Path | None) -> Settings:
    return settings if database is None else settings.with_database(database)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shopping", description="Local shopping intelligence")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate_parser = commands.add_parser("migrate", help="Apply pending database migrations")
    migrate_parser.add_argument("--database", type=Path)

    import_parser = commands.add_parser("import-eml", help="Archive and import one .eml file")
    import_parser.add_argument("path", type=Path)
    import_parser.add_argument("--database", type=Path)
    import_parser.add_argument(
        "--synthetic-fixture",
        action="store_true",
        help="Allow the reserved test sender domain (never valid in production)",
    )

    serve_parser = commands.add_parser("serve", help="Run the local FastHTML application")
    serve_parser.add_argument("--host")
    serve_parser.add_argument("--port", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = load_settings()
    if arguments.command == "migrate":
        settings = _settings_with_database(settings, arguments.database)
        settings.prepare_database_directory()
        assert_supported_runtime(enforce_safe_sqlite=settings.enforce_safe_sqlite)
        result = migrate(settings.database_path, settings.migrations_dir)
        applied = ", ".join(str(version) for version in result.applied_versions) or "none"
        print(f"schema={result.current_version} applied={applied}")
        return 0
    if arguments.command == "import-eml":
        settings = _settings_with_database(settings, arguments.database)
        if arguments.synthetic_fixture:
            if settings.enforce_safe_sqlite:
                raise ValueError("synthetic fixtures are disabled in production")
            settings = replace(settings, allow_synthetic_fixtures=True)
        assert_supported_runtime(enforce_safe_sqlite=settings.enforce_safe_sqlite)
        assert_schema_current(settings.database_path, settings.migrations_dir)
        result = import_eml(arguments.path, settings)
        print(result.model_dump_json())
        return 0
    if arguments.command == "serve":
        host = settings.validate_bind_host(arguments.host)
        port = arguments.port or settings.port
        uvicorn.run(create_app(settings), host=host, port=port, workers=1)
        return 0
    raise AssertionError(f"unhandled command: {arguments.command}")
