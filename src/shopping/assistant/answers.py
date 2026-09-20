"""Deterministic renderers for bounded recorded-purchase tool results."""

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shopping.assistant.dates import month_bounds

SG = ZoneInfo("Asia/Singapore")


def render_recorded(
    question: str, results: list[tuple[str, dict]], evidence: dict[str, dict]
) -> tuple[str, list[str], bool] | None:
    """Render tool results deterministically, with an explicit answerability flag."""
    if type(question) is not str or not isinstance(results, list) or not isinstance(evidence, dict):
        return None
    if not results:
        return None
    requested = question.casefold()
    lookup = (
        requested.startswith(("show ", "list ", "look up ", "find ", "search "))
        or "order details" in requested
        or "latest order" in requested
        or "recent orders" in requested
        or "product history" in requested
        or "purchase items" in requested
        or requested in {"order?", "order"}
        or ("total" in requested and "order" in requested)
        or requested.startswith("what did i order")
        or (requested.startswith("which ") and "product" in requested)
        or any(token in requested for token in (" fee", "unit price"))
    )
    supported = lookup and not any(
        word in requested
        for word in (
            "forecast",
            "predict",
            "recommend",
            "why",
            "how many",
            "total count",
            "aggregate",
        )
    )
    requested_fee_fields = {
        "delivery": "delivery_fee_cents",
        "service": "service_fee_cents",
        "other": "other_fee_cents",
        "tax": "tax_cents",
        "subtotal": "subtotal_cents",
        "discount": "discount_cents",
    }
    asks_unit_price = "unit price" in requested
    requested_data_fields = []
    if "quantity" in requested:
        requested_data_fields.append("quantity")
    if re.search(r"\btotal\b", requested):
        requested_data_fields.append("total_cents")
    if "delivery date" in requested or "purchase date" in requested:
        requested_data_fields.append("purchase_date")
    lines = ["Here are the recorded details from this lookup:"]
    refs: list[str] = []
    available_fields: set[str] = set()
    answered = supported

    def clean(value: object) -> str:
        return _clean(value)

    def money(currency: object, cents: object) -> str:
        if not isinstance(currency, str) or type(cents) is not int:
            return "unknown"
        major, minor = divmod(abs(cents), 100)
        return f"{clean(currency)} {'-' if cents < 0 else ''}{major}.{minor:02d}"

    for name, result in results:
        if not isinstance(name, str) or not isinstance(result, dict):
            return None
        status = result.get("status")
        if status == "not_found":
            lines.append("No matching record was returned for this lookup.")
            continue
        if status != "ok" or not isinstance(result.get("data"), dict):
            return None
        data = result["data"]
        items = data.get("items", [])
        if not isinstance(items, list):
            return None
        records = ([data] if "order_id" in data or "product_id" in data else []) + items
        available_fields.update(data)
        for candidate in items:
            if isinstance(candidate, dict):
                available_fields.update(candidate)
        if name == "search_products" and (len(items) > 1 or result.get("truncated")):
            lines.append("Product candidates:")
        if name == "get_product_history" and not items:
            lines.append("No current recorded purchase items were found for this product.")
        elif not records:
            lines.append("No rows were returned for this lookup.")
        for record in records:
            if not isinstance(record, dict):
                return None
            row_refs: list[str] = []
            parts: list[str] = []
            for kind in ("order", "product"):
                entity = record.get(f"{kind}_id")
                if entity is None and kind == "order" and name == "get_order":
                    entity = data.get("order_id")
                if entity is not None:
                    reference = f"{kind}:{entity}"
                    if reference not in evidence:
                        return None
                    row_refs.append(reference)
                    parts.append(f"{kind.title()} {entity}")
                    if reference not in refs:
                        refs.append(reference)
            if not row_refs:
                return None
            label = record.get("raw_name") or record.get("canonical_name")
            if label:
                parts.append(clean(label))
            if record.get("retailer_name"):
                parts.append(f"from {clean(record['retailer_name'])}")
            if "purchase_date" in record:
                parts.append(f"purchase date {_delivery(record['purchase_date'])}")
            if "status" in record:
                parts.append(f"status {clean(record['status'])}")
            currency = record.get("currency", data.get("currency"))
            for field, label_text in (
                ("subtotal_cents", "subtotal"),
                ("discount_cents", "discount"),
                ("delivery_fee_cents", "delivery fee"),
                ("service_fee_cents", "service fee"),
                ("other_fee_cents", "other fee"),
                ("tax_cents", "tax"),
                ("included_tax_cents", "included tax"),
                ("total_cents", "total"),
                ("unit_price_cents", "unit price"),
                ("gross_cents", "gross"),
                ("net_cents", "line value"),
            ):
                if field in record:
                    parts.append(f"{label_text} {money(currency, record[field])}")
            if "line_number" in record:
                parts.append(f"line {clean(record['line_number'])}")
            if "quantity" in record:
                quantity = "unknown" if record["quantity"] is None else clean(record["quantity"])
                unit = f" {clean(record['unit'])}" if record.get("unit") else ""
                parts.append(f"quantity {quantity}{unit}")
            if not parts:
                return None
            lines.append(" — ".join(parts) + " " + " ".join(f"[[{ref}]]" for ref in row_refs))
        if name == "search_products" and (len(items) > 1 or result.get("truncated")):
            lines.append("Which product do you mean?")
        if result.get("truncated"):
            lines.append("This lookup is partial; ask for the next page to see more recorded rows.")
    requested_fields = [
        field
        for word, field in requested_fee_fields.items()
        if re.search(rf"\b{re.escape(word)}\s+fee\b|\b{re.escape(word)}\b", requested)
        and not (word == "delivery" and re.search(r"\bdelivery\s+date\b", requested))
    ]
    if (
        any(word in requested for word in ("fee", "tax", "subtotal", "discount"))
        and not requested_fields
    ):
        requested_fields = ["delivery_fee_cents", "service_fee_cents", "other_fee_cents"]
    missing_fields = [field for field in requested_fields if field not in available_fields]
    if asks_unit_price and "unit_price_cents" not in available_fields:
        missing_fields.append("unit_price_cents")
    missing_fields.extend(field for field in requested_data_fields if field not in available_fields)
    if missing_fields:
        answered = False
        labels = {
            "delivery_fee_cents": "delivery fee",
            "service_fee_cents": "service fee",
            "other_fee_cents": "other fee",
            "unit_price_cents": "unit price",
            "total_cents": "total",
            "purchase_date": "purchase date",
            "quantity": "quantity",
        }
        lines.append(
            "Requested recorded fields unavailable: "
            + ", ".join(dict.fromkeys(labels.get(field, field) for field in missing_fields))
            + "."
        )
    if not supported:
        lines.insert(
            0,
            "Answer incomplete: this request is outside recorded lookup support; "
            "here are the available recorded details:",
        )
        answered = False
    return "\n".join(lines), refs, answered


def _clean(value: object, unknown: str = "unknown") -> str:
    if value is None or value == "":
        return unknown
    return " ".join(str(value).split()).replace("[", "[ ").replace("]", " ]")


def _delivery(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return "unknown"
        return parsed.astimezone(SG).date().isoformat()
    except ValueError:
        return "unknown"


def render_month_items(result: dict[str, Any]) -> tuple[str, list[str]]:
    """Render one validated ``list_purchase_items`` envelope without inference."""
    if result.get("status") != "ok" or not isinstance(result.get("data"), dict):
        raise ValueError("invalid_result")
    data = result["data"]
    month = data.get("month")
    items = data.get("items")
    evidence = result.get("evidence", [])
    if not isinstance(month, str) or not isinstance(items, list) or not isinstance(evidence, list):
        raise ValueError("invalid_result")
    try:
        month_bounds(month)
    except ValueError as exc:
        raise ValueError("invalid_result") from exc
    allowed = {
        entry.get("id")
        for entry in evidence
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    refs: list[str] = []
    lines = [f"Recorded purchase items for {month} (delivery date, Asia/Singapore):"]
    if not items:
        lines.append("No recorded purchase items were found for this month.")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid_result")
        order_id = item.get("order_id")
        order_ref = f"order:{order_id}" if type(order_id) is int and order_id > 0 else None
        if order_ref is None or order_ref not in allowed:
            raise ValueError("invalid_result")
        marker = f" [[{order_ref}]]" if order_ref in allowed else ""
        if isinstance(order_ref, str) and order_ref in allowed and order_ref not in refs:
            refs.append(order_ref)
        quantity = _clean(item.get("quantity"))
        unit = item.get("unit")
        amount = quantity if unit in (None, "") else f"{quantity} {_clean(unit)}"
        lines.append(
            f"- {_clean(item.get('raw_name'))} — {amount}; "
            f"delivery {_delivery(item.get('purchase_date'))}; "
            f"status {_clean(item.get('status'))}; "
            f"order {_clean(item.get('external_order_id'))} (ID {_clean(order_id)}){marker}."
        )
    if result.get("next_cursor"):
        lines.append(
            "This page is partial; ask for the next page to continue this month's records."
        )
    else:
        lines.append("No more recorded item lines follow this page for the requested month.")
    lines.append(
        "Known dates are scheduled delivery dates, not confirmed arrival. "
        "Unknown delivery dates are excluded."
    )
    return "\n".join(lines), refs
