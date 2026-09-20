from typing import Any, cast
from uuid import uuid4

import pytest

from shopping.knowledge import reviews as reviews_module
from shopping.knowledge.models import GraphReadError
from shopping.knowledge.reviews import read_reviews
from shopping.purchases.families import create_family, propose_membership, review_membership


def test_review_lifecycle_modes_and_provenance(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Reviews", definition="Products"
    )
    proposal = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="first",
    )
    accepted = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=proposal.id,
        proposal_event_id=proposal.event_id,
        expected_version=1,
        decision="accepted",
        reason="yes",
    )
    withdrawn = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=accepted.id,
        proposal_event_id=proposal.event_id,
        expected_version=2,
        decision="withdrawn",
        reason="change",
    )
    reproposed = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=3,
        origin="inferred",
        method="new",
        rationale="second",
    )
    pending = read_reviews(purchase_facts, mode="pending", family_id=family.id)
    assert len(pending["entries"]) == 1
    assert pending["entries"][0]["event_id"] == reproposed.event_id
    assert pending["entries"][0]["actions"] == ("accepted", "rejected")
    current = read_reviews(purchase_facts, mode="current", family_id=family.id)
    assert len(current["entries"]) == 1 and current["entries"][0]["state"] == "pending"
    history = read_reviews(purchase_facts, mode="history", family_id=family.id)
    assert [entry["event_id"] for entry in history["entries"]] == [
        proposal.event_id,
        accepted.event_id,
        withdrawn.event_id,
        reproposed.event_id,
    ]
    assert history["entries"][1]["review_reason"] == "yes"
    assert history["entries"][2]["actions"] == ()
    page = read_reviews(purchase_facts, mode="history", family_id=family.id, limit=1)
    all_entries = list(page["entries"])
    while page["page"]["cursor"] is not None:
        page = read_reviews(
            purchase_facts,
            mode="history",
            family_id=family.id,
            limit=1,
            cursor=page["page"]["cursor"],
        )
        all_entries.extend(page["entries"])
    assert [entry["event_id"] for entry in all_entries] == [
        proposal.event_id,
        accepted.event_id,
        withdrawn.event_id,
        reproposed.event_id,
    ]
    assert all(entry["actions"] == () for entry in all_entries[:3])
    assert all_entries[3]["actions"] == ("accepted", "rejected")


def test_history_unfiltered_and_pending_cursor_filters(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Cursor reviews", definition="Products"
    )
    first = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="one",
    )
    second = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=2,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="two",
    )
    pending = read_reviews(purchase_facts, mode="pending", family_id=family.id, limit=1)
    assert pending["page"]["has_more"]
    next_page = read_reviews(
        purchase_facts,
        mode="pending",
        family_id=family.id,
        limit=1,
        cursor=pending["page"]["cursor"],
    )
    assert {pending["entries"][0]["product_id"], next_page["entries"][0]["product_id"]} == {1, 2}
    assert read_reviews(purchase_facts, mode="history")["entries"]
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        read_reviews(
            purchase_facts,
            mode="current",
            family_id=family.id,
            limit=1,
            cursor=pending["page"]["cursor"],
        )
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        read_reviews(
            purchase_facts,
            mode="pending",
            family_id=family.id,
            limit=2,
            cursor=pending["page"]["cursor"],
        )
    accepted = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=first.id,
        proposal_event_id=first.event_id,
        expected_version=1,
        decision="accepted",
        reason="yes",
    )
    with pytest.raises(GraphReadError, match="stale_snapshot"):
        read_reviews(
            purchase_facts,
            mode="pending",
            family_id=family.id,
            limit=1,
            cursor=pending["page"]["cursor"],
        )
    assert accepted.state == "accepted" and second.product_id == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": []},
        {"mode": True},
        {"limit": True},
        {"limit": 0},
        {"limit": 51},
        {"family_id": True},
        {"family_id": 999999},
    ],
)
def test_review_input_validation(purchase_facts, kwargs):
    with pytest.raises(GraphReadError):
        cast(Any, read_reviews)(purchase_facts, **kwargs)


def test_review_error_codes_and_cursor_filtering(purchase_facts):
    with pytest.raises(GraphReadError, match="not_found"):
        read_reviews(purchase_facts, family_id=999999)
    with pytest.raises(GraphReadError, match="invalid_input"):
        cast(Any, read_reviews)(purchase_facts, mode=[])
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        read_reviews(purchase_facts, cursor="!")
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Filter", definition="Products"
    )
    propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="one",
    )
    propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=2,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="two",
    )
    page = read_reviews(purchase_facts, family_id=family.id, limit=1)
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        read_reviews(purchase_facts, family_id=None, cursor=page["page"]["cursor"])


def test_review_budget_and_byte_caps(purchase_facts, monkeypatch):
    monkeypatch.setattr(reviews_module, "PROGRESS_INTERVAL", 1)
    monkeypatch.setattr(reviews_module, "MAX_OPS", 1)
    with pytest.raises(GraphReadError, match="scope_too_large"):
        read_reviews(purchase_facts)
    monkeypatch.setattr(reviews_module, "MAX_OPS", 2_000_000)
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Budget", definition="Products"
    )
    propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="budget",
    )
    assert read_reviews(purchase_facts)["entries"]
    monkeypatch.setattr(reviews_module, "MAX_BYTES", 10)
    with pytest.raises(GraphReadError, match="scope_too_large"):
        read_reviews(purchase_facts)
