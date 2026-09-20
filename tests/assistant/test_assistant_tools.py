from __future__ import annotations

from shopping.assistant.tools import dispatch_tool
from shopping.ingestion.pipeline import import_eml


def test_current_placed_items_are_purchase_history(settings, fixture_dir):
    imported = import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    search = dispatch_tool(settings, "search_products", {"query": "Oat"})
    assert search["status"] == "ok"
    product = search["data"]["items"][0]
    history = dispatch_tool(settings, "get_product_history", {"product_id": product["product_id"]})
    assert history["status"] == "ok"
    assert len(history["data"]["items"]) == 1
    row = history["data"]["items"][0]
    assert row["order_id"] == imported.order_id
    assert row["status"] == "placed"
    assert row["purchase_date"] == "2026-01-12T10:00:00+00:00"
    assert row["quantity"] == 2
    assert row["currency"] == "SGD"
    assert row["net_cents"] == 800
    assert history["next_cursor"] is None
    assert history["truncated"] is False


def test_revisions_do_not_duplicate_purchases(settings, fixture_dir):
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    import_eml(fixture_dir / "fairprice_order_adjusted.eml", settings)
    recent = dispatch_tool(settings, "list_recent_orders", {})
    assert len(recent["data"]["items"]) == 1
    assert recent["data"]["items"][0]["total_cents"] == 1890
    old_product = dispatch_tool(settings, "search_products", {"query": "Oat"})["data"]["items"][0]
    history = dispatch_tool(
        settings, "get_product_history", {"product_id": old_product["product_id"]}
    )
    assert history["status"] == "ok"
    assert history["data"]["items"] == []
    assert dispatch_tool(settings, "get_order", {"order_id": 999})["status"] == "not_found"
    assert (
        dispatch_tool(settings, "get_product_history", {"product_id": 999})["status"] == "not_found"
    )
    assert dispatch_tool(settings, "search_products", {"query": "absent"})["data"]["items"] == []


def test_dates_ties_pagination_and_recorded_missing_values(purchase_facts):
    recent = dispatch_tool(purchase_facts, "list_recent_orders", {"limit": 2})
    assert [row["order_id"] for row in recent["data"]["items"]] == [3, 1]
    remaining = dispatch_tool(
        purchase_facts, "list_recent_orders", {"limit": 2, "cursor": recent["next_cursor"]}
    )
    assert [row["order_id"] for row in remaining["data"]["items"]] == [4, 2]
    assert remaining["data"]["items"][-1]["purchase_date"] is None
    assert remaining["next_cursor"] is None
    assert remaining["truncated"] is False
    rows = collect_pages(purchase_facts, "get_product_history", {"product_id": 1})
    assert len(rows) == 63
    assert [row["order_id"] for row in rows] == [3] * 60 + [1, 4, 2]
    assert rows[0]["quantity"] == 0.5
    assert rows[0]["unit"] == "kg"
    assert rows[0]["unit_price_cents"] is None
    assert rows[0]["gross_cents"] is None
    assert rows[0]["net_cents"] == 125
    assert rows[-1]["purchase_date"] is None
    order_rows = collect_pages(purchase_facts, "get_order", {"order_id": 3})
    assert [row["line_number"] for row in order_rows] == list(range(1, 61))


def collect_pages(settings, tool, arguments):
    from shopping.assistant.tools import encode_result

    rows = []
    cursors = set()
    while True:
        result = dispatch_tool(settings, tool, arguments)
        assert result["status"] == "ok"
        assert len(encode_result(result).encode("utf-8")) <= 4096
        rows.extend(result["data"]["items"])
        cursor = result["next_cursor"]
        assert result["truncated"] is (cursor is not None)
        if cursor is None:
            return rows
        assert cursor not in cursors
        cursors.add(cursor)
        arguments = {**arguments, "cursor": cursor}
        assert len(cursors) < 100


def test_list_purchase_items_month_pagination_and_envelope(purchase_facts):
    from shopping.assistant.tools import MAX_RESULT_BYTES, encode_result

    first = dispatch_tool(purchase_facts, "list_purchase_items", {"month": "2026-01", "limit": 10})
    assert first["status"] == "ok"
    assert first["data"]["month"] == "2026-01"
    assert first["data"]["timezone"] == "Asia/Singapore"
    assert first["data"]["limit"] == 10
    assert len(encode_result(first).encode()) <= MAX_RESULT_BYTES
    rows = list(first["data"]["items"])
    cursor = first["next_cursor"]
    assert cursor
    second = dispatch_tool(
        purchase_facts,
        "list_purchase_items",
        {"month": "2026-01", "limit": 10, "cursor": cursor},
    )
    assert second["status"] == "ok"
    rows.extend(second["data"]["items"])
    assert len({row["order_item_id"] for row in rows}) == len(rows)
    assert all(row["purchase_date"].startswith("2026-01") for row in rows)
    assert (
        dispatch_tool(
            purchase_facts,
            "list_purchase_items",
            {"month": "2026-02", "limit": 10, "cursor": cursor},
        )["data"]["code"]
        == "invalid_cursor"
    )


def test_list_purchase_items_strict_month_and_empty_result(settings):
    for args in (
        {"month": "2026-1"},
        {"month": "2026-01", "limit": 21},
        {"month": "2026-01", "extra": 1},
    ):
        assert dispatch_tool(settings, "list_purchase_items", args)["data"]["code"] == (
            "invalid_arguments"
        )
    empty = dispatch_tool(settings, "list_purchase_items", {"month": "2030-01"})
    assert empty["status"] == "ok" and empty["data"]["items"] == []


def test_list_purchase_items_all_pages_match_independent_expected_ids(monthly_purchase_facts):
    from shopping.assistant.tools import dispatch_tool

    expected = [
        2002,
        1022,
        1020,
        1018,
        1016,
        1014,
        1012,
        1010,
        1008,
        1006,
        1004,
        1002,
        1000,
        1001,
        2001,
    ]
    actual = []
    arguments = {"month": "2026-08", "limit": 10}
    while True:
        page = dispatch_tool(monthly_purchase_facts, "list_purchase_items", arguments)
        assert page["status"] == "ok"
        actual.extend(row["order_item_id"] for row in page["data"]["items"])
        if page["next_cursor"] is None:
            break
        arguments = {**arguments, "cursor": page["next_cursor"]}
    assert actual == expected
    assert not {2000, 2003, 2004, 2005} & set(actual)
    assert len(actual) > 8


def test_list_purchase_items_cursor_binds_limit_database_and_restart(
    monkeypatch, monthly_purchase_facts, tmp_path
):
    from dataclasses import replace

    from shopping.assistant import tools

    first = tools.dispatch_tool(
        monthly_purchase_facts, "list_purchase_items", {"month": "2026-08", "limit": 10}
    )
    cursor = first["next_cursor"]
    assert cursor
    assert (
        tools.dispatch_tool(
            monthly_purchase_facts,
            "list_purchase_items",
            {"month": "2026-08", "limit": 5, "cursor": cursor},
        )["data"]["code"]
        == "invalid_cursor"
    )
    other = replace(monthly_purchase_facts, database_path=tmp_path / "other.sqlite3")
    assert (
        tools.dispatch_tool(
            other,
            "list_purchase_items",
            {"month": "2026-08", "limit": 10, "cursor": cursor},
        )["data"]["code"]
        == "invalid_cursor"
    )
    monkeypatch.setattr(tools, "_CURSOR_KEY", b"restart" * 8)
    assert (
        tools.dispatch_tool(
            monthly_purchase_facts,
            "list_purchase_items",
            {"month": "2026-08", "limit": 10, "cursor": cursor},
        )["data"]["code"]
        == "invalid_cursor"
    )


def test_list_purchase_items_oversized_row_is_bounded(monthly_purchase_facts):
    import sqlite3

    from shopping.assistant.tools import encode_result

    with sqlite3.connect(monthly_purchase_facts.database_path) as connection:
        connection.execute("UPDATE products SET canonical_name=? WHERE id=1", ("X" * 5000,))
        connection.commit()
    result = dispatch_tool(
        monthly_purchase_facts, "list_purchase_items", {"month": "2026-08", "limit": 20}
    )
    assert result["status"] == "error"
    assert result["data"]["code"] == "size_limit"
    assert len(encode_result(result).encode("utf-8")) <= 4096


def test_strict_validation_precedes_storage_access(settings):
    import pytest

    settings.database_path.unlink()
    for name, arguments, code in [
        ("sql", {}, "unknown_tool"),
        ("search_products", {"query": "  "}, "invalid_arguments"),
        ("search_products", {"query": "x" * 201}, "invalid_arguments"),
        ("search_products", {"query": "\ud800"}, "invalid_arguments"),
        ("search_products", {"query": "x", "sql": "SELECT 1"}, "invalid_arguments"),
        ("get_order", {"order_id": 1, "limit": 2}, "invalid_arguments"),
        ("get_order", {}, "invalid_arguments"),
        ("list_recent_orders", {"cursor": None}, "invalid_arguments"),
        ("list_recent_orders", {"cursor": "foreign"}, "invalid_cursor"),
    ]:
        assert dispatch_tool(settings, name, arguments)["data"]["code"] == code
    for value in [True, False, "1", 1.0, 0, -1, None, 2**63]:
        assert dispatch_tool(settings, "get_order", {"order_id": value})["data"]["code"] == (
            "invalid_arguments"
        )
    for value in [True, "1", 1.0, 0, -1, 26]:
        assert dispatch_tool(settings, "list_recent_orders", {"limit": value})["data"]["code"] == (
            "invalid_arguments"
        )
    assert dispatch_tool(settings, "list_recent_orders", {})["data"]["code"] == (
        "storage_unavailable"
    )
    from shopping.assistant.tools import validate_arguments

    with pytest.raises(ValueError, match="invalid_arguments"):
        validate_arguments("list_recent_orders", {"extra": True})


def test_search_candidates_and_cursors_are_bound_to_query(settings, fixture_dir):
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    first = dispatch_tool(settings, "search_products", {"query": " Example ", "limit": 1})
    assert first["data"]["items"][0]["canonical_name"] == "Example Oat Drink 1L"
    assert first["data"]["items"][0]["match_kind"] == "prefix"
    cursor = first["next_cursor"]
    second = dispatch_tool(
        settings, "search_products", {"query": "Example", "limit": 1, "cursor": cursor}
    )
    assert second["data"]["items"][0]["canonical_name"] == "Example Paper Towels 2 Pack"
    assert second["next_cursor"] is None
    for tool, arguments in [
        ("search_products", {"query": "Oat", "limit": 1}),
        ("list_recent_orders", {"limit": 1}),
        ("get_product_history", {"product_id": 1}),
    ]:
        assert dispatch_tool(settings, tool, {**arguments, "cursor": cursor})["data"]["code"] == (
            "invalid_cursor"
        )
    corrupted = cursor[:-4] + "AAAA"
    assert (
        dispatch_tool(
            settings, "search_products", {"query": "Example", "limit": 1, "cursor": corrupted}
        )["status"]
        == "error"
    )
    assert dispatch_tool(settings, "search_products", {"query": "%"})["data"]["items"] == []
    assert (
        dispatch_tool(settings, "search_products", {"query": "Example Oat Drink 1L"})["data"][
            "items"
        ][0]["match_kind"]
        == "exact"
    )
    assert (
        dispatch_tool(settings, "search_products", {"query": "oat"})["data"]["items"][0][
            "match_kind"
        ]
        == "contains"
    )


def test_utf8_budget_returns_whole_rows_and_safe_oversize_error(purchase_facts):
    from shopping.assistant.tools import encode_result
    from shopping.storage.connection import connect_database

    connection = connect_database(purchase_facts.database_path)
    try:
        connection.execute("UPDATE order_items SET raw_name = ?", ("茶" * 100,))
        page = dispatch_tool(purchase_facts, "get_order", {"order_id": 3})
        assert page["status"] == "ok"
        assert 0 < len(page["data"]["items"]) < 50
        assert len(encode_result(page).encode("utf-8")) <= 4096
        assert page["data"]["total_cents"] == 125  # Recorded order total, not a page sum.
        rows = collect_pages(purchase_facts, "get_order", {"order_id": 3})
        assert len(rows) == 60
        assert all(row["raw_name"] == "茶" * 100 for row in rows)
        connection.execute("UPDATE order_items SET raw_name = ?", ("茶" * 1500,))
        oversized = dispatch_tool(purchase_facts, "get_order", {"order_id": 3})
        assert oversized == {
            "status": "error",
            "data": {"code": "size_limit"},
            "evidence": [],
            "next_cursor": None,
            "truncated": False,
        }
        assert len(encode_result(oversized).encode("utf-8")) <= 4096
    finally:
        connection.close()


def test_evidence_contains_only_local_current_record_references(settings, fixture_dir):
    from shopping.assistant.tools import encode_result
    from shopping.web.factory import create_app

    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    app = create_app(settings)
    with app.get_testclient() as client:
        for name, arguments in [
            ("search_products", {"query": "Example"}),
            ("get_product_history", {"product_id": 1}),
            ("get_order", {"order_id": 1}),
            ("list_recent_orders", {}),
        ]:
            result = dispatch_tool(settings, name, arguments)
            encoded = encode_result(result)
            for forbidden in (
                "raw_path",
                "source_event_at",
                "sender",
                "parser",
                str(settings.database_path),
                str(settings.raw_email_dir),
            ):
                assert forbidden not in encoded
            for evidence in result["evidence"]:
                assert evidence["id"] == f"{evidence['entity_type']}:{evidence['entity_id']}"
                assert client.get(evidence["url"]).status_code == 200


def test_storage_failure_is_not_empty_history(settings):
    from shopping.storage.connection import connect_database

    connection = connect_database(settings.database_path)
    try:
        connection.execute("DROP TABLE products")
    finally:
        connection.close()
    assert dispatch_tool(settings, "search_products", {"query": "x"}) == {
        "status": "error",
        "data": {"code": "storage_unavailable"},
        "evidence": [],
        "next_cursor": None,
        "truncated": False,
    }


def test_schemas_expose_exactly_five_strict_tools():
    from shopping.assistant.tools import tool_schemas, validate_arguments

    schemas = tool_schemas()
    assert [schema["function"]["name"] for schema in schemas] == [
        "search_products",
        "get_product_history",
        "list_recent_orders",
        "get_order",
        "list_purchase_items",
    ]
    for schema in schemas:
        assert schema["function"]["parameters"]["additionalProperties"] is False
    assert validate_arguments("search_products", {"query": " x "}) == {"query": "x", "limit": 10}
    assert validate_arguments("get_product_history", {"product_id": 1})["limit"] == 20
    assert validate_arguments("list_recent_orders", {})["limit"] == 10


def test_cursor_scope_ignores_argument_mapping_order(purchase_facts):
    first = dispatch_tool(purchase_facts, "get_product_history", {"product_id": 1, "limit": 1})
    second = dispatch_tool(
        purchase_facts,
        "get_product_history",
        {"limit": 1, "product_id": 1, "cursor": first["next_cursor"]},
    )
    assert second["status"] == "ok"
    assert second["data"]["items"][0]["line_number"] == 2


def test_row_ceilings_and_foreign_entity_cursors(purchase_facts):
    for tool, arguments, ceiling in [
        ("search_products", {"query": "Example"}, 20),
        ("get_product_history", {"product_id": 1}, 50),
        ("list_recent_orders", {}, 25),
    ]:
        assert (
            dispatch_tool(purchase_facts, tool, {**arguments, "limit": ceiling})["status"] == "ok"
        )
        assert (
            dispatch_tool(purchase_facts, tool, {**arguments, "limit": ceiling + 1})["data"]["code"]
            == "invalid_arguments"
        )
    for tool, field, source, other in [
        ("get_product_history", "product_id", 1, 2),
        ("get_order", "order_id", 3, 1),
    ]:
        first = dispatch_tool(purchase_facts, tool, {field: source})
        assert first["next_cursor"] is not None
        assert dispatch_tool(purchase_facts, tool, {field: other, "cursor": first["next_cursor"]})[
            "data"
        ]["code"] == ("invalid_cursor")
