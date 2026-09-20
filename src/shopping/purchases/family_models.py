"""Typed records for product-family membership and graph source identity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

EntityType = Literal[
    "product", "family", "membership", "order", "revision", "item", "source", "listing"
]
MembershipKind = Literal["pending", "accepted", "rejected", "withdrawn"]


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    entity_type: EntityType
    row_id: int


@dataclass(frozen=True, slots=True)
class FamilyRecord:
    id: int
    name: str
    definition: str
    created_at: str


@dataclass(frozen=True, slots=True)
class MembershipState:
    id: int
    product_id: int
    family_id: int
    version: int
    state: MembershipKind
    event_id: int
    proposal_event_id: int
    origin: Literal["manual", "inferred"]
    method: str
    rationale: str
    support_refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class FamilyStatePage:
    family: FamilyRecord
    memberships: tuple[MembershipState, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class PurchaseScope:
    analysis_date: date
    start_date: date | None = None
    end_date: date | None = None


@dataclass(frozen=True, slots=True)
class TimelineSummary:
    complete_for_scope: bool
    order_count: int
    purchase_day_count: int
    purchase_dates: tuple[date, ...]
    gaps_days: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TimelineOccurrence:
    order_id: int
    revision_id: int
    purchase_date: date
    item_ids: tuple[int, ...]
    source_ids: tuple[int, ...]
    product_ids: tuple[int, ...]
    listing_ids: tuple[int, ...]
    membership_event_ids: tuple[int, ...]
    quantities: tuple[tuple[int, str, Decimal], ...]


@dataclass(frozen=True, slots=True)
class TimelineCoverage:
    counts_complete: bool
    eligible_order_count: int | None
    excluded_order_count: int | None
    missing_date_count: int | None
    upcoming_order_count: int | None
    outside_range_count: int | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TimelinePageInfo:
    has_more: bool
    after_order: tuple[str, int] | None


@dataclass(frozen=True, slots=True)
class TimelinePage:
    summary: TimelineSummary | None
    occurrences: tuple[TimelineOccurrence, ...]
    coverage: TimelineCoverage
    page: TimelinePageInfo
