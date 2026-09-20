"""Validated request and immutable graph projection records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shopping.purchases.family_models import PurchaseScope

NODE_TYPES = ("order", "revision", "item", "listing", "product", "family", "retailer", "source")
NODE_TYPE_SET = frozenset(NODE_TYPES)
SUPPORT_TYPES = NODE_TYPE_SET | {"membership", "membership_event"}
PREDICATES = {
    "HAS_REVISION": {"order": {"revision"}},
    "CURRENT_REVISION": {"order": {"revision"}},
    "ORDERED_FROM": {"order": {"retailer"}},
    "HAS_ITEM": {"revision": {"item"}},
    "REFERS_TO_LISTING": {"item": {"listing"}},
    "LISTED_BY": {"listing": {"retailer"}},
    "MAPS_TO_PRODUCT": {"listing": {"product"}},
    "MEMBER_OF": {"product": {"family"}},
    "SUPPORTED_BY": {"revision": {"source"}},
    "PURCHASED_IN": {"product": {"order"}},
}


class GraphReadError(ValueError):
    def __init__(self, code: str):
        if code not in {
            "invalid_input",
            "not_found",
            "invalid_cursor",
            "stale_snapshot",
            "scope_too_large",
        }:
            raise ValueError("unknown graph error")
        super().__init__(code)
        self.code = code


class GraphViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    query: str = Field(default="", max_length=200)
    selected_id: str | None = None
    expanded_ids: tuple[str, ...] = Field(default=(), max_length=12)
    mode: Literal["current", "history"] = "current"
    node_types: tuple[str, ...] = NODE_TYPES
    purchase_scope: PurchaseScope
    page_size: int = Field(default=40, ge=1, le=80)
    overview_cursor: str | None = Field(default=None, max_length=2048)
    relationship_cursors: dict[str, str] = Field(default_factory=dict, max_length=12)
    timeline_cursor: str | None = Field(default=None, max_length=2048)

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("invalid query")
        return value

    @field_validator("purchase_scope")
    @classmethod
    def _scope(cls, value: PurchaseScope) -> PurchaseScope:
        if type(value) is not PurchaseScope or type(value.analysis_date) is not date:
            raise ValueError("invalid purchase scope")
        if any(
            item is not None and type(item) is not date
            for item in (value.start_date, value.end_date)
        ):
            raise ValueError("invalid purchase scope")
        if value.start_date and value.start_date > value.analysis_date:
            raise ValueError("invalid purchase scope")
        if value.end_date and value.end_date > value.analysis_date:
            raise ValueError("invalid purchase scope")
        if value.start_date and value.end_date and value.start_date > value.end_date:
            raise ValueError("invalid purchase scope")
        try:
            for day, end in (
                (value.analysis_date, True),
                (value.start_date, False),
                (value.end_date, True),
            ):
                if day is not None:
                    datetime.combine(
                        day + (timedelta(days=1) if end else timedelta()),
                        time.min,
                        ZoneInfo("Asia/Singapore"),
                    ).astimezone(UTC)
        except (OverflowError, ValueError) as exc:
            raise ValueError("invalid purchase scope") from exc
        return value

    @field_validator("selected_id")
    @classmethod
    def _selected(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_graph_id(value)
        return value

    @field_validator("expanded_ids")
    @classmethod
    def _expanded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("expanded IDs must be distinct")
        for item in value:
            _validate_graph_id(item)
        return value

    @field_validator("node_types")
    @classmethod
    def _node_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not value
            or len(set(value)) != len(value)
            or any(item not in NODE_TYPE_SET for item in value)
        ):
            raise ValueError("invalid node types")
        return value

    @field_validator("relationship_cursors")
    @classmethod
    def _relationship_cursors(cls, value: dict[str, str]) -> dict[str, str]:
        for root, cursor in value.items():
            _validate_graph_id(root)
            if len(cursor) > 2048:
                raise ValueError("cursor too large")
        return value


def _validate_graph_id(value: str) -> None:
    parts = value.split(":")
    if len(parts) != 3 or len(parts[0]) != 32 or any(c not in "0123456789abcdef" for c in parts[0]):
        raise ValueError("invalid graph ID")
    if (
        parts[1] not in NODE_TYPE_SET
        or not parts[2]
        or (len(parts[2]) > 1 and parts[2][0] == "0")
        or any(char not in "0123456789" for char in parts[2])
        or not 0 < int(parts[2]) <= 2**63 - 1
        or len(value) > 70
    ):
        raise ValueError("invalid graph ID")


@dataclass(frozen=True, slots=True)
class RecordRef:
    entity_type: str
    row_id: int


@dataclass(frozen=True, slots=True)
class GraphRecord:
    ref: RecordRef
    label: str
    attributes: dict[str, Any]
    local_url: str | None = None


@dataclass(frozen=True, slots=True)
class GraphRelation:
    type: str
    source: RecordRef
    target: RecordRef
    state: Literal["active", "inactive"] = "active"
    support: tuple[RecordRef, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    type: str
    label: str
    record: RecordRef
    attributes: dict[str, Any]
    local_url: str | None = None


@dataclass(frozen=True, slots=True)
class GraphEdge:
    id: str
    type: str
    source: str
    target: str
    state: Literal["active", "inactive"]
    support: tuple[RecordRef, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    dataset_id: str
    source_generation: int
    projection_schema_version: int = 1
    method_version: str = "delivery-family-v1"

    def __post_init__(self) -> None:
        if (
            type(self.dataset_id) is not str
            or len(self.dataset_id) != 32
            or any(char not in "0123456789abcdef" for char in self.dataset_id)
            or type(self.source_generation) is not int
            or self.source_generation < 0
            or self.source_generation > 2**63 - 1
            or type(self.projection_schema_version) is not int
            or self.projection_schema_version != 1
            or self.method_version != "delivery-family-v1"
        ):
            raise ValueError("invalid snapshot reference")


@dataclass(frozen=True, slots=True)
class GraphReadSnapshot:
    snapshot: SnapshotRef
    scope: PurchaseScope
    records: tuple[GraphRecord, ...]
    relations: tuple[GraphRelation, ...]
    page: dict[str, Any]
    selection: dict[str, Any] | None
    coverage: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GraphProjection:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


@dataclass(frozen=True, slots=True)
class GraphView:
    snapshot: SnapshotRef
    scope: PurchaseScope
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    page: dict[str, Any]
    selection: dict[str, Any] | None
    coverage: dict[str, Any]
    build_metadata: dict[str, Any]
