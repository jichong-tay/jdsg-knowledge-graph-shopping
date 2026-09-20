# ruff: noqa: E501
from contextlib import closing
from datetime import date
from uuid import uuid4

from shopping.knowledge.models import PREDICATES, RecordRef
from shopping.knowledge.relationships import read_relations, relation_key
from shopping.purchases.families import create_family, propose_membership, review_membership
from shopping.purchases.family_models import PurchaseScope
from shopping.storage.connection import connect_database, transaction


def test_order_and_revision_neighbors(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c:
        rows = read_relations(
            c, RecordRef("order", 1), mode="current", scope=PurchaseScope(date(2026, 9, 20))
        )
    assert {r.type for r in rows} >= {"ORDERED_FROM", "CURRENT_REVISION"}


def test_keyset_limit(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c:
        rows = read_relations(
            c,
            RecordRef("order", 1),
            mode="current",
            scope=PurchaseScope(date(2026, 9, 20)),
            limit=1,
        )
        again = read_relations(
            c,
            RecordRef("order", 1),
            mode="current",
            scope=PurchaseScope(date(2026, 9, 20)),
            after=relation_key(rows[0]),
            limit=1,
        )
    assert not set(map(relation_key, rows)) & set(map(relation_key, again))


def test_membership_transition_current_and_history(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Relations", definition="test"
    )
    proposal = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="test",
    )
    accepted = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=proposal.id,
        proposal_event_id=proposal.event_id,
        expected_version=1,
        decision="accepted",
        reason="test",
    )
    with closing(connect_database(purchase_facts.database_path)) as c:
        scope = PurchaseScope(date(2026, 9, 20))
        product = tuple(
            r
            for r in read_relations(c, RecordRef("product", 1), mode="current", scope=scope)
            if r.type == "MEMBER_OF"
        )
        family_rows = read_relations(c, RecordRef("family", family.id), mode="current", scope=scope)
        assert product == family_rows and product[0].support[-1].row_id == accepted.event_id
    review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=proposal.id,
        proposal_event_id=proposal.event_id,
        expected_version=2,
        decision="withdrawn",
        reason="test",
    )
    with closing(connect_database(purchase_facts.database_path)) as c:
        current_product = read_relations(
            c, RecordRef("product", 1), mode="current", scope=PurchaseScope(date(2026, 9, 20))
        )
        history_product = tuple(
            r
            for r in read_relations(
                c, RecordRef("product", 1), mode="history", scope=PurchaseScope(date(2026, 9, 20))
            )
            if r.type == "MEMBER_OF"
        )
    assert not any(r.type == "MEMBER_OF" for r in current_product)
    assert len(history_product) == 1 and history_product[0].state == "inactive"
    assert any(r.row_id == accepted.event_id for r in history_product[0].support)


def test_all_predicates_and_reverse_roots(purchase_facts):
    family = create_family(purchase_facts, command_id=uuid4().hex, name="All", definition="test")
    proposal = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="test",
    )
    review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=proposal.id,
        proposal_event_id=proposal.event_id,
        expected_version=1,
        decision="accepted",
        reason="test",
    )
    scope = PurchaseScope(date(2026, 9, 20))
    roots = (
        ("order", 1),
        ("revision", 1),
        ("item", 1),
        ("listing", 1),
        ("product", 1),
        ("family", family.id),
        ("retailer", 1),
        ("source", 1),
    )
    expected = {
        "order": {"CURRENT_REVISION", "HAS_REVISION", "ORDERED_FROM"},
        "revision": {"CURRENT_REVISION", "HAS_REVISION", "HAS_ITEM", "SUPPORTED_BY"},
        "item": {"HAS_ITEM", "REFERS_TO_LISTING"},
        "listing": {"LISTED_BY", "MAPS_TO_PRODUCT", "REFERS_TO_LISTING"},
        "product": {"MAPS_TO_PRODUCT", "MEMBER_OF"},
        "family": {"MEMBER_OF"},
        "retailer": {"ORDERED_FROM", "LISTED_BY"},
        "source": {"SUPPORTED_BY"},
    }
    with closing(connect_database(purchase_facts.database_path)) as c:
        for kind, row_id in roots:
            rows = read_relations(c, RecordRef(kind, row_id), mode="current", scope=scope)
            assert expected[kind] <= {r.type for r in rows}
            for relation in rows:
                assert relation.source.entity_type == kind or relation.target.entity_type == kind
                root = relation.source if relation.source.entity_type == kind else relation.target
                other = relation.target if root == relation.source else relation.source
                assert root == RecordRef(kind, row_id)
                assert other.entity_type in PREDICATES[relation.type].get(
                    relation.source.entity_type, set()
                ) or relation.target.entity_type in PREDICATES[relation.type].get(
                    relation.source.entity_type, set()
                )
                assert relation.support
        current = read_relations(c, RecordRef("order", 1), mode="current", scope=scope)
        history = read_relations(c, RecordRef("order", 1), mode="history", scope=scope)
    assert any(r.type == "HAS_REVISION" and r.target.row_id == 5 for r in history)
    assert not any(r.type == "HAS_REVISION" and r.target.row_id == 5 for r in current)


def test_sources_union_and_explicit_date_filter(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        wrapper = int(c.execute("SELECT coalesce(max(id),0)+1 FROM email_messages").fetchone()[0])
        c.execute(
            "INSERT INTO email_messages (id,source_kind,source_message_key,source_fingerprint,sender,subject,received_at,raw_sha256,raw_path,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                wrapper,
                "manual",
                "wrapper@example.invalid",
                "wrapper-fingerprint",
                "source@example.invalid",
                "Wrapper",
                "2026-01-01T00:00:00+00:00",
                "wrapper-sha",
                "/tmp/wrapper.eml",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        c.execute("INSERT INTO order_revision_sources VALUES (1,?, '2026-01-01')", (wrapper,))
    with closing(connect_database(purchase_facts.database_path)) as c:
        scope = PurchaseScope(date(2026, 9, 20))
        edges = read_relations(c, RecordRef("revision", 1), mode="current", scope=scope)
        sources = {r.target.row_id for r in edges if r.type == "SUPPORTED_BY"}
        assert sources == {1, wrapper}
        reverse = read_relations(c, RecordRef("source", wrapper), mode="current", scope=scope)
        assert any(
            r.type == "SUPPORTED_BY" and r.source.row_id == 1 and r.target.row_id == wrapper
            for r in reverse
        )
        jan11 = read_relations(
            c,
            RecordRef("listing", 1),
            mode="current",
            scope=PurchaseScope(date(2026, 9, 20), date(2026, 1, 11), date(2026, 1, 11)),
        )
        february = read_relations(
            c,
            RecordRef("listing", 1),
            mode="current",
            scope=PurchaseScope(date(2026, 9, 20), date(2026, 2, 1), date(2026, 2, 1)),
        )
        item_revision = {
            int(row[0]): int(row[1])
            for row in c.execute(
                "SELECT id,order_revision_id FROM order_items WHERE retailer_product_id=1"
            )
        }
        assert {item_revision[r.source.row_id] for r in jan11 if r.type == "REFERS_TO_LISTING"} == {
            2,
            4,
        }  # Imported revision 1 has a 12 Jan Singapore delivery date.
        assert {
            item_revision[r.source.row_id] for r in february if r.type == "REFERS_TO_LISTING"
        } == {2}
        supported = [r for r in edges if r.type == "SUPPORTED_BY"]
        assert all(r.support for r in supported)
        assert all(
            RecordRef("revision", r.source.row_id) in r.support
            and RecordRef("source", r.target.row_id) in r.support
            for r in supported
        )
    assert {r.type for r in jan11} >= {"MAPS_TO_PRODUCT", "LISTED_BY"}
    assert {r.type for r in february} >= {"MAPS_TO_PRODUCT", "LISTED_BY"}
