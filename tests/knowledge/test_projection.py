from datetime import date
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shopping.knowledge import projection as projection_module
from shopping.knowledge.models import (
    GraphEdge,
    GraphNode,
    GraphProjection,
    GraphReadError,
    GraphReadSnapshot,
    GraphRecord,
    GraphRelation,
    GraphView,
    GraphViewRequest,
    RecordRef,
    SnapshotRef,
)
from shopping.knowledge.projection import canonical_payload, project_graph, validate_projection
from shopping.purchases.family_models import PurchaseScope


def snapshot(records=(), relations=()):
    return GraphReadSnapshot(
        SnapshotRef("a" * 32, 1),
        PurchaseScope(date(2026, 9, 20)),
        tuple(records),
        tuple(relations),
        {},
        None,
        {},
    )


def test_request_rejects_bools_bad_ids_and_extra_fields():
    with pytest.raises(ValidationError):
        GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)), page_size=True)
    with pytest.raises(ValidationError):
        GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)), selected_id="bad")
    with pytest.raises(ValidationError):
        GraphViewRequest.model_validate(
            {"purchase_scope": PurchaseScope(date(2026, 9, 20)), "unexpected": 1}
        )


def test_projection_is_deterministic_and_supports_membership():
    product = GraphRecord(RecordRef("product", 1), "Milk", {})
    family = GraphRecord(RecordRef("family", 2), "Drinks", {})
    relation = GraphRelation(
        "MEMBER_OF",
        product.ref,
        family.ref,
        support=(RecordRef("membership_event", 3), RecordRef("membership", 4)),
    )
    first = project_graph(snapshot([family, product], [relation]))
    second = project_graph(snapshot([product, family], [relation]))
    assert first == second
    assert first.edges[0].id.endswith("membership:4:membership_event:3")


def test_dangling_or_bad_predicate_is_rejected():
    projection = GraphProjection(
        (GraphNode("a" * 32 + ":product:1", "product", "p", RecordRef("product", 1), {}),),
        (GraphEdge("x", "MEMBER_OF", "a" * 32 + ":product:1", "missing", "active"),),
    )
    with pytest.raises(GraphReadError):
        validate_projection(projection)


def test_source_attributes_are_allowlisted_and_canonical_omits_build_time():
    source = GraphRecord(RecordRef("source", 1), "Source", {"id": 1, "secret": "x"})
    with pytest.raises(GraphReadError):
        project_graph(snapshot([source]))
    view = GraphView(
        SnapshotRef("a" * 32, 1),
        PurchaseScope(date(2026, 9, 20)),
        (),
        (),
        {},
        None,
        {},
        {"built_at": "one", "method": "x"},
    )
    payload = canonical_payload(view)
    assert b"one" not in payload and b'"method":"x"' in payload


@pytest.mark.parametrize(
    "scope",
    [
        PurchaseScope(cast(Any, None)),
        PurchaseScope(date(2026, 9, 20), date(2026, 9, 21)),
        PurchaseScope(date(2026, 9, 20), end_date=date(2026, 9, 21)),
    ],
)
def test_request_rejects_invalid_scopes(scope):
    with pytest.raises(ValidationError):
        GraphViewRequest.model_validate({"purchase_scope": scope})


@pytest.mark.parametrize("mutation", ["prefix", "row_id", "state", "support"])
def test_projection_rejects_independent_guard_failures(mutation):
    product = GraphNode("a" * 32 + ":product:1", "product", "p", RecordRef("product", 1), {})
    family = GraphNode("a" * 32 + ":family:2", "family", "f", RecordRef("family", 2), {})
    if mutation == "prefix":
        product = GraphNode("b" * 32 + ":product:1", "product", "p", product.record, {})
    if mutation == "row_id":
        product = GraphNode(
            "a" * 32 + ":product:9223372036854775808",
            "product",
            "p",
            RecordRef("product", 9223372036854775808),
            {},
        )
    edge = GraphEdge(
        "e",
        "MEMBER_OF",
        product.id,
        family.id,
        "active",
        (RecordRef("membership", 1), RecordRef("membership_event", 2)),
    )
    if mutation == "state":
        edge = GraphEdge(
            edge.id, edge.type, edge.source, edge.target, cast(Any, "bad"), edge.support
        )
    if mutation == "support":
        edge = GraphEdge(
            edge.id, edge.type, edge.source, edge.target, edge.state, (RecordRef("membership", 1),)
        )
    with pytest.raises(GraphReadError):
        validate_projection(GraphProjection((product, family), (edge,)))


def test_projection_caps_nodes_and_edges():
    nodes = tuple(
        GraphNode(
            f"{'a' * 32}:product:{index}",
            "product",
            "p",
            RecordRef("product", index),
            {},
        )
        for index in range(1, 202)
    )
    with pytest.raises(GraphReadError, match="scope_too_large"):
        validate_projection(GraphProjection(nodes, ()))


def test_canonical_view_permutations_and_json_request(monkeypatch):
    request = GraphViewRequest.model_validate_json(
        '{"purchase_scope":{"analysis_date":"2026-09-20"}}'
    )
    assert request.purchase_scope.analysis_date == date(2026, 9, 20)
    with pytest.raises(ValidationError):
        GraphViewRequest.model_validate_json(
            '{"purchase_scope":{"analysis_date":"2026-09-20"},"page_size":true}'
        )
    product1 = GraphRecord(RecordRef("product", 1), "P1", {})
    product2 = GraphRecord(RecordRef("product", 2), "P2", {})
    family = GraphRecord(RecordRef("family", 3), "F", {})
    relations = (
        GraphRelation(
            "MEMBER_OF",
            product1.ref,
            family.ref,
            support=(RecordRef("membership_event", 2), RecordRef("membership", 1)),
        ),
        GraphRelation(
            "MEMBER_OF",
            product2.ref,
            family.ref,
            support=(RecordRef("membership_event", 4), RecordRef("membership", 3)),
        ),
    )
    projection = project_graph(snapshot((product1, product2, family), relations))
    view1 = GraphView(
        SnapshotRef("a" * 32, 1),
        PurchaseScope(date(2026, 9, 20)),
        projection.nodes,
        projection.edges,
        {},
        None,
        {},
        {"built_at": "one", "method": "x"},
    )
    view2 = GraphView(
        view1.snapshot,
        view1.scope,
        tuple(reversed(view1.nodes)),
        tuple(
            GraphEdge(e.id, e.type, e.source, e.target, e.state, tuple(reversed(e.support)))
            for e in reversed(view1.edges)
        ),
        view1.page,
        view1.selection,
        view1.coverage,
        {"built_at": "two", "method": "x"},
    )
    payload = canonical_payload(view1)
    assert payload == canonical_payload(view2)
    monkeypatch.setattr(projection_module, "MAX_JSON_BYTES", len(payload) - 1)
    with pytest.raises(GraphReadError, match="scope_too_large"):
        canonical_payload(view1)
