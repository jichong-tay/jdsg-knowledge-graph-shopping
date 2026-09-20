from __future__ import annotations

from fasthtml.common import (
    JSONResponse,
)

from shopping.config import Settings
from shopping.storage.runtime import get_runtime_info
from shopping.storage.schema import current_schema_version
from shopping.web.queries import ingestion_counts


def register_health(app, settings: Settings) -> None:
    @app.get("/api/health")  # pyright: ignore[reportAttributeAccessIssue]
    def health():
        current_version, migration_dirty = current_schema_version(settings.database_path)
        current_runtime = get_runtime_info()
        status = "ok" if current_runtime.sqlite_wal_safe else "degraded"
        return JSONResponse(
            {
                "status": status,
                "ready": (
                    current_runtime.python_supported
                    and current_runtime.sqlite_wal_safe
                    and not migration_dirty
                ),
                "environment": settings.environment,
                "runtime": current_runtime.as_dict(),
                "database": {
                    "schema_version": current_version,
                    "migration_dirty": migration_dirty,
                    "ingestion": ingestion_counts(settings.database_path),
                },
            }
        )
