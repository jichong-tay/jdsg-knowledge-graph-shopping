# ruff: noqa: E501
from contextlib import closing
from datetime import date
from uuid import uuid4

import pytest

from shopping.knowledge.models import GraphReadError, RecordRef
from shopping.knowledge.records import read_record
from shopping.knowledge.selection import read_selection
from shopping.purchases.families import create_family, propose_membership, review_membership
from shopping.purchases.family_models import PurchaseScope
from shopping.storage.connection import connect_database, transaction


def test_product_selection_has_independent_timeline(purchase_facts):
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection, immediate=False),
    ):
        result = read_selection(
            connection, RecordRef("product", 1), scope=PurchaseScope(date(2026, 9, 20))
        )
    assert result["record"].ref == RecordRef("product", 1)
    assert result["timeline"].summary is not None
    assert result["memberships"] == ()


def test_missing_record_and_non_product_cursor_are_typed(purchase_facts):
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection, immediate=False),
    ):
        with pytest.raises(GraphReadError, match="not_found"):
            read_selection(
                connection, RecordRef("product", 999999), scope=PurchaseScope(date(2026, 9, 20))
            )
        with pytest.raises(GraphReadError, match="invalid_cursor"):
            read_selection(
                connection,
                RecordRef("order", 1),
                scope=PurchaseScope(date(2026, 9, 20)),
                after_order=("2026-09-01", 1),
            )


def test_family_selection_uses_only_current_accepted_members(purchase_facts):
    scope = PurchaseScope(date(2026, 9, 20))
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection, immediate=False),
    ):
        before = read_selection(connection, RecordRef("product", 1), scope=scope)
        source = read_record(connection, RecordRef("source", 1))
        assert source is not None
        assert not {"raw_path", "sender", "subject"} & source.attributes.keys()
        assert before["record"] == read_record(connection, RecordRef("product", 1))
        assert before["record"].local_url == "/products/1"

    family = create_family(
        purchase_facts,
        command_id=uuid4().hex,
        name="Selection family",
        definition="Products 1 and 2",
    )
    first = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="first",
    )
    accepted = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=first.id,
        proposal_event_id=first.event_id,
        expected_version=first.version,
        decision="accepted",
        reason="accept",
    )
    pending = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=2,
        family_id=family.id,
        expected_version=0,
        origin="inferred",
        method="test",
        rationale="pending",
    )
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection, immediate=False),
    ):
        selected = read_selection(connection, RecordRef("family", family.id), scope=scope)
        product = read_selection(connection, RecordRef("product", 1), scope=scope)
        assert selected["timeline"].summary == product["timeline"].summary
        assert len(selected["memberships"]) == 1
        assert selected["memberships"][0]["product_id"] == 1
        assert selected["memberships"][0]["event_id"] == accepted.event_id
        assert selected["memberships"][0]["origin"] == "manual"
        assert selected["details"]["definition"] == "Products 1 and 2"

    withdrawn = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=accepted.id,
        proposal_event_id=accepted.proposal_event_id,
        expected_version=accepted.version,
        decision="withdrawn",
        reason="withdraw",
    )
    assert withdrawn.state == "withdrawn"
    with closing(connect_database(purchase_facts.database_path)) as connection:
        empty = read_selection(connection, RecordRef("family", family.id), scope=scope)
        unchanged = read_selection(connection, RecordRef("product", 1), scope=scope)
        assert empty["memberships"] == ()
        assert empty["timeline"].summary.order_count == 0
        assert empty["timeline"].summary.complete_for_scope
        assert unchanged["timeline"].summary == before["timeline"].summary
        assert all(
            not occurrence.membership_event_ids for occurrence in unchanged["timeline"].occurrences
        )

    accepted_two = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=pending.id,
        proposal_event_id=pending.event_id,
        expected_version=pending.version,
        decision="accepted",
        reason="accept second",
    )
    assert accepted_two.state == "accepted"
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection, immediate=False),
    ):
        selected_two = read_selection(connection, RecordRef("family", family.id), scope=scope)
        product_two = read_selection(connection, RecordRef("product", 2), scope=scope)
        assert selected_two["timeline"].summary == product_two["timeline"].summary
        assert [item["product_id"] for item in selected_two["memberships"]] == [2]


def test_family_selection_membership_bound_is_honest(purchase_facts):
    scope = PurchaseScope(date(2026, 9, 20))
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection),
    ):
        family = connection.execute(
            "INSERT INTO product_families(name,normalized_name,definition,created_at) VALUES(?,?,?,?)",
            ("Large family", "large-family", "Synthetic", "2026-01-01"),
        ).lastrowid
        assert family is not None
        for offset in range(500):
            product_id = 10000 + offset
            connection.execute(
                "INSERT INTO products(id,canonical_key,canonical_name,normalized_name,is_active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
                (
                    product_id,
                    f"synthetic-{product_id}",
                    f"Synthetic {product_id}",
                    f"synthetic-{product_id}",
                    "2026-01-01",
                    "2026-01-01",
                ),
            )
            membership = connection.execute(
                "INSERT INTO product_family_memberships(product_id,family_id,created_at) VALUES(?,?,?)",
                (product_id, family, "2026-01-01"),
            ).lastrowid
            proposal = connection.execute(
                "INSERT INTO product_family_events(membership_id,version,kind,origin,method,rationale,support_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (membership, 1, "proposed", "manual", "test", "synthetic", "[]", "2026-01-01"),
            ).lastrowid
            connection.execute(
                "INSERT INTO product_family_events(membership_id,version,kind,proposal_event_id,review_reason,created_at) VALUES(?,?,?,?,?,?)",
                (membership, 2, "accepted", proposal, "synthetic", "2026-01-01"),
            )
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection, immediate=False),
    ):
        bounded = read_selection(connection, RecordRef("family", family), scope=scope)
        assert len(bounded["memberships"]) == 500
        assert bounded["details"]["has_more_memberships"] is False
        assert bounded["timeline"].summary is not None
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection),
    ):
        product_id = 10500
        connection.execute(
            "INSERT INTO products(id,canonical_key,canonical_name,normalized_name,is_active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
            (
                product_id,
                f"synthetic-{product_id}",
                f"Synthetic {product_id}",
                f"synthetic-{product_id}",
                "2026-01-01",
                "2026-01-01",
            ),
        )
        membership = connection.execute(
            "INSERT INTO product_family_memberships(product_id,family_id,created_at) VALUES(?,?,?)",
            (product_id, family, "2026-01-01"),
        ).lastrowid
        proposal = connection.execute(
            "INSERT INTO product_family_events(membership_id,version,kind,origin,method,rationale,support_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (membership, 1, "proposed", "manual", "test", "synthetic", "[]", "2026-01-01"),
        ).lastrowid
        connection.execute(
            "INSERT INTO product_family_events(membership_id,version,kind,proposal_event_id,review_reason,created_at) VALUES(?,?,?,?,?,?)",
            (membership, 2, "accepted", proposal, "synthetic", "2026-01-01"),
        )
    with (
        closing(connect_database(purchase_facts.database_path)) as connection,
        transaction(connection, immediate=False),
    ):
        oversized = read_selection(connection, RecordRef("family", family), scope=scope)
        assert len(oversized["memberships"]) == 500
        assert oversized["details"]["has_more_memberships"] is True
        assert oversized["timeline"].summary is None
        assert oversized["timeline"].coverage.reason == "scope_too_large"
