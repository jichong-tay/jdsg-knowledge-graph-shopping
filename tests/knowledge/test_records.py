from contextlib import closing
from uuid import uuid4

import pytest

from shopping.knowledge.models import GraphReadError, RecordRef
from shopping.knowledge.records import read_record, read_roots
from shopping.purchases.families import create_family, propose_membership, review_membership
from shopping.purchases.normalization import normalize_text
from shopping.storage.connection import connect_database, transaction


def test_all_records_and_source_privacy(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Records", definition="test"
    )
    with closing(connect_database(purchase_facts.database_path)) as c:
        for kind in ("order", "revision", "item", "listing", "product", "retailer", "source"):
            record = read_record(c, RecordRef(kind, 1))
            assert record is not None and record.ref == RecordRef(kind, 1)
        family_record = read_record(c, RecordRef("family", family.id))
        assert family_record is not None and family_record.attributes["definition"] == "test"
        source = read_record(c, RecordRef("source", 1))
        assert source is not None and source.label == "Source #1" and source.local_url is None
        assert not {"sender", "subject", "raw_path", "recipient"} & source.attributes.keys()
        assert read_record(c, RecordRef("product", 99999)) is None


def test_root_paging_and_cursor_validation(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        for pid in (10, 11):
            c.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    f"root-{pid}",
                    f"Root {pid}",
                    f"root {pid}",
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
        first = read_roots(c, query="", limit=2)
        second = read_roots(
            c, query="", after=(first[-1].ref.entity_type, first[-1].ref.row_id), limit=2
        )
        assert len(first) == len(second) == 2
        with pytest.raises(GraphReadError):
            read_roots(c, query="", after=("order", 0))
        with pytest.raises(GraphReadError):
            read_roots(c, query="", after=("bad", 1))


def test_literal_root_search(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c, transaction(c):
        for pid, name in ((12, "Percent%"), (13, "Under_score"), (14, "Slash\\name")):
            c.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    f"literal-{pid}",
                    name,
                    normalize_text(name),
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
        for name in ("Percent%", "Under_score", "Slash\\name"):
            rows = read_roots(c, query=name, limit=10)
            assert len(rows) == 1 and rows[0].label == name


def test_product_identity_and_unassigned_are_independent(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c:
        before = read_record(c, RecordRef("product", 1))
    assert (
        before is not None
        and before.attributes["identity_status"] == "provisional"
        and before.attributes["unassigned"] is True
    )
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Assigned", definition="test"
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
    review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=proposal.id,
        proposal_event_id=proposal.event_id,
        expected_version=1,
        decision="accepted",
        reason="test",
    )
    with closing(connect_database(purchase_facts.database_path)) as c:
        after = read_record(c, RecordRef("product", 1))
    assert (
        after is not None
        and after.attributes["identity_status"] == "provisional"
        and after.attributes["unassigned"] is False
    )


@pytest.mark.parametrize(
    "ref", [RecordRef("product", True), RecordRef("product", 2**63), RecordRef("nope", 1)]
)
def test_invalid_record_refs(ref, purchase_facts):
    with (
        closing(connect_database(purchase_facts.database_path)) as c,
        pytest.raises(GraphReadError),
    ):
        read_record(c, ref)


def test_root_cursor_and_nul_validation(purchase_facts):
    with closing(connect_database(purchase_facts.database_path)) as c:
        with pytest.raises(GraphReadError):
            read_roots(c, query="", after=("product", 2**63))
        with pytest.raises(GraphReadError):
            read_roots(c, query="\x00")
