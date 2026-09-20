from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest

from shopping.purchases.families import FamilyError, create_family, propose_membership
from shopping.purchases.family_models import EvidenceRef


def test_malformed_evidence_and_huge_ids_are_invalid(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Validation", definition="Items"
    )
    with pytest.raises(FamilyError, match="invalid_input"):
        propose_membership(
            purchase_facts,
            command_id=uuid4().hex,
            product_id=1,
            family_id=family.id,
            expected_version=0,
            origin="manual",
            method="test",
            rationale="test",
            support_refs=cast(tuple[EvidenceRef, ...], [EvidenceRef("product", 1)]),
        )
    with pytest.raises(FamilyError, match="invalid_input"):
        propose_membership(
            purchase_facts,
            command_id=uuid4().hex,
            product_id=2**63,
            family_id=family.id,
            expected_version=0,
            origin="manual",
            method="test",
            rationale="test",
        )


def test_missing_evidence_does_not_mutate(purchase_facts):
    family = create_family(
        purchase_facts, command_id=uuid4().hex, name="Missing", definition="Items"
    )
    with pytest.raises(FamilyError, match="not_found"):
        propose_membership(
            purchase_facts,
            command_id=uuid4().hex,
            product_id=1,
            family_id=family.id,
            expected_version=0,
            origin="manual",
            method="test",
            rationale="test",
            support_refs=(EvidenceRef("product", 999999),),
        )
