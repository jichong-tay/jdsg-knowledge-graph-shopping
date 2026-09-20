from contextlib import closing
from datetime import date

import pytest

from shopping.knowledge.models import GraphReadError, GraphViewRequest
from shopping.knowledge.projection import canonical_payload
from shopping.knowledge.snapshot import read_graph_view
from shopping.purchases.family_models import PurchaseScope
from shopping.storage.connection import connect_database, transaction


def test_graph_view_reads_overview(purchase_facts):
    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    view = read_graph_view(purchase_facts, request)
    assert view.snapshot.dataset_id
    assert view.nodes


def test_expected_snapshot_stales_after_revision_change(purchase_facts):
    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    first = read_graph_view(purchase_facts, request)
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        c.execute("UPDATE order_revisions SET is_current=0 WHERE id=1")
    with pytest.raises(GraphReadError, match="stale_snapshot"):
        read_graph_view(purchase_facts, request, expected_snapshot=first.snapshot)


def test_overview_cursor_continuation(purchase_facts):
    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)), page_size=1)
    first = read_graph_view(purchase_facts, request)
    assert first.page["overview"]["has_more"]
    second_request = request.model_copy(
        update={"overview_cursor": first.page["overview"]["cursor"]}
    )
    second = read_graph_view(purchase_facts, second_request)
    assert not second.page["overview"]["has_more"]
    assert {node.id for node in first.nodes}.isdisjoint({node.id for node in second.nodes})


def test_overview_cursor_filter_change_is_invalid(purchase_facts):
    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)), page_size=1)
    first = read_graph_view(purchase_facts, request)
    changed = request.model_copy(
        update={"query": "different", "overview_cursor": first.page["overview"]["cursor"]}
    )
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        read_graph_view(purchase_facts, changed)


def test_foreign_selected_id_is_stale(purchase_facts):
    request = GraphViewRequest(
        selected_id="0" * 32 + ":product:1", purchase_scope=PurchaseScope(date(2026, 9, 20))
    )
    with pytest.raises(GraphReadError, match="stale_snapshot"):
        read_graph_view(purchase_facts, request)


def test_expanded_revision_contains_item_and_source_endpoints(purchase_facts):
    base = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    initial = read_graph_view(purchase_facts, base)
    request = base.model_copy(
        update={"expanded_ids": (f"{initial.snapshot.dataset_id}:revision:1",)}
    )
    view = read_graph_view(purchase_facts, request)
    endpoint_types = {node.type for node in view.nodes}
    assert {"revision", "item", "source"} <= endpoint_types


def test_selected_product_timeline_survives_hidden_canvas_type(purchase_facts):
    base = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)), selected_id=None)
    initial = read_graph_view(purchase_facts, base)
    product_id = f"{initial.snapshot.dataset_id}:product:1"
    visible = read_graph_view(purchase_facts, base.model_copy(update={"selected_id": product_id}))
    hidden = read_graph_view(
        purchase_facts,
        base.model_copy(update={"selected_id": product_id, "node_types": ("family",)}),
    )
    assert visible.selection is not None and hidden.selection is not None
    assert visible.selection["timeline"].summary == hidden.selection["timeline"].summary
    assert hidden.selection["node"].record.entity_type == "product"


def test_relationship_pagination_dense_revision(purchase_facts):
    base = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    initial = read_graph_view(purchase_facts, base)
    product = f"{initial.snapshot.dataset_id}:product:1"
    baseline = read_graph_view(purchase_facts, base.model_copy(update={"selected_id": product}))
    root = f"{initial.snapshot.dataset_id}:revision:3"
    request = base.model_copy(update={"selected_id": product, "expanded_ids": (root,)})
    first = read_graph_view(purchase_facts, request)
    assert len(first.edges) == 60
    assert first.page["relationships"][root]["has_more"]
    assert first.page["relationships"][root]["reason"] == "relationship_limit"
    cursor = first.page["relationships"][root]["cursor"]
    second = read_graph_view(
        purchase_facts, request.model_copy(update={"relationship_cursors": {root: cursor}})
    )
    first_edges = {edge.id for edge in first.edges}
    second_edges = {edge.id for edge in second.edges}
    assert first_edges.isdisjoint(second_edges)
    assert not second.page["relationships"][root]["has_more"]
    assert (
        first.selection is not None
        and second.selection is not None
        and baseline.selection is not None
    )
    assert first.selection["timeline"].summary == baseline.selection["timeline"].summary
    assert second.selection["timeline"].summary == baseline.selection["timeline"].summary
    assert first_edges | second_edges
    assert all(
        edge.source in {node.id for node in first.nodes}
        and edge.target in {node.id for node in first.nodes}
        for edge in first.edges
    )
    assert all(
        edge.source in {node.id for node in second.nodes}
        and edge.target in {node.id for node in second.nodes}
        for edge in second.edges
    )


def test_graph_caps_keep_edges_dangling_free(purchase_facts, monkeypatch):
    import shopping.knowledge.snapshot as snapshot

    base = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    initial = read_graph_view(purchase_facts, base)
    product = f"{initial.snapshot.dataset_id}:product:1"
    baseline = read_graph_view(purchase_facts, base.model_copy(update={"selected_id": product}))
    root = f"{initial.snapshot.dataset_id}:revision:1"
    monkeypatch.setattr(snapshot, "MAX_NODES", 4)
    view = read_graph_view(
        purchase_facts, base.model_copy(update={"selected_id": product, "expanded_ids": (root,)})
    )
    assert len(view.nodes) <= 4
    node_ids = {node.id for node in view.nodes}
    assert all(edge.source in node_ids and edge.target in node_ids for edge in view.edges)
    assert view.coverage["partial"] and "node_limit" in view.coverage["reasons"]
    assert view.page["relationships"][root]["has_more"]
    assert view.selection is not None and baseline.selection is not None
    assert view.selection["timeline"].summary == baseline.selection["timeline"].summary


def test_graph_edge_cap_keeps_endpoints_and_selection(purchase_facts, monkeypatch):
    import shopping.knowledge.snapshot as snapshot

    base = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    initial = read_graph_view(purchase_facts, base)
    product = f"{initial.snapshot.dataset_id}:product:1"
    baseline = read_graph_view(purchase_facts, base.model_copy(update={"selected_id": product}))
    root = f"{initial.snapshot.dataset_id}:revision:1"
    monkeypatch.setattr(snapshot, "MAX_EDGES", 1)
    view = read_graph_view(
        purchase_facts, base.model_copy(update={"selected_id": product, "expanded_ids": (root,)})
    )
    assert (
        len(view.edges) == 1
        and view.coverage["partial"]
        and "edge_limit" in view.coverage["reasons"]
    )
    assert view.page["relationships"][root]["has_more"]
    node_ids = {node.id for node in view.nodes}
    assert all(edge.source in node_ids and edge.target in node_ids for edge in view.edges)
    assert view.selection is not None and baseline.selection is not None
    assert view.selection["timeline"].summary == baseline.selection["timeline"].summary


def test_essential_budget_and_byte_cap(purchase_facts, monkeypatch):
    import shopping.knowledge.snapshot as snapshot

    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    monkeypatch.setattr(snapshot, "PROGRESS_INTERVAL", 1)
    monkeypatch.setattr(snapshot, "MAX_VM_STEPS", 1)
    with pytest.raises(GraphReadError, match="scope_too_large"):
        read_graph_view(purchase_facts, request)
    monkeypatch.setattr(snapshot, "MAX_VM_STEPS", 2_000_000)
    assert read_graph_view(purchase_facts, request).nodes
    monkeypatch.setattr(snapshot, "MAX_JSON_BYTES", 100)
    with pytest.raises(GraphReadError, match="scope_too_large"):
        read_graph_view(purchase_facts, request)


def test_source_changes_stale_snapshot_and_canonical_reads(purchase_facts):
    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    first = read_graph_view(purchase_facts, request)
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        c.execute("UPDATE retailer_products SET match_method='manual' WHERE id=1")
    with pytest.raises(GraphReadError, match="stale_snapshot"):
        read_graph_view(purchase_facts, request, expected_snapshot=first.snapshot)
    second = read_graph_view(purchase_facts, request)
    third = read_graph_view(purchase_facts, request)
    assert canonical_payload(second) == canonical_payload(third)


def test_missing_selected_record_is_not_found(purchase_facts):
    initial = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    request = GraphViewRequest(
        selected_id=f"{initial.snapshot.dataset_id}:product:99999",
        purchase_scope=PurchaseScope(date(2026, 9, 20)),
    )
    with pytest.raises(GraphReadError, match="not_found"):
        read_graph_view(purchase_facts, request)


def test_rolled_back_write_keeps_snapshot_and_payload(purchase_facts):
    request = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    before = read_graph_view(purchase_facts, request)
    with closing(connect_database(purchase_facts.database_path)) as c:
        try:
            with transaction(c):
                c.execute("UPDATE products SET canonical_name='temporary' WHERE id=1")
                raise ValueError("deliberate rollback")
        except ValueError:
            pass
    after = read_graph_view(purchase_facts, request, expected_snapshot=before.snapshot)
    assert canonical_payload(before) == canonical_payload(after)


def test_history_expansion_adds_old_revision_without_timeline_change(purchase_facts):
    initial = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    product = f"{initial.snapshot.dataset_id}:product:1"
    root = f"{initial.snapshot.dataset_id}:order:1"
    scope = PurchaseScope(date(2026, 9, 20))
    current = read_graph_view(
        purchase_facts,
        GraphViewRequest(
            selected_id=product, expanded_ids=(root,), mode="current", purchase_scope=scope
        ),
    )
    history = read_graph_view(
        purchase_facts,
        GraphViewRequest(
            selected_id=product, expanded_ids=(root,), mode="history", purchase_scope=scope
        ),
    )
    assert current.selection is not None and history.selection is not None
    assert current.selection["timeline"].summary == history.selection["timeline"].summary
    current_ids = {node.record.row_id for node in current.nodes if node.type == "revision"}
    history_ids = {node.record.row_id for node in history.nodes if node.type == "revision"}
    assert 5 not in current_ids and 5 in history_ids


def test_graph_read_snapshot_is_stable_during_writer(purchase_facts, monkeypatch):
    import threading

    import shopping.knowledge.snapshot as snapshot

    scope = PurchaseScope(date(2026, 9, 20))
    baseline_request = GraphViewRequest(purchase_scope=scope, selected_id=None)
    initial = read_graph_view(purchase_facts, baseline_request)
    root = f"{initial.snapshot.dataset_id}:revision:1"
    request = baseline_request.model_copy(update={"selected_id": None, "expanded_ids": (root,)})
    baseline = read_graph_view(purchase_facts, request)
    updated = threading.Event()
    errors: list[BaseException] = []
    threads: list[threading.Thread] = []

    original = snapshot.read_roots

    def wrapped(connection, **kwargs):
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        writer_done = threading.Event()

        def writer():
            try:
                with closing(connect_database(purchase_facts.database_path)) as writer_connection:
                    with transaction(writer_connection):
                        writer_connection.execute(
                            "UPDATE order_items SET quantity=quantity+1 WHERE id=1"
                        )
                        updated.set()
            except BaseException as exc:
                errors.append(exc)
            finally:
                writer_done.set()

        thread = threading.Thread(target=writer)
        threads.append(thread)
        thread.start()
        assert updated.wait(2)
        result = original(connection, **kwargs)
        return result

    monkeypatch.setattr(snapshot, "read_roots", wrapped)
    try:
        concurrent = read_graph_view(purchase_facts, request, expected_snapshot=baseline.snapshot)
    finally:
        monkeypatch.setattr(snapshot, "read_roots", original)
    for thread in threads:
        thread.join(2)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert canonical_payload(concurrent) == canonical_payload(baseline)
    fresh = read_graph_view(purchase_facts, request)
    assert fresh.snapshot.source_generation != baseline.snapshot.source_generation
    assert canonical_payload(fresh) != canonical_payload(baseline)


def test_dense_expansions_hit_global_node_cap(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        next_id = int(c.execute("SELECT coalesce(max(id),0)+1 FROM order_items").fetchone()[0])
        for revision in (1, 2, 4):
            current = int(
                c.execute(
                    (
                        "SELECT coalesce(max(line_number),0) FROM order_items "
                        "WHERE order_revision_id=?"
                    ),
                    (revision,),
                ).fetchone()[0]
            )
            for line in range(current + 1, 61):
                c.execute(
                    (
                        "INSERT INTO order_items "
                        "(id,order_revision_id,line_number,line_fingerprint,retailer_product_id,"
                        "raw_name,quantity,unit,net_cents,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)"
                    ),
                    (
                        next_id,
                        revision,
                        line,
                        f"dense-{revision}-{line}",
                        1,
                        "Synthetic",
                        1,
                        "item",
                        100,
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                next_id += 1
    initial = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    product = f"{initial.snapshot.dataset_id}:product:1"
    roots = tuple(f"{initial.snapshot.dataset_id}:revision:{revision}" for revision in (1, 2, 3, 4))
    request = GraphViewRequest(
        selected_id=product, expanded_ids=roots, purchase_scope=PurchaseScope(date(2026, 9, 20))
    )
    baseline = read_graph_view(
        purchase_facts,
        GraphViewRequest(selected_id=product, purchase_scope=PurchaseScope(date(2026, 9, 20))),
    )
    view = read_graph_view(purchase_facts, request)
    assert len(view.nodes) <= 200
    assert view.coverage["partial"] and "node_limit" in view.coverage["reasons"]
    node_ids = {node.id for node in view.nodes}
    assert all(edge.source in node_ids and edge.target in node_ids for edge in view.edges)
    assert any(info["reason"] == "node_limit" for info in view.page["relationships"].values())
    assert view.selection is not None and baseline.selection is not None
    assert view.selection["timeline"].summary == baseline.selection["timeline"].summary


def test_dense_family_edges_hit_global_edge_cap(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        for pid in range(1000, 1012):
            c.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    f"dense-product-{pid}",
                    f"Dense Product {pid}",
                    f"dense product {pid}",
                    None,
                    None,
                    None,
                    None,
                    None,
                    1,
                    "2026-01-01",
                    "2026-01-01",
                ),
            )
        for fid in range(1000, 1040):
            c.execute(
                "INSERT INTO product_families VALUES (?,?,?,?,?)",
                (fid, f"Dense Family {fid}", f"dense-family-{fid}", "Dense", "2026-01-01"),
            )
        event = 10000
        membership = 1000
        for pid in range(1000, 1012):
            for fid in range(1000, 1040):
                c.execute(
                    "INSERT INTO product_family_memberships VALUES (?,?,?,?)",
                    (membership, pid, fid, "2026-01-01"),
                )
                c.execute(
                    (
                        "INSERT INTO product_family_events "
                        "(id,membership_id,version,kind,origin,method,rationale,"
                        "support_json,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)"
                    ),
                    (
                        event,
                        membership,
                        1,
                        "proposed",
                        "manual",
                        "synthetic",
                        "synthetic",
                        "[]",
                        "2026-01-01",
                    ),
                )
                c.execute(
                    (
                        "INSERT INTO product_family_events "
                        "(id,membership_id,version,kind,proposal_event_id,review_reason,"
                        "created_at) "
                        "VALUES (?,?,?,?,?,?,?)"
                    ),
                    (event + 1, membership, 2, "accepted", event, "synthetic", "2026-01-01"),
                )
                membership += 1
                event += 2
    initial = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    roots = tuple(f"{initial.snapshot.dataset_id}:product:{pid}" for pid in range(1000, 1012))
    view = read_graph_view(
        purchase_facts,
        GraphViewRequest(expanded_ids=roots, purchase_scope=PurchaseScope(date(2026, 9, 20))),
    )
    assert len(view.edges) == 400
    assert view.coverage["partial"] and "edge_limit" in view.coverage["reasons"]
    assert any(
        info["reason"] == "edge_limit" and info["has_more"]
        for info in view.page["relationships"].values()
    )
    node_ids = {node.id for node in view.nodes}
    assert all(edge.source in node_ids and edge.target in node_ids for edge in view.edges)


def test_optional_coverage_interrupt_preserves_timeline(purchase_facts, monkeypatch):
    import shopping.purchases.timelines as timelines

    initial = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    product = f"{initial.snapshot.dataset_id}:product:1"
    root = f"{initial.snapshot.dataset_id}:revision:1"
    request = GraphViewRequest(
        selected_id=product, expanded_ids=(root,), purchase_scope=PurchaseScope(date(2026, 9, 20))
    )
    baseline = read_graph_view(purchase_facts, request)
    original = timelines._coverage

    def interrupted(connection, product_ids, scope):
        connection.set_progress_handler(lambda: 1, 1)
        return original(connection, product_ids, scope)

    monkeypatch.setattr(timelines, "_coverage", interrupted)
    interrupted_view = read_graph_view(purchase_facts, request)
    assert interrupted_view.selection is not None and baseline.selection is not None
    assert interrupted_view.selection["timeline"].summary == baseline.selection["timeline"].summary
    assert (
        interrupted_view.selection["timeline"].occurrences
        == baseline.selection["timeline"].occurrences
    )
    coverage = interrupted_view.selection["timeline"].coverage
    assert not coverage.counts_complete and coverage.reason == "coverage_budget"
    assert coverage.eligible_order_count is None
    assert interrupted_view.snapshot.source_generation == baseline.snapshot.source_generation
    monkeypatch.setattr(timelines, "_coverage", original)
    normal = read_graph_view(purchase_facts, request)
    assert normal.selection is not None
    assert normal.selection["timeline"].coverage.counts_complete
