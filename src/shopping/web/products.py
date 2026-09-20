from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fasthtml.common import (
    A,
    Div,
    P,
    Span,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Tr,
)
from starlette.exceptions import HTTPException
from starlette.requests import Request
from stitchyard.ui import (
    PageFrame,
    PageHeader,
    Panel,
)

from shopping.assistant.tools import dispatch_tool
from shopping.config import Settings
from shopping.web.layout import _page_response, money, status_badge


def product_history(result: dict[str, Any]):
    """Inspect the same bounded current purchase facts supplied to read tools."""
    data = result["data"]
    rows = []
    for item in data["items"]:
        purchase_date = item["purchase_date"]
        date_label = (
            datetime.fromisoformat(purchase_date)
            .astimezone(ZoneInfo("Asia/Singapore"))
            .strftime("%d %b %Y")
            if purchase_date
            else "Unavailable"
        )
        rows.append(
            Tr(
                Td(A(item["external_order_id"], href=f"/orders/{item['order_id']}")),
                Td(item["raw_name"]),
                Td(date_label),
                Td(status_badge(item["status"])),
                Td(f"{item['quantity']:g} {item['unit']}"),
                Td(money(item["unit_price_cents"], item["currency"])),
                Td(money(item["net_cents"], item["currency"])),
            )
        )
    next_url = (
        f"/products/{data['product_id']}?{urlencode({'cursor': result['next_cursor']})}"
        if result["next_cursor"]
        else None
    )
    return Div(
        Div(
            Table(
                Thead(
                    Tr(
                        *(
                            Th(label)
                            for label in (
                                "Order",
                                "Recorded item",
                                "Purchase date",
                                "Status",
                                "Quantity",
                                "Unit price",
                                "Net amount",
                            )
                        )
                    )
                ),
                Tbody(*rows),
                cls="data-table",
            ),
            cls="table-scroll",
        )
        if rows
        else P("No current purchases recorded."),
        Div(
            A("← First page", href=f"/products/{data['product_id']}"),
            Span("More purchases available" if next_url else "End of purchase history"),
            A("Next →", href=next_url) if next_url else None,
            cls="pagination",
        ),
    )


def register_products(app, settings: Settings) -> None:
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
