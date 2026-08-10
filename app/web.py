"""FastHTML dashboard for the first ingestion slice."""

from __future__ import annotations

import os
from typing import Any

from fasthtml.common import (
    H1,
    H2,
    A,
    Body,
    Div,
    Head,
    Html,
    JSONResponse,
    Li,
    Main,
    Meta,
    P,
    Small,
    Span,
    Style,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Title,
    Tr,
    Ul,
    fast_app,
)
from starlette.exceptions import HTTPException

from app.config import Settings
from app.db.migrations import assert_schema_current, current_schema_version
from app.db.repository import (
    count_current_orders,
    get_current_order,
    ingestion_counts,
    list_current_orders,
)
from app.runtime import assert_supported_runtime, get_runtime_info

_STYLES = """
:root { color-scheme: light; font-family: ui-sans-serif, system-ui, sans-serif; }
body { background: #f5f7f4; color: #17201a; margin: 0; }
main { max-width: 900px; margin: 0 auto; padding: 2rem 1rem 4rem; }
h1 { margin-bottom: .25rem; }
a { color: #176b45; }
.muted { color: #66736b; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
.cards { gap: 1rem; margin: 1.5rem 0; }
.card { background: white; border: 1px solid #dce4de; border-radius: .8rem; }
.card { padding: 1rem; box-shadow: 0 2px 8px #17201a0b; }
.value { display: block; font-size: 1.5rem; font-weight: 700; margin-top: .25rem; }
table { width: 100%; border-collapse: collapse; background: white; }
table { border-radius: .8rem; overflow: hidden; }
th, td { padding: .8rem; border-bottom: 1px solid #e4e9e5; text-align: left; }
th { background: #edf3ef; }
.money { text-align: right; font-variant-numeric: tabular-nums; }
.badge { background: #e1f2e8; border-radius: 999px; padding: .2rem .55rem; font-size: .85rem; }
.warning { background: #fff4d6; border: 1px solid #efd289; border-radius: .6rem; padding: .8rem; }
"""


def _money(cents: int, currency: str) -> str:
    return f"{currency} {cents / 100:,.2f}"


def _layout(title: str, *content: Any) -> Any:
    return Html(
        Head(
            Title(f"{title} · Shopping Intelligence"),
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Style(_STYLES),
        ),
        Body(Main(*content)),
    )


def create_app(settings: Settings):
    runtime = assert_supported_runtime(enforce_safe_sqlite=settings.enforce_safe_sqlite)
    assert_schema_current(settings.database_path, settings.migrations_dir)
    session_key_path = settings.data_dir / ".sesskey"
    app, _ = fast_app(key_fname=str(session_key_path))
    os.chmod(session_key_path, 0o600)
    app.state.settings = settings

    @app.get("/")  # pyright: ignore[reportAttributeAccessIssue]
    def dashboard():
        orders = list_current_orders(settings.database_path)
        order_count = count_current_orders(settings.database_path)
        counts = ingestion_counts(settings.database_path)
        cards = Div(
            Div(
                Small("Imported messages"),
                Span(str(counts.get("parsed", 0)), cls="value"),
                cls="card",
            ),
            Div(Small("Orders"), Span(str(order_count), cls="value"), cls="card"),
            Div(
                Small("Runtime"),
                Span("Ready" if runtime.sqlite_wal_safe else "Development only", cls="value"),
                cls="card",
            ),
            cls="cards",
        )
        warning = (
            P(
                f"Development SQLite {runtime.sqlite_version} lacks the required production "
                "WAL fix. "
                "The production profile will refuse to start until SQLite is upgraded.",
                cls="warning",
            )
            if not runtime.sqlite_wal_safe
            else None
        )
        if not orders:
            history = Div(
                H2("No orders yet"),
                P("Import a sanitized sample email to exercise the first vertical slice."),
                P(
                    "uv run --locked shopping import-eml "
                    "tests/fixtures/email/fairprice_order_minimal.eml --synthetic-fixture"
                ),
                cls="card",
            )
        else:
            history = Div(
                H2("Current orders"),
                Table(
                    Thead(Tr(Th("Order"), Th("Vendor"), Th("Items"), Th("Status"), Th("Total"))),
                    Tbody(
                        *(
                            Tr(
                                Td(A(order["external_order_id"], href=f"/orders/{order['id']}")),
                                Td(order["retailer_name"]),
                                Td(str(order["item_count"])),
                                Td(Span(order["status"], cls="badge")),
                                Td(_money(order["total_cents"], order["currency"]), cls="money"),
                            )
                            for order in orders
                        )
                    ),
                ),
            )
        return _layout(
            "Dashboard",
            H1("Shopping Intelligence"),
            P("Private purchase history from archived retailer emails.", cls="muted"),
            warning,
            cards,
            history,
        )

    @app.get("/orders/{order_id}")  # pyright: ignore[reportAttributeAccessIssue]
    def order_detail(order_id: int):
        order = get_current_order(settings.database_path, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        items = Ul(
            *(
                Li(
                    f"{item['quantity']:g} x {item['raw_name']} - "
                    f"{_money(item['net_cents'], order['currency'])}"
                )
                for item in order["items"]
            )
        )
        return _layout(
            f"Order {order['external_order_id']}",
            P(A("← All orders", href="/")),
            H1(f"Order {order['external_order_id']}"),
            P(
                f"{order['retailer_name']} · {order['status']} · "
                f"revision {order['revision_number']} ({order['revision_kind']})",
                cls="muted",
            ),
            Div(H2("Items"), items, cls="card"),
            Div(
                H2("Summary"),
                P(f"Subtotal: {_money(order['subtotal_cents'], order['currency'])}"),
                *(
                    [P(f"Discount: {_money(order['discount_cents'], order['currency'])}")]
                    if order["discount_cents"]
                    else []
                ),
                *(
                    [P(f"Delivery fee: {_money(order['delivery_fee_cents'], order['currency'])}")]
                    if order["delivery_fee_cents"]
                    else []
                ),
                *(
                    [P(f"Service fee: {_money(order['service_fee_cents'], order['currency'])}")]
                    if order["service_fee_cents"]
                    else []
                ),
                *(
                    [P(f"Other fees: {_money(order['other_fee_cents'], order['currency'])}")]
                    if order["other_fee_cents"]
                    else []
                ),
                *(
                    [P(f"Tax: {_money(order['tax_cents'], order['currency'])}")]
                    if order["tax_cents"]
                    else []
                ),
                *(
                    [P(f"Included tax: {_money(order['included_tax_cents'], order['currency'])}")]
                    if order["included_tax_cents"]
                    else []
                ),
                P(f"Total: {_money(order['total_cents'], order['currency'])}"),
                cls="card",
            ),
        )

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
