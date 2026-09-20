from contextlib import closing
from datetime import date

import pytest

from shopping.knowledge.models import (
    GraphEdge,
    GraphNode,
    GraphProjection,
    GraphReadError,
    GraphViewRequest,
    RecordRef,
)
from shopping.knowledge.projection import canonical_payload, validate_projection
from shopping.knowledge.records import product_purchase_counts
from shopping.knowledge.relationships import read_relations
from shopping.knowledge.snapshot import read_graph_view
from shopping.purchases.family_models import PurchaseScope
from shopping.storage.connection import connect_database


def test_product_counts_are_explicit_zero_and_distinct_orders(purchase_facts):
    from shopping.storage.connection import transaction

    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        c.execute(
            "INSERT INTO products "
            "(id, canonical_key, canonical_name, normalized_name, is_active, "
            "created_at, updated_at) "
            "VALUES (9999, 'unused-9999', 'Unused', 'unused', 1, '2026-01-01', '2026-01-01')"
        )
    with closing(connect_database(purchase_facts.database_path)) as c:
        counts = product_purchase_counts(c, (1, 9999), PurchaseScope(date(2026, 9, 20)))
    assert counts[1] == 3
    assert counts[9999] == 0


def test_selected_product_exposes_exact_count_even_when_product_hidden(purchase_facts):
    request = GraphViewRequest(
        purchase_scope=PurchaseScope(date(2026, 9, 20)),
        selected_id="".join(("0" * 32, ":product:1")),
    )
    first = read_graph_view(purchase_facts, request.model_copy(update={"selected_id": None}))
    selected = read_graph_view(
        purchase_facts,
        request.model_copy(
            update={
                "selected_id": f"{first.snapshot.dataset_id}:product:1",
                "node_types": ("order",),
            }
        ),
    )
    assert selected.selection is not None
    assert selected.selection["node"].attributes["purchase_count"] == 3
    assert selected.coverage["hidden_by_type"] >= 1


def test_history_preserves_current_purchase_count_and_scope_boundaries(purchase_facts):
    scope = PurchaseScope(date(2026, 9, 20), date(2026, 1, 10), date(2026, 1, 12))
    with closing(connect_database(purchase_facts.database_path)) as c:
        current = product_purchase_counts(c, (1,), scope)
        rows = read_relations(c, RecordRef("product", 1), mode="current", scope=scope)
        history = read_relations(c, RecordRef("product", 1), mode="history", scope=scope)
    assert current[1] == 3
    assert {r.target.row_id for r in rows if r.type == "PURCHASED_IN"} == {1, 3, 4}
    assert {r.target.row_id for r in history if r.type == "PURCHASED_IN"} == {1, 3, 4}


def test_relation_pages_union_without_duplicates_and_include_proof(purchase_facts):
    scope = PurchaseScope(date(2026, 9, 20))
    with closing(connect_database(purchase_facts.database_path)) as c:
        first = read_relations(c, RecordRef("product", 1), mode="current", scope=scope, limit=1)
        cursor = __import__(
            "shopping.knowledge.relationships", fromlist=["relation_key"]
        ).relation_key(first[-1])
        second = read_relations(
            c, RecordRef("product", 1), mode="current", scope=scope, after=cursor, limit=61
        )
    purchases = [r for r in first + second if r.type == "PURCHASED_IN"]
    assert len({(r.source.row_id, r.target.row_id) for r in purchases}) == len(purchases)
    assert all({"revision", "item"} <= {x.entity_type for x in r.support} for r in purchases)


def test_graph_projection_has_valid_dataset_ids_and_repeat_is_canonical(purchase_facts):
    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    first = read_graph_view(purchase_facts, request)
    second = read_graph_view(purchase_facts, request)
    assert first.nodes
    assert all(node.id.startswith(first.snapshot.dataset_id + ":") for node in first.nodes)
    assert canonical_payload(first) == canonical_payload(second)


def test_purchase_relation_has_revision_and_item_proof(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c:
        rows = read_relations(
            c, RecordRef("product", 1), mode="current", scope=PurchaseScope(date(2026, 9, 20))
        )
    purchases = [row for row in rows if row.type == "PURCHASED_IN"]
    assert purchases
    assert all(
        {"product", "order", "revision", "item"} <= {r.entity_type for r in row.support}
        for row in purchases
    )


def test_purchase_projection_rejects_missing_proof():
    dataset = "0" * 32
    product = GraphNode(f"{dataset}:product:1", "product", "p", RecordRef("product", 1), {})
    order = GraphNode(f"{dataset}:order:1", "order", "o", RecordRef("order", 1), {})
    edge = GraphEdge(
        "x",
        "PURCHASED_IN",
        product.id,
        order.id,
        "active",
        (product.record, order.record, RecordRef("revision", 1), RecordRef("item", 1)),
    )
    validate_projection(GraphProjection((product, order), (edge,)))
    for missing in (RecordRef("item", 1), RecordRef("revision", 1)):
        proof = tuple(ref for ref in edge.support if ref != missing)
        with pytest.raises(GraphReadError):
            validate_projection(
                GraphProjection(
                    (product, order),
                    (GraphEdge("x", "PURCHASED_IN", product.id, order.id, "active", proof),),
                )
            )
