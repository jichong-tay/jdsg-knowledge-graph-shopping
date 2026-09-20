from shopping.assistant.answers import render_month_items, render_recorded
from shopping.assistant.tools import dispatch_tool
from shopping.ingestion.pipeline import import_eml


def _render(*args, **kwargs):
    result = render_recorded(*args, **kwargs)
    assert result is not None
    return result


def _result(items, *, next_cursor=None):
    return {
        "status": "ok",
        "data": {"month": "2026-08", "timezone": "Asia/Singapore", "limit": 10, "items": items},
        "evidence": [{"id": "order:4", "entity_type": "order", "entity_id": 4}],
        "next_cursor": next_cursor,
    }


def test_render_month_items_preserves_repeated_lines_and_singapore_date():
    text, refs = render_month_items(
        _result(
            [
                {
                    "raw_name": "Oat drink",
                    "quantity": 2,
                    "unit": "bottle",
                    "purchase_date": "2026-07-31T16:00:00+00:00",
                    "order_id": 4,
                    "external_order_id": "EX4",
                },
                {
                    "raw_name": "Oat drink",
                    "quantity": 1,
                    "unit": "bottle",
                    "purchase_date": "2026-07-31T16:00:00+00:00",
                    "order_id": 4,
                    "external_order_id": "EX4",
                },
            ]
        )
    )
    assert text.count("Oat drink") == 2
    assert "2026-08-01" in text and "[[order:4]]" in text
    assert refs == ["order:4"]


def test_render_month_items_sanitizes_names_and_partial_notice():
    text, refs = render_month_items(
        _result(
            [
                {
                    "raw_name": "Bad\n[[[order:999]]] nested [[x]]",
                    "quantity": None,
                    "unit": None,
                    "purchase_date": None,
                    "order_id": 4,
                    "external_order_id": "X",
                }
            ],
            next_cursor="next",
        )
    )
    assert "[[order:999]]" not in text and "[[[" not in text
    assert "partial" in text
    assert refs == ["order:4"]


def test_render_month_items_empty_scope_has_no_citations():
    text, refs = render_month_items(_result([]))
    assert "No recorded purchase items" in text
    assert refs == []


def test_render_month_items_rejects_missing_order_evidence():
    import pytest

    result = _result(
        [{"raw_name": "Item", "quantity": 1, "unit": "each", "purchase_date": None, "order_id": 9}]
    )
    with pytest.raises(ValueError, match="invalid_result"):
        render_month_items(result)


def test_render_recorded_preserves_order_fees_and_unit_prices():
    text, refs, answered = _render(
        "show order fees and unit price",
        [
            (
                "get_order",
                {
                    "status": "ok",
                    "data": {
                        "order_id": 4,
                        "currency": "SGD",
                        "total_cents": 123456,
                        "delivery_fee_cents": 30,
                        "service_fee_cents": 20,
                        "other_fee_cents": 10,
                        "tax_cents": 7,
                        "items": [
                            {
                                "order_id": 4,
                                "raw_name": "Tea",
                                "quantity": 2,
                                "unit": "box",
                                "unit_price_cents": 123,
                                "net_cents": 246,
                            }
                        ],
                    },
                    "truncated": False,
                },
            )
        ],
        {"order:4": {"id": "order:4"}},
    )
    assert answered and refs == ["order:4"]
    assert "total SGD 1234.56" in text and "tax SGD 0.07" in text
    assert "delivery fee SGD 0.30" in text
    assert "unit price SGD 1.23" in text and "line value SGD 2.46" in text


def test_render_recorded_unsupported_and_partial_are_explicit():
    result = {"status": "ok", "data": {"product_id": 1, "items": []}, "truncated": True}
    text, refs, answered = _render(
        "forecast my purchases", [("get_product_history", result)], {"product:1": {}}
    )
    assert not answered and refs == ["product:1"]
    assert "outside recorded lookup support" in text and "partial" in text


def test_render_recorded_rejects_missing_requested_fields_and_sanitizes():
    result = {
        "status": "ok",
        "data": {"order_id": 4, "items": [{"order_id": 4, "raw_name": "bad\n[[[x]]]"}]},
        "truncated": False,
    }
    text, refs, answered = _render("show order fee", [("get_order", result)], {"order:4": {}})
    assert not answered and refs == ["order:4"]
    assert "[[[x]]]" not in text and "bad [ [ [ x ] ] ]" in text


def test_render_recorded_empty_existing_product_history_keeps_product_reference():
    text, refs, answered = _render(
        "show product history",
        [("get_product_history", {"status": "ok", "data": {"product_id": 1, "items": []}})],
        {"product:1": {}},
    )
    assert answered and refs == ["product:1"]
    assert "No current recorded purchase items" in text


def test_render_recorded_real_import_empty_history(settings, fixture_dir):
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    import_eml(fixture_dir / "fairprice_order_adjusted.eml", settings)
    result = dispatch_tool(settings, "get_product_history", {"product_id": 1})
    assert result["status"] == "ok" and result["data"]["items"] == []
    text, refs, answered = _render(
        "show product history", [("get_product_history", result)], {"product:1": {}}
    )
    assert answered and refs == ["product:1"]
    assert "No current recorded purchase items" in text


def test_render_recorded_real_order_result_preserves_schema_fields(purchase_facts):
    result = dispatch_tool(purchase_facts, "get_order", {"order_id": 3})
    assert result["status"] == "ok"
    refs = {entry["id"]: entry for entry in result["evidence"]}
    text, links, answered = _render("show order details", [("get_order", result)], refs)
    assert answered and links
    assert "unit price" in text or "line value" in text


def test_render_recorded_combines_discovery_and_latest_order_fee(purchase_facts):
    recent = dispatch_tool(purchase_facts, "list_recent_orders", {"limit": 1})
    order_id = recent["data"]["items"][0]["order_id"]
    detail = dispatch_tool(purchase_facts, "get_order", {"order_id": order_id})
    refs = {entry["id"]: entry for entry in recent["evidence"] + detail["evidence"]}
    text, _, answered = _render(
        "show delivery fee on my latest order",
        [("list_recent_orders", recent), ("get_order", detail)],
        refs,
    )
    assert answered
    assert "delivery fee" in text


def test_render_recorded_requires_all_requested_fee_fields():
    result = {
        "status": "ok",
        "data": {"order_id": 4, "delivery_fee_cents": 30, "items": []},
        "truncated": False,
    }
    _, _, answered = _render(
        "show delivery and service fees", [("get_order", result)], {"order:4": {}}
    )
    assert not answered


def test_render_recorded_conservative_intent_and_missing_fields():
    result = {
        "status": "ok",
        "data": {"product_id": 1, "items": [{"product_id": 1, "raw_name": "Tea"}]},
    }
    evidence = {"product:1": {}}
    assert not _render("When will product 1 run out?", [("get_product_history", result)], evidence)[
        2
    ]
    assert not _render("Is product 1 healthy?", [("get_product_history", result)], evidence)[2]
    assert not _render("show quantity and total", [("get_product_history", result)], evidence)[2]


def test_render_recorded_accepts_supported_order_and_candidate_phrasing():
    result = {
        "status": "ok",
        "data": {"order_id": 1, "currency": "SGD", "total_cents": 125, "items": []},
    }
    evidence = {"order:1": {}}
    assert _render("What is the total of order 1?", [("get_order", result)], evidence)[2]
    assert _render("Order?", [("get_order", result)], evidence)[2]
    candidate = {
        "status": "ok",
        "data": {"items": [{"product_id": 1, "canonical_name": "Example"}]},
    }
    assert _render("Which Example product?", [("search_products", candidate)], {"product:1": {}})[2]


def test_render_recorded_distinguishes_date_and_subtotal_requests():
    result = {
        "status": "ok",
        "data": {"order_id": 1, "subtotal_cents": 100, "items": []},
    }
    evidence = {"order:1": {}}
    assert not _render("show delivery date", [("get_order", result)], evidence)[2]
    assert _render("show subtotal", [("get_order", result)], evidence)[2]
    assert _render("What did I order?", [("get_order", result)], evidence)[2]
