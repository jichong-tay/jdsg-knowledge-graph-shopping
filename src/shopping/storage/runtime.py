"""Runtime compatibility checks reported through the health endpoint."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    python_version: str
    sqlite_version: str
    python_supported: bool
    sqlite_wal_safe: bool

    def as_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def sqlite_has_wal_reset_fix(version: tuple[int, ...]) -> bool:
    """Return whether SQLite includes the 2026 WAL-reset corruption fix."""

    padded = (*version, 0, 0, 0)[:3]
    if padded >= (3, 51, 3):
        return True
    if padded[:2] == (3, 50):
        return padded >= (3, 50, 7)
    if padded[:2] == (3, 44):
        return padded >= (3, 44, 6)
    return False


def get_runtime_info() -> RuntimeInfo:
    sqlite_version = tuple(int(part) for part in sqlite3.sqlite_version.split("."))
    return RuntimeInfo(
        python_version=sys.version.split()[0],
        sqlite_version=sqlite3.sqlite_version,
        python_supported=sys.version_info[:2] == (3, 14),
        sqlite_wal_safe=sqlite_has_wal_reset_fix(sqlite_version),
    )


def assert_supported_runtime(*, enforce_safe_sqlite: bool) -> RuntimeInfo:
    info = get_runtime_info()
    if not info.python_supported:
        raise RuntimeError(f"Python 3.14 is required; found {info.python_version}")
    if enforce_safe_sqlite and not info.sqlite_wal_safe:
        raise RuntimeError(
            "Production requires SQLite 3.51.3+, 3.50.7+, or the 3.44.6 backport; "
            f"found {info.sqlite_version}"
        )
    return info
