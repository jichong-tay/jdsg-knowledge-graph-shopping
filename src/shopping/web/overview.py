from __future__ import annotations

from fasthtml.common import (
    H2,
    Div,
    P,
    Span,
    Time,
)
from starlette.requests import Request
from stitchyard.ui import (
    EmptyState,
    Icon,
    PageFrame,
    PageHeader,
    Panel,
    RaisedPanel,
    SectionHeader,
)

from shopping.config import Settings
from shopping.purchases.queries import (
    list_orders,
    list_scheduled_deliveries,
)
from shopping.storage.runtime import RuntimeInfo, get_runtime_info
from shopping.web.layout import _display_datetime, _page_response, money, status_badge
from shopping.web.orders import _order_link, _orders_table
from shopping.web.queries import list_recent_sources, overview_snapshot


def _metric(label: str, value: str, note: str):
    return RaisedPanel(
        P(label, cls="metric-label"),
        P(value, cls="metric-number metric-value"),
        P(note, cls="metric-note"),
        cls="metric-card",
    )


def _attention_region(snapshot: dict, runtime: RuntimeInfo):
    warning = (
        Div(
            Icon("triangle-alert", "h-5 w-5 text-amber"),
            Div(
                H2("Development runtime requires attention"),
                P(
                    f"SQLite {runtime.sqlite_version} does not contain the required "
                    "production WAL fix. Production startup remains blocked."
                ),
            ),
            cls="attention-banner",
        )
        if not runtime.sqlite_wal_safe
        else None
    )
    attention_count = snapshot["attention_count"]
    if attention_count:
        attention = Div(
            Icon("circle-alert", "h-5 w-5 text-amber"),
            Div(
                H2(
                    f"{attention_count} condition"
                    f"{'s' if attention_count != 1 else ''} need attention"
                ),
                P("Open System to inspect parsing, sync, and data-quality evidence."),
            ),
            cls="attention-banner",
        )
    else:
        attention = Div(
            Icon("circle-check", "h-5 w-5 text-healthy"),
            Div(
                H2("No ingestion problems"),
                P("Archived sources have no current failure or review state."),
            ),
            cls="attention-banner",
        )
    return Div(
        warning,
        attention,
        id="attention-region",
        cls="attention-region",
        hx_get="/fragments/attention",
        hx_trigger="every 30s [document.visibilityState === 'visible']",
        hx_swap="outerHTML",
    )


def _scheduled_deliveries_panel(deliveries: list[dict]):
    if deliveries:
        body = Div(
            *(
                Div(
                    Div(
                        _order_link(
                            delivery,
                            delivery["external_order_id"],
                            cls="order-link mono",
                        ),
                        P(delivery["retailer_name"], cls="item-meta"),
                    ),
                    Div(
                        Time(
                            _display_datetime(delivery["delivery_at"]),
                            datetime=delivery["delivery_at"],
                            cls="mono",
                        ),
                        Span(
                            money(delivery["total_cents"], delivery["currency"]),
                            cls="money",
                        ),
                        cls="delivery-facts",
                    ),
                    cls="activity-row",
                )
                for delivery in deliveries
            )
        )
    else:
        body = EmptyState(
            "No future delivery timestamps",
            "Scheduled delivery facts will appear here when a current order provides them.",
            icon="calendar-check",
        )
    return Panel(
        SectionHeader(
            "Scheduled deliveries",
            "Future timestamps from current revisions; not fulfilment tracking",
        ),
        body,
    )


def _recent_ingestion_panel(sources: list[dict]):
    if sources:
        body = Div(
            *(
                Div(
                    Div(
                        P(
                            f"{source['source_kind'].title()} source",
                            cls="activity-title",
                        ),
                        P(
                            f"{source['sender_domain']} · SHA-256 {source['raw_hash_prefix']}…",
                            cls="activity-meta mono",
                        ),
                    ),
                    Div(
                        status_badge(source["parse_status"]),
                        Time(
                            _display_datetime(source["event_at"]),
                            datetime=source["event_at"],
                            cls="activity-time mono",
                        ),
                        cls="activity-facts",
                    ),
                    cls="activity-row",
                )
                for source in sources
            )
        )
    else:
        body = EmptyState(
            "No archived sources",
            "Recent deterministic ingestion activity will appear here.",
            icon="inbox",
        )
    return Panel(
        SectionHeader("Recent ingestion", "Privacy-minimised source evidence"),
        body,
    )


def register_overview(app, settings: Settings, runtime: RuntimeInfo) -> None:
    @app.get("/")  # pyright: ignore[reportAttributeAccessIssue]
    def dashboard(request: Request):
        snapshot = overview_snapshot(settings.database_path)
        orders = list_orders(settings.database_path, page_size=5)["items"]
        attention = _attention_region(snapshot, runtime)
        deliveries = list_scheduled_deliveries(settings.database_path)
        sources = list_recent_sources(settings.database_path)
        metrics = Div(
            _metric(
                "Current orders",
                str(snapshot["current_orders"]),
                "Latest factual revision per order",
            ),
            _metric(
                "Current item lines",
                str(snapshot["current_item_lines"]),
                "Across every current order revision",
            ),
            _metric(
                "Recorded order value",
                " · ".join(
                    money(item["total_cents"], item["currency"])
                    for item in snapshot["recorded_values"]
                )
                or "—",
                "Recorded value, not completed spend",
            ),
            _metric(
                "Archived messages",
                str(snapshot["archived_messages"]),
                "Exact raw sources retained",
            ),
            cls="dashboard-grid",
        )
        if orders:
            recent = Panel(
                SectionHeader("Latest orders", "Ordered by original source-event time"),
                Div(_orders_table(orders), cls="table-scroll"),
            )
        else:
            recent = Panel(
                EmptyState(
                    "No orders yet",
                    "Import the sanitised example to exercise the complete archive-to-order path.",
                    icon="shopping-basket",
                ),
                Div(
                    "uv run shopping import-eml "
                    "tests/fixtures/email/fairprice_order_minimal.eml --synthetic-fixture",
                    cls="empty-command mono",
                ),
            )
        content = PageFrame(
            PageHeader(
                "Shopping overview",
                "A precise view of archived sources and their current order facts.",
                eyebrow="Overview",
            ),
            attention,
            metrics,
            Div(
                _scheduled_deliveries_panel(deliveries),
                _recent_ingestion_panel(sources),
                cls="content-grid",
            ),
            recent,
            cls="space-y-4",
        )
        return _page_response(
            request,
            settings,
            title="Overview",
            eyebrow="Shopping",
            current_path="/",
            content=content,
        )

    @app.get("/fragments/attention")  # pyright: ignore[reportAttributeAccessIssue]
    def attention_fragment():
        return _attention_region(
            overview_snapshot(settings.database_path),
            get_runtime_info(),
        )
