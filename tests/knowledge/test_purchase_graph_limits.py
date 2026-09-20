from contextlib import closing
from datetime import date, timedelta

from shopping.knowledge.models import GraphViewRequest
from shopping.knowledge.records import product_purchase_counts
from shopping.knowledge.snapshot import read_graph_view
from shopping.purchases.family_models import (
    PurchaseScope,
    TimelineCoverage,
    TimelinePage,
    TimelinePageInfo,
)
from shopping.storage.connection import connect_database, transaction


def test_count_batch_accepts_one_hundred_existing_products(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        for product_id in range(1000, 1100):
            c.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    product_id,
                    f"synthetic-{product_id}",
                    f"Synthetic {product_id}",
                    f"synthetic {product_id}",
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
    with closing(connect_database(purchase_facts.database_path)) as c:
        result = product_purchase_counts(
            c, tuple(range(1000, 1100)), PurchaseScope(date(2026, 9, 20))
        )
    assert len(result) == 100 and set(result.values()) == {0}


def test_expanded_order_adds_product_count_even_when_query_has_no_roots(purchase_facts):
    base = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    order_id = 1
    request = GraphViewRequest(
        query="no-match",
        expanded_ids=(f"{base.snapshot.dataset_id}:order:{order_id}",),
        purchase_scope=PurchaseScope(date(2026, 9, 20)),
    )
    view = read_graph_view(purchase_facts, request)
    products = [node for node in view.nodes if node.type == "product"]
    assert products and all("purchase_count" in node.attributes for node in products)


def test_selected_hidden_product_keeps_count_when_timeline_is_unavailable(
    purchase_facts, monkeypatch
):
    import shopping.knowledge.selection as selection

    monkeypatch.setattr(
        selection,
        "read_timeline",
        lambda *args, **kwargs: TimelinePage(
            None,
            (),
            TimelineCoverage(False, None, None, None, None, None, "scope_too_large"),
            TimelinePageInfo(False, None),
        ),
    )
    base = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    view = read_graph_view(
        purchase_facts,
        GraphViewRequest(
            selected_id=f"{base.snapshot.dataset_id}:product:1",
            node_types=("order",),
            purchase_scope=PurchaseScope(date(2026, 9, 20)),
        ),
    )
    assert view.selection is not None
    assert view.selection["node"].attributes["purchase_count"] == 3


def test_purchase_edges_page_over_sixty_orders_without_duplicates(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        for oid in range(100, 161):
            delivery = (
                date(2026, 2, 1) + timedelta(days=oid - 100)
            ).isoformat() + "T00:00:00+00:00"
            c.execute(
                "INSERT INTO orders VALUES (?,1,?,'2026-01-01T00:00:00+00:00')",
                (oid, f"SYNTH-{oid}"),
            )
            c.execute(
                "INSERT INTO order_revisions (id,order_id,email_message_id,revision_number,"
                "revision_kind,revision_fingerprint,parser_version,source_event_at,ordered_at,"
                "delivery_at,currency,"
                "total_cents,status,created_at) VALUES (?,?,1,1,'confirmation',?,'synthetic',"
                "'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',?,'SGD',1,'placed',"
                "'2026-01-01T00:00:00+00:00')",
                (oid, oid, f"synthetic-{oid}", delivery),
            )
            c.execute(
                "INSERT INTO order_items (order_revision_id,line_number,line_fingerprint,"
                "retailer_product_id,raw_name,quantity,unit,net_cents,created_at) VALUES "
                "(?,1,?,1,'synthetic',1,'each',1,'2026-01-01T00:00:00+00:00')",
                (oid, f"synthetic-item-{oid}"),
            )
    base = read_graph_view(
        purchase_facts, GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    )
    pid = f"{base.snapshot.dataset_id}:product:1"
    request = GraphViewRequest(expanded_ids=(pid,), purchase_scope=PurchaseScope(date(2026, 9, 20)))
    seen = set()
    while True:
        view = read_graph_view(purchase_facts, request)
        page_targets = {
            edge.target.split(":")[-1] for edge in view.edges if edge.type == "PURCHASED_IN"
        }
        assert seen.isdisjoint(page_targets)
        product_node = next(node for node in view.nodes if node.type == "product")
        assert product_node.attributes["purchase_count"] == 64
        seen |= page_targets
        page = view.page["relationships"][pid]
        if not page["has_more"]:
            break
        request = request.model_copy(update={"relationship_cursors": {pid: page["cursor"]}})
    assert {int(value) for value in seen} == set(range(100, 161)) | {1, 3, 4}
