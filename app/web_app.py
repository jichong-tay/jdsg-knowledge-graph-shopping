"""FastHTML application for exploring archived shopping facts."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fasthtml.common import (
    H2,
    A,
    Aside,
    Button,
    Dd,
    Details,
    Div,
    Dl,
    Dt,
    Form,
    JSONResponse,
    Li,
    P,
    Small,
    Span,
    Summary,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Time,
    Tr,
    Ul,
    fast_app,
)
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from stitchyard.ui import (
    EmptyState,
    Icon,
    PageFrame,
    PageHeader,
    Panel,
    RaisedPanel,
    SectionHeader,
    SelectField,
    TextField,
    UiButton,
)

from app.assistant.tools import dispatch_tool
from app.config import Settings
from app.db.migrations import assert_schema_current, current_schema_version
from app.db.repository import (
    get_current_order,
    ingestion_counts,
)
from app.runtime import RuntimeInfo, assert_supported_runtime, get_runtime_info
from app.web_queries import (
    get_order_history,
    list_orders,
    list_recent_sources,
    list_scheduled_deliveries,
    overview_snapshot,
    system_snapshot,
)
from app.web_ui import document, main_view, money, product_history, register_assets, status_badge

_STATIC_DIR = Path(__file__).with_name("static")
_DISPLAY_TIMEZONE = ZoneInfo("Asia/Singapore")


def _page_response(
    request: Request,
    settings: Settings,
    *,
    title: str,
    eyebrow: str,
    current_path: str,
    content,
):
    if request.headers.get("HX-Request") == "true":
        return main_view(title, eyebrow, content, environment=settings.environment)
    return document(
        title,
        eyebrow,
        content,
        current_path=current_path,
        environment=settings.environment,
    )


def _metric(label: str, value: str, note: str):
    return RaisedPanel(
        P(label, cls="metric-label"),
        P(value, cls="metric-number metric-value"),
        P(note, cls="metric-note"),
        cls="metric-card",
    )


def _display_datetime(value: str | None) -> str:
    if value is None:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.utcoffset() is None:
        return value
    return parsed.astimezone(_DISPLAY_TIMEZONE).strftime("%d %b %Y, %H:%M SGT")


def _order_link(order: dict, *children, cls: str, aria_label: str | None = None):
    canonical_url = f"/orders/{order['id']}"
    return A(
        *children,
        href=canonical_url,
        cls=cls,
        aria_label=aria_label,
        hx_get=f"{canonical_url}?view=drawer",
        hx_target="#drawer-root",
        hx_swap="innerHTML",
        hx_push_url=canonical_url,
        aria_controls="drawer-root",
    )


def _orders_table(rows: list[dict], *, query: str = ""):
    return Table(
        Thead(
            Tr(
                Th("Order"),
                Th("Status"),
                Th("Source event", cls="priority-medium"),
                Th("Delivery", cls="priority-low"),
                Th("Items", cls="priority-low"),
                Th("Revisions", cls="priority-low"),
                Th("Total", cls="money"),
                Th(Span("Open", cls="sr-only"), cls="row-action"),
            )
        ),
        Tbody(
            *(
                Tr(
                    Td(
                        _order_link(
                            row,
                            row["external_order_id"],
                            cls="order-link mono",
                        ),
                        Small(row["retailer_name"]),
                        Small(row["item_names"], cls="search-context")
                        if query and row.get("item_names")
                        else None,
                        cls="cell-primary",
                    ),
                    Td(status_badge(row["status"])),
                    Td(
                        Time(
                            _display_datetime(row["source_event_at"]),
                            datetime=row["source_event_at"],
                        ),
                        cls="priority-medium mono",
                    ),
                    Td(
                        Time(
                            _display_datetime(row["delivery_at"]),
                            datetime=row["delivery_at"],
                        )
                        if row["delivery_at"]
                        else "—",
                        cls="priority-low mono",
                    ),
                    Td(str(row["item_count"]), cls="priority-low mono"),
                    Td(str(row["revision_count"]), cls="priority-low mono"),
                    Td(money(row["total_cents"], row["currency"]), cls="money"),
                    Td(
                        _order_link(
                            row,
                            Icon("chevron-right"),
                            aria_label=f"Open order {row['external_order_id']}",
                            cls="row-open",
                        ),
                        cls="row-action",
                    ),
                )
                for row in rows
            )
        ),
        cls="data-table",
    )


def _order_query_url(*, q: str, retailer: str, status: str, sort: str, page: int) -> str:
    values = {"q": q, "retailer": retailer, "status": status, "sort": sort, "page": page}
    return f"/orders?{urlencode({key: value for key, value in values.items() if value})}"


def _orders_results(data: dict, *, q: str, retailer: str, status: str, sort: str):
    if not data["items"]:
        body = EmptyState(
            "No matching orders",
            "Try a broader product, retailer, order ID, or status filter.",
            icon="search-x",
        )
    else:
        body = Div(_orders_table(data["items"], query=q), cls="table-scroll")
    previous_url = _order_query_url(
        q=q, retailer=retailer, status=status, sort=sort, page=data["page"] - 1
    )
    next_url = _order_query_url(
        q=q, retailer=retailer, status=status, sort=sort, page=data["page"] + 1
    )
    pagination = Div(
        A(
            "← Previous",
            href=previous_url,
            hx_get=previous_url,
            hx_target="#orders-results",
            hx_swap="outerHTML",
            hx_push_url="true",
        )
        if data["page"] > 1
        else Span("← Previous", aria_disabled="true"),
        Span(f"Page {data['page']} of {data['pages']}", cls="mono"),
        A(
            "Next →",
            href=next_url,
            hx_get=next_url,
            hx_target="#orders-results",
            hx_swap="outerHTML",
            hx_push_url="true",
        )
        if data["page"] < data["pages"]
        else Span("Next →", aria_disabled="true"),
        cls="pagination",
    )
    return Div(
        Div(
            Span(f"{data['total']} current order{'s' if data['total'] != 1 else ''}"),
            Span("Newest source event first" if sort == "source_desc" else "Filtered view"),
            cls="results-summary",
        ),
        body,
        pagination,
        id="orders-results",
    )


def _definition_rows(items: list[tuple[str, str]]):
    return Dl(
        *(Div(Dt(label), Dd(value, cls="mono"), cls="definition-row") for label, value in items),
        cls="definition-list",
    )


def _order_items(order: dict):
    return Ul(
        *(
            Li(
                Div(
                    P(item["raw_name"], cls="item-name"),
                    P(
                        f"{item['quantity']:g} {item['unit']}"
                        + (
                            f" · unit {money(item['unit_price_cents'], order['currency'])}"
                            if item["unit_price_cents"] is not None
                            else ""
                        ),
                        cls="item-meta",
                    ),
                ),
                Span(money(item["net_cents"], order["currency"]), cls="money"),
                cls="item-row",
            )
            for item in order["items"]
        ),
        cls="item-list",
    )


def _order_summary(order: dict):
    summary_values = [
        ("Subtotal", order["subtotal_cents"]),
        ("Discount", order["discount_cents"]),
        ("Delivery fee", order["delivery_fee_cents"]),
        ("Service fee", order["service_fee_cents"]),
        ("Other fees", order["other_fee_cents"]),
        ("Tax", order["tax_cents"]),
        ("Included tax", order["included_tax_cents"]),
    ]
    return Div(
        *(
            P(f"{label}: {money(value, order['currency'])}", cls="summary-row")
            for label, value in summary_values
            if value
        ),
        P(
            f"Total: {money(order['total_cents'], order['currency'])}",
            cls="summary-row summary-total",
        ),
        cls="summary-list",
    )


def _revision_history(revisions: list[dict]):
    return Panel(
        SectionHeader(
            "Revision history",
            "Source-event chronology; revision number records insertion order.",
        ),
        Div(
            *(
                Div(
                    Div(
                        Span(
                            "Current factual revision"
                            if revision["is_current"]
                            else "Historical revision",
                            cls="timeline-state",
                        ),
                        P(
                            revision["revision_kind"].title(),
                            cls="timeline-title",
                        ),
                        P(
                            _display_datetime(revision["source_event_at"]),
                            cls="timeline-time mono",
                        ),
                    ),
                    Div(
                        status_badge(revision["status"]),
                        Span(
                            money(revision["total_cents"], revision["currency"]),
                            cls="money",
                        ),
                        Span(
                            f"{revision['item_count']} items · "
                            f"{revision['source_count']} source"
                            f"{'s' if revision['source_count'] != 1 else ''}",
                            cls="timeline-meta",
                        ),
                        cls="timeline-facts",
                    ),
                    Details(
                        Summary(
                            f"Source evidence · {len(revision['sources'])}",
                            cls="source-summary",
                        ),
                        Div(
                            *(
                                Div(
                                    Div(
                                        Span(
                                            f"{source['source_kind'].title()} source",
                                            cls="source-kind",
                                        ),
                                        Span(
                                            status_badge(source["parse_status"]),
                                            cls="source-status",
                                        ),
                                    ),
                                    P(
                                        f"{source['sender_domain']} · "
                                        + _display_datetime(
                                            source["source_sent_at"] or source["received_at"]
                                        ),
                                        cls="source-meta",
                                    ),
                                    P(
                                        f"SHA-256 {source['raw_hash_prefix']}…"
                                        + (
                                            f" · {source['error_code']}"
                                            if source["error_code"]
                                            else ""
                                        ),
                                        cls="source-hash mono",
                                    ),
                                    cls="source-row",
                                )
                                for source in revision["sources"]
                            ),
                            cls="source-list",
                        ),
                        cls="source-evidence",
                    ),
                    cls=f"timeline-entry{' is-current' if revision['is_current'] else ''}",
                )
                for revision in revisions
            ),
            cls="timeline",
            data_revision_count=str(len(revisions)),
        ),
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


def _order_drawer(order: dict, revisions: list[dict]):
    return Div(
        Button(
            "",
            type="button",
            cls="drawer-backdrop",
            aria_label="Close order detail",
            data_drawer_close="true",
        ),
        Aside(
            Div(
                Div(
                    P("Order detail", cls="topbar-eyebrow"),
                    H2(
                        order["external_order_id"],
                        id="drawer-order-title",
                        cls="drawer-title mono",
                    ),
                ),
                Button(
                    Icon("x"),
                    type="button",
                    cls="drawer-close",
                    aria_label="Close order detail",
                    data_drawer_close="true",
                ),
                cls="drawer-header",
            ),
            Div(
                Div(
                    status_badge(order["status"]),
                    Span(order["retailer_name"], cls="drawer-retailer"),
                    cls="drawer-meta",
                ),
                Panel(
                    SectionHeader("Items", f"{len(order['items'])} line items"),
                    _order_items(order),
                ),
                Panel(
                    SectionHeader("Recorded total", "Current factual revision"),
                    _order_summary(order),
                ),
                Panel(
                    SectionHeader("History", f"{len(revisions)} factual revisions"),
                    Div(
                        *(
                            Div(
                                Span(
                                    "Current" if revision["is_current"] else "Historical",
                                    cls="timeline-state",
                                ),
                                Span(
                                    _display_datetime(revision["source_event_at"]),
                                    cls="mono",
                                ),
                                cls="drawer-history-row",
                            )
                            for revision in revisions[:3]
                        )
                    ),
                ),
                A(
                    "Open full order history",
                    href=f"/orders/{order['id']}",
                    cls="drawer-full-link",
                    data_full_page="true",
                ),
                cls="drawer-body",
            ),
            role="dialog",
            aria_modal="true",
            aria_labelledby="drawer-order-title",
            tabindex="-1",
            data_drawer="true",
            cls="order-drawer",
        ),
        cls="drawer-layer",
    )


def create_app(settings: Settings):
    runtime = assert_supported_runtime(enforce_safe_sqlite=settings.enforce_safe_sqlite)
    assert_schema_current(settings.database_path, settings.migrations_dir)
    session_key_path = settings.data_dir / ".sesskey"
    app, _ = fast_app(
        key_fname=str(session_key_path),
        default_hdrs=False,
        pico=False,
        surreal=False,
        htmx=False,
    )
    os.chmod(session_key_path, 0o600)
    app.state.settings = settings
    app.router.routes.insert(
        0,
        Mount(
            "/static",
            app=StaticFiles(directory=str(_STATIC_DIR)),
            name="shopping-static",
        ),
    )
    register_assets(app)

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
                    "uv run --locked shopping import-eml "
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

    @app.get("/orders")  # pyright: ignore[reportAttributeAccessIssue]
    def orders_page(
        request: Request,
        q: str = "",
        retailer: str = "",
        status: str = "",
        sort: str = "source_desc",
        page: int = 1,
    ):
        data = list_orders(
            settings.database_path,
            query=q,
            retailer=retailer,
            status=status,
            sort=sort,
            page=page,
        )
        results = _orders_results(data, q=q, retailer=retailer, status=status, sort=sort)
        if request.headers.get("HX-Target") == "orders-results":
            return results
        filters = Form(
            TextField(
                "Search",
                name="q",
                value=q,
                placeholder="Order, retailer, product, or SKU",
                field_id="order-search",
                icon="search",
                autocomplete="off",
            ),
            SelectField(
                "Retailer",
                name="retailer",
                value=retailer,
                options=(
                    ("", "All retailers"),
                    *((item["slug"], item["name"]) for item in data["retailers"]),
                ),
                compact=True,
            ),
            SelectField(
                "Status",
                name="status",
                value=status,
                options=(
                    ("", "All statuses"),
                    ("placed", "Placed"),
                    ("completed", "Completed"),
                    ("cancelled", "Cancelled"),
                    ("refunded", "Refunded"),
                    ("unknown", "Unknown"),
                ),
                compact=True,
            ),
            SelectField(
                "Sort",
                name="sort",
                value=sort,
                options=(
                    ("source_desc", "Newest source event"),
                    ("source_asc", "Oldest source event"),
                    ("delivery_asc", "Soonest delivery"),
                    ("total_desc", "Highest total"),
                ),
                compact=True,
            ),
            UiButton(
                Icon("search"),
                "Apply",
                type="submit",
                variant="primary",
                cls="filter-submit",
            ),
            method="get",
            action="/orders",
            hx_get="/orders",
            hx_target="#orders-results",
            hx_swap="outerHTML",
            hx_push_url="true",
            hx_trigger=("submit, input changed delay:300ms from:#order-search, change from:select"),
            cls="filters",
        )
        content = PageFrame(
            PageHeader(
                "Orders",
                "Search current factual revisions while retaining append-only history.",
                eyebrow="Purchase history",
            ),
            Panel(filters, results),
        )
        return _page_response(
            request,
            settings,
            title="Orders",
            eyebrow="Purchase history",
            current_path="/orders",
            content=content,
        )

    @app.get("/orders/{order_id}")  # pyright: ignore[reportAttributeAccessIssue]
    def order_detail(request: Request, order_id: int, view: str = ""):
        order = get_current_order(settings.database_path, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        revisions = get_order_history(settings.database_path, order_id)
        if view == "drawer" and request.headers.get("HX-Request") == "true":
            return _order_drawer(order, revisions)
        content = PageFrame(
            P(A("← Orders", href="/orders", cls="back-link")),
            PageHeader(
                f"Order {order['external_order_id']}",
                f"{order['retailer_name']} · revision {order['revision_number']} "
                f"({order['revision_kind']})",
                eyebrow="Order detail",
                actions=(status_badge(order["status"]),),
            ),
            Div(
                Panel(
                    SectionHeader("Items", f"{len(order['items'])} line items"),
                    _order_items(order),
                ),
                Panel(
                    SectionHeader("Recorded total", "Current factual revision"),
                    _order_summary(order),
                ),
                cls="detail-grid",
            ),
            _revision_history(revisions),
        )
        return _page_response(
            request,
            settings,
            title=f"Order {order['external_order_id']}",
            eyebrow="Orders",
            current_path=f"/orders/{order_id}",
            content=content,
        )

    @app.get("/products/{product_id}")  # pyright: ignore[reportAttributeAccessIssue]
    def product_detail(request: Request, product_id: int, cursor: str = ""):
        arguments: dict = {"product_id": product_id}
        if cursor or "cursor" in request.query_params:
            arguments["cursor"] = cursor
        result = dispatch_tool(settings, "get_product_history", arguments)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Product not found")
        if result["status"] == "error":
            invalid = result["data"]["code"] in {"invalid_arguments", "invalid_cursor"}
            raise HTTPException(
                status_code=400 if invalid else 503,
                detail="Invalid purchase history request"
                if invalid
                else "Purchase history unavailable",
            )
        name = result["data"]["canonical_name"]
        return _page_response(
            request,
            settings,
            title=name,
            eyebrow="Purchase history",
            current_path=f"/products/{product_id}",
            content=PageFrame(
                P(A("← Orders", href="/orders", cls="back-link")),
                PageHeader(name, "Current recorded purchases", eyebrow="Product"),
                Panel(product_history(result)),
            ),
        )

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

    @app.get("/fragments/attention")  # pyright: ignore[reportAttributeAccessIssue]
    def attention_fragment():
        return _attention_region(
            overview_snapshot(settings.database_path),
            get_runtime_info(),
        )

    @app.get("/fragments/system-health")  # pyright: ignore[reportAttributeAccessIssue]
    def system_health_fragment():
        return _system_health_region(settings, get_runtime_info())

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

    return app
