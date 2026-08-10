"""Application configuration with safe local defaults."""

from __future__ import annotations

import ipaddress
import os
import stat
from dataclasses import dataclass, replace
from pathlib import Path

_ENVIRONMENTS = frozenset({"development", "production"})


def _validate_environment(value: str) -> str:
    if value not in _ENVIRONMENTS:
        allowed = ", ".join(sorted(_ENVIRONMENTS))
        raise ValueError(f"SHOPPING_ENV must be one of: {allowed}")
    return value


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _configured_path(name: str, default: Path, *, require_absolute: bool) -> Path:
    raw = os.environ.get(name)
    candidate = Path(raw).expanduser() if raw is not None else default
    if require_absolute and not candidate.is_absolute():
        raise ValueError(f"{name} must be an absolute path in production")
    return candidate.resolve()


def _ensure_private_directory(path: Path) -> None:
    """Create path privately, or refuse a pre-existing directory that isn't already."""
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ValueError(
                f"{path} already exists with permissions {oct(mode)}; "
                "refusing to reuse a directory that is not already private"
            )
        return
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


@dataclass(frozen=True, slots=True)
class Settings:
    """Filesystem and server settings.

    Secrets are intentionally absent from the first implementation slice.
    """

    environment: str
    data_dir: Path
    database_path: Path
    raw_email_dir: Path
    migrations_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    allow_non_loopback: bool = False
    allow_synthetic_fixtures: bool = False

    def __post_init__(self) -> None:
        _validate_environment(self.environment)

    @property
    def enforce_safe_sqlite(self) -> bool:
        return self.environment == "production"

    def with_database(self, database_path: Path) -> Settings:
        expanded = database_path.expanduser()
        if self.enforce_safe_sqlite and not expanded.is_absolute():
            raise ValueError("database override must be an absolute path in production")
        return replace(self, database_path=expanded.resolve())

    def validate_bind_host(self, host: str | None = None) -> str:
        candidate = host or self.host
        try:
            is_loopback = ipaddress.ip_address(candidate).is_loopback
        except ValueError:
            is_loopback = candidate.casefold() == "localhost"
        if not is_loopback and not self.allow_non_loopback:
            raise ValueError(
                f"Refusing non-loopback bind {candidate!r}; use Tailscale Serve over localhost"
            )
        return candidate

    def prepare_database_directory(self) -> None:
        _ensure_private_directory(self.database_path.parent)

    def prepare_private_directories(self) -> None:
        _ensure_private_directory(self.data_dir)
        self.prepare_database_directory()
        _ensure_private_directory(self.raw_email_dir)


def load_settings() -> Settings:
    root = _project_root()
    environment = _validate_environment(os.environ.get("SHOPPING_ENV", "development"))
    production = environment == "production"
    if production and os.environ.get("SHOPPING_DATA_DIR") is None:
        raise ValueError("SHOPPING_DATA_DIR is required in production")
    data_dir = _configured_path(
        "SHOPPING_DATA_DIR", Path.cwd() / "data", require_absolute=production
    )
    database_path = _configured_path(
        "SHOPPING_DATABASE_PATH", data_dir / "shopping.sqlite3", require_absolute=production
    )
    raw_email_dir = _configured_path(
        "SHOPPING_RAW_EMAIL_DIR", data_dir / "raw-email", require_absolute=production
    )
    return Settings(
        environment=environment,
        data_dir=data_dir,
        database_path=database_path,
        raw_email_dir=raw_email_dir,
        migrations_dir=root / "app" / "migrations",
        host=os.environ.get("SHOPPING_HOST", "127.0.0.1"),
        port=int(os.environ.get("SHOPPING_PORT", "8000")),
        allow_non_loopback=os.environ.get("SHOPPING_ALLOW_NON_LOOPBACK", "false").casefold()
        in {"1", "true", "yes"},
    )
