from __future__ import annotations

from urllib.parse import urlencode

from fasthtml.common import (
    H2,
    A,
    Aside,
    Button,
    Details,
    Div,
    Form,
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
)
from starlette.exceptions import HTTPException
from starlette.requests import Request
from stitchyard.ui import (
    EmptyState,
    Icon,
    PageFrame,
    PageHeader,
    Panel,
    SectionHeader,
    SelectField,
    TextField,
    UiButton,
)

from shopping.config import Settings
from shopping.purchases.queries import (
    get_current_order,
    get_order_history,
    list_orders,
)
from shopping.web.layout import _display_datetime, _page_response, money, status_badge


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


def register_orders(app, settings: Settings) -> None:
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
