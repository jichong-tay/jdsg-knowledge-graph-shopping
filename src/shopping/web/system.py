from __future__ import annotations

from fasthtml.common import (
    Div,
)
from starlette.requests import Request
from stitchyard.ui import (
    PageFrame,
    PageHeader,
    Panel,
    SectionHeader,
)

from shopping.config import Settings
from shopping.storage.runtime import RuntimeInfo, get_runtime_info
from shopping.storage.schema import current_schema_version
from shopping.web.layout import _definition_rows, _display_datetime, _page_response
from shopping.web.queries import system_snapshot


def _system_health_region(settings: Settings, runtime: RuntimeInfo):
    current_version, migration_dirty = current_schema_version(settings.database_path)
    snapshot = system_snapshot(settings.database_path)
    counts = snapshot["ingestion"]
    sync_states = snapshot["gmail_sync"]
    if sync_states:
        sync_errors = [sync["last_error"] for sync in sync_states if sync["last_error_at"]]
        sync_successes = [
            sync["last_success_at"] for sync in sync_states if sync["last_success_at"]
        ]
        sync_rows = [
            ("Connections", str(len(sync_states))),
            ("Needs attention", str(len(sync_errors))),
            (
                "Latest success",
                _display_datetime(max(sync_successes) if sync_successes else None),
            ),
            (
                "Current errors",
                ", ".join(sorted(set(sync_errors))) if sync_errors else "—",
            ),
            (
                "Updated",
                _display_datetime(max(sync["updated_at"] for sync in sync_states)),
            ),
        ]
    else:
        sync_rows = [("State", "Not configured")]
    return Div(
        Panel(
            SectionHeader("Runtime", "Compatibility and database safety"),
            _definition_rows(
                [
                    ("Environment", settings.environment),
                    ("Python", runtime.python_version),
                    ("SQLite", runtime.sqlite_version),
                    ("WAL safety", "Ready" if runtime.sqlite_wal_safe else "Development only"),
                    ("Schema", f"v{current_version}"),
                    ("Migration", "Dirty" if migration_dirty else "Current"),
                ]
            ),
        ),
        Panel(
            SectionHeader("Ingestion", "Archived source parse states"),
            _definition_rows(
                [
                    (status.replace("_", " ").title(), str(counts.get(status, 0)))
                    for status in ("parsed", "needs_review", "failed", "pending", "ignored")
                ]
            ),
        ),
        Panel(
            SectionHeader("Gmail sync", "Current persisted state; account hidden"),
            _definition_rows(sync_rows),
        ),
        Panel(
            SectionHeader(
                "Product normalization",
                "Review backlog; provisional parser matches are informational",
            ),
            _definition_rows(
                [
                    ("Provisional", str(snapshot["normalization"]["provisional"])),
                    ("Rejected", str(snapshot["normalization"]["rejected"])),
                    (
                        "Unreviewed aliases",
                        str(snapshot["normalization"]["unreviewed_aliases"]),
                    ),
                ]
            ),
        ),
        id="system-health-region",
        cls="system-grid",
        hx_get="/fragments/system-health",
        hx_trigger="every 30s [document.visibilityState === 'visible']",
        hx_swap="outerHTML",
    )


def register_system(app, settings: Settings) -> None:
    @app.get("/system")  # pyright: ignore[reportAttributeAccessIssue]
    def system_page(request: Request):
        current_runtime = get_runtime_info()
        content = PageFrame(
            PageHeader(
                "System health",
                "Current runtime and ingestion evidence, without raw household data.",
                eyebrow="System",
                tone="amber" if not current_runtime.sqlite_wal_safe else "neutral",
            ),
            _system_health_region(settings, current_runtime),
        )
        return _page_response(
            request,
            settings,
            title="System",
            eyebrow="Operations",
            current_path="/system",
            content=content,
        )

    @app.get("/fragments/system-health")  # pyright: ignore[reportAttributeAccessIssue]
    def system_health_fragment():
        return _system_health_region(settings, get_runtime_info())
