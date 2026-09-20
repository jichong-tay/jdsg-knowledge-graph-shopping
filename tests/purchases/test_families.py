from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from typing import Literal
from uuid import uuid4

import pytest

from shopping.purchases import families
from shopping.purchases.families import (
    FamilyError,
    create_family,
    propose_membership,
    read_family_state,
    review_membership,
)
from shopping.purchases.family_models import EvidenceRef
from shopping.storage.connection import connect_database, transaction


def test_family_lifecycle_and_idempotent_review(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Example drinks", definition="Oat drinks"
    )
    pending = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="Matches",
    )
    command = uuid4().hex
    accepted = review_membership(
        purchase_facts,
        command_id=command,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=1,
        decision="accepted",
        reason="Reviewed",
    )
    assert (
        review_membership(
            purchase_facts,
            command_id=command,
            membership_id=pending.id,
            proposal_event_id=pending.proposal_event_id,
            expected_version=1,
            decision="accepted",
            reason="Reviewed",
        )
        == accepted
    )
    withdrawn = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=2,
        decision="withdrawn",
        reason="Grouping corrected",
    )
    assert withdrawn.state == "withdrawn"


def test_command_conflict_and_immutable_family(purchase_facts):
    command = uuid4().hex
    create_family(purchase_facts, command_id=command, name="One", definition="Definition")
    with pytest.raises(FamilyError, match="command_conflict"):
        create_family(purchase_facts, command_id=command, name="Two", definition="Definition")
    with closing(connect_database(purchase_facts.database_path)) as connection:
        with transaction(connection), pytest.raises(Exception, match="immutable"):
            connection.execute("UPDATE product_families SET name='bad' WHERE id=1")


def test_family_state_is_bounded(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Bounded", definition="Definition"
    )
    propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="Matches",
    )
    with closing(connect_database(purchase_facts.database_path)) as connection:
        page = read_family_state(connection, family_id=family.id, limit=1)
    assert len(page.memberships) == 1 and page.has_more is False


def test_family_state_rejects_sqlite_overflow_id(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as connection:
        with pytest.raises(FamilyError, match="invalid_input"):
            read_family_state(connection, family_id=2**63)


def test_replay_accepted_command_after_withdrawal_returns_original_result(purchase_facts):
    family = create_family(purchase_facts, command_id=uuid4().hex, name="Replay", definition="D")
    pending = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="Matches",
    )
    command = uuid4().hex
    accepted = review_membership(
        purchase_facts,
        command_id=command,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=1,
        decision="accepted",
        reason="Reviewed",
    )
    review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=2,
        decision="withdrawn",
        reason="Changed",
    )
    assert (
        review_membership(
            purchase_facts,
            command_id=command,
            membership_id=pending.id,
            proposal_event_id=pending.proposal_event_id,
            expected_version=1,
            decision="accepted",
            reason="Reviewed",
        )
        == accepted
    )


def test_replay_original_proposal_after_acceptance_returns_pending_snapshot(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Proposal replay", definition="D"
    )
    command = uuid4().hex
    pending = propose_membership(
        purchase_facts,
        command_id=command,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="Matches",
    )
    review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=1,
        decision="accepted",
        reason="Reviewed",
    )
    assert (
        propose_membership(
            purchase_facts,
            command_id=command,
            product_id=1,
            family_id=family.id,
            expected_version=0,
            origin="manual",
            method="operator",
            rationale="Matches",
        )
        == pending
    )


def test_old_proposal_event_is_rejected_after_withdrawal_and_reproposal(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Reproposal", definition="D"
    )
    first = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="First",
    )
    review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=first.id,
        proposal_event_id=first.proposal_event_id,
        expected_version=1,
        decision="accepted",
        reason="Reviewed",
    )
    review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=first.id,
        proposal_event_id=first.proposal_event_id,
        expected_version=2,
        decision="withdrawn",
        reason="Changed",
    )
    second = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=3,
        origin="manual",
        method="operator",
        rationale="Second",
    )
    with pytest.raises(FamilyError, match="invalid_transition") as error:
        review_membership(
            purchase_facts,
            command_id=uuid4().hex,
            membership_id=second.id,
            proposal_event_id=first.proposal_event_id,
            expected_version=4,
            decision="accepted",
            reason="Old proposal",
        )
    assert error.value.current_state == "pending"


def test_concurrent_reviews_have_one_winner_and_one_stale_error(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Concurrent", definition="D"
    )
    pending = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="Matches",
    )

    def review(decision: Literal["accepted", "rejected"]):
        try:
            return review_membership(
                purchase_facts,
                command_id=uuid4().hex,
                membership_id=pending.id,
                proposal_event_id=pending.proposal_event_id,
                expected_version=1,
                decision=decision,
                reason=decision,
            )
        except FamilyError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, ("accepted", "rejected")))
    assert sum(isinstance(result, FamilyError) for result in results) == 1
    assert (
        sum(
            isinstance(result, FamilyError) and result.code == "stale_version" for result in results
        )
        == 1
    )
    with closing(connect_database(purchase_facts.database_path)) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM product_family_events WHERE membership_id=?", (pending.id,)
            ).fetchone()[0]
            == 2
        )


def test_proposal_rolls_back_when_receipt_save_fails(purchase_facts, monkeypatch):
    family = create_family(purchase_facts, command_id=uuid4().hex, name="Rollback", definition="D")
    with closing(connect_database(purchase_facts.database_path)) as connection:
        before_generation = connection.execute(
            "SELECT generation FROM graph_dataset_state"
        ).fetchone()[0]

    def fail_save(*args, **kwargs):
        raise RuntimeError("save failed")

    monkeypatch.setattr(families, "_save", fail_save)
    with pytest.raises(RuntimeError, match="save failed"):
        propose_membership(
            purchase_facts,
            command_id=uuid4().hex,
            product_id=1,
            family_id=family.id,
            expected_version=0,
            origin="manual",
            method="operator",
            rationale="Matches",
        )
    with closing(connect_database(purchase_facts.database_path)) as connection:
        assert (
            connection.execute("SELECT count(*) FROM product_family_memberships").fetchone()[0] == 0
        )
        assert connection.execute("SELECT count(*) FROM product_family_events").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM family_commands").fetchone()[0] == 1
        assert (
            connection.execute("SELECT generation FROM graph_dataset_state").fetchone()[0]
            == before_generation
        )


def test_missing_evidence_ref_does_not_mutate(purchase_facts):
    family = create_family(purchase_facts, command_id=uuid4().hex, name="Evidence", definition="D")
    with pytest.raises(FamilyError, match="not_found"):
        propose_membership(
            purchase_facts,
            command_id=uuid4().hex,
            product_id=1,
            family_id=family.id,
            expected_version=0,
            origin="inferred",
            method="model",
            rationale="Evidence",
            support_refs=(EvidenceRef("product", 99999),),
        )
    with closing(connect_database(purchase_facts.database_path)) as connection:
        assert (
            connection.execute("SELECT count(*) FROM product_family_memberships").fetchone()[0] == 0
        )
        assert connection.execute("SELECT count(*) FROM product_family_events").fetchone()[0] == 0


def test_accepted_inferred_family_survives_verified_backup(
    purchase_facts, sqlite_backup_module, tmp_path
):
    family = create_family(purchase_facts, command_id=uuid4().hex, name="Backup", definition="D")
    pending = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="inferred",
        method="rules-v1",
        rationale="Observed",
        support_refs=(EvidenceRef("product", 1),),
    )
    accepted = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=1,
        decision="accepted",
        reason="Confirmed",
    )
    backup = tmp_path / "family.sqlite3"
    sqlite_backup_module.create_verified_backup(purchase_facts.database_path, backup)
    with closing(connect_database(backup)) as connection:
        state = read_family_state(connection, family_id=family.id).memberships[0]
        assert state == accepted
        assert (state.origin, state.method, state.rationale, state.support_refs) == (
            "inferred",
            "rules-v1",
            "Observed",
            (EvidenceRef("product", 1),),
        )


def test_graph_generation_tracks_writes_and_rollbacks(purchase_facts, monkeypatch):
    def generation():
        with closing(connect_database(purchase_facts.database_path)) as connection:
            return connection.execute("SELECT generation FROM graph_dataset_state").fetchone()[0]

    baseline = generation()
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Generation", definition="D"
    )
    assert generation() > baseline
    with closing(connect_database(purchase_facts.database_path)) as connection:
        before = generation()
        with transaction(connection):
            connection.execute("UPDATE order_revisions SET is_current=0 WHERE id=1")
        assert generation() > before
        before = generation()
        connection.execute("UPDATE order_revisions SET is_current=1 WHERE id=5")
        assert generation() > before
        before = generation()
        connection.execute(
            "INSERT INTO products "
            "(canonical_key,canonical_name,normalized_name,created_at,updated_at) "
            "VALUES ('generation-test','Generation Test','generation test',"
            "'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
        )
        connection.execute("UPDATE retailer_products SET product_id=2 WHERE id=1")
        assert generation() > before
        before = generation()
        connection.execute(
            "INSERT INTO order_revision_sources "
            "(order_revision_id,email_message_id,linked_at) "
            "VALUES (2,1,'2026-01-01T00:00:00+00:00')"
        )
        assert generation() > before
    pending = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="Matches",
    )
    assert generation() > before
    before = generation()
    monkeypatch.setattr(
        families, "_save", lambda *args: (_ for _ in ()).throw(RuntimeError("rollback"))
    )
    with pytest.raises(RuntimeError):
        review_membership(
            purchase_facts,
            command_id=uuid4().hex,
            membership_id=pending.id,
            proposal_event_id=pending.proposal_event_id,
            expected_version=1,
            decision="accepted",
            reason="Reviewed",
        )
    assert generation() == before
