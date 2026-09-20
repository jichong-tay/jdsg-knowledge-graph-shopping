"""Transactional, bounded graph views with independent selected-scope totals."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import Any, cast

from shopping.config import Settings
from shopping.knowledge.cursors import decode_cursor, encode_cursor, request_fingerprint
from shopping.knowledge.models import (
    GraphReadError,
    GraphReadSnapshot,
    GraphRecord,
    GraphRelation,
    GraphView,
    GraphViewRequest,
    RecordRef,
    SnapshotRef,
)
from shopping.knowledge.projection import canonical_json, canonical_payload, project_graph
from shopping.knowledge.records import product_purchase_counts, read_record, read_roots
from shopping.knowledge.relationships import RelationKey, read_relations, relation_key
from shopping.knowledge.selection import read_selection
from shopping.storage.connection import connect_database, transaction
from shopping.storage.schema import assert_schema_current

MAX_NODES = 200
MAX_EDGES = 400
MAX_RELATIONSHIPS = 60
MAX_JSON_BYTES = 1 << 20
PROGRESS_INTERVAL = 5000
MAX_VM_STEPS = 2_000_000
MAX_READ_SECONDS = 2.0


def _ref(node_id: str, snapshot: SnapshotRef) -> RecordRef:
    dataset, kind, row_id = node_id.split(":")
    if dataset != snapshot.dataset_id:
        raise GraphReadError("stale_snapshot")
    return RecordRef(kind, int(row_id))


class _ViewReader:
    def __init__(
        self, connection: sqlite3.Connection, request: GraphViewRequest, snapshot: SnapshotRef
    ) -> None:
        self.connection = connection
        self.request = request
        self.snapshot = snapshot
        self.fingerprint = request_fingerprint(request)
        self.cache: dict[RecordRef, GraphRecord] = {}
        self.records: dict[RecordRef, GraphRecord] = {}
        self.relations: dict[RelationKey, GraphRelation] = {}
        self.reasons: set[str] = set()
        self.hidden = 0

    def record(self, ref: RecordRef) -> GraphRecord:
        if ref not in self.cache:
            record = read_record(self.connection, ref)
            if record is None:
                raise GraphReadError("not_found")
            self.cache[ref] = record
        return self.cache[ref]

    def add_root(self, record: GraphRecord) -> None:
        self.cache[record.ref] = record
        if record.ref.entity_type not in self.request.node_types:
            self.hidden += 1
        elif record.ref in self.records or len(self.records) < MAX_NODES:
            self.records[record.ref] = record
        else:
            self.reasons.add("node_limit")

    def cursor(self, kind: str, root: str | None, last: tuple[Any, ...] | None) -> str | None:
        if last is None:
            return None
        return encode_cursor(
            self.snapshot, fingerprint=self.fingerprint, kind=kind, root=root, last=last
        )

    def decode(self, token: str | None, kind: str, root: str | None) -> tuple[Any, ...] | None:
        if token is None:
            return None
        return decode_cursor(
            token, self.snapshot, fingerprint=self.fingerprint, kind=kind, root=root
        )

    def neighborhood(
        self, root_id: str, root: RecordRef, after: RelationKey | None
    ) -> dict[str, Any]:
        rows = read_relations(
            self.connection,
            root,
            mode=self.request.mode,
            scope=self.request.purchase_scope,
            after=after,
            limit=MAX_RELATIONSHIPS + 1,
        )
        has_more = len(rows) > MAX_RELATIONSHIPS
        reason = "relationship_limit" if has_more else None
        last: RelationKey | None = None
        for relation in rows[:MAX_RELATIONSHIPS]:
            key = relation_key(relation)
            endpoints = (relation.source, relation.target)
            if any(ref.entity_type not in self.request.node_types for ref in endpoints):
                self.hidden += 1
                last = key
                continue
            if key in self.relations:
                last = key
                continue
            missing = tuple(ref for ref in endpoints if ref not in self.records)
            if len(self.records) + len(set(missing)) > MAX_NODES:
                has_more, reason = True, "node_limit"
                break
            if len(self.relations) >= MAX_EDGES:
                has_more, reason = True, "edge_limit"
                break
            # All endpoints must fit before making this edge visible.
            endpoint_records = tuple(self.record(ref) for ref in missing)
            for record in endpoint_records:
                self.records[record.ref] = record
            self.relations[key] = relation
            last = key
        if reason:
            self.reasons.add(reason)
        return {
            "has_more": has_more,
            "cursor": self.cursor("relationship", root_id, last) if has_more else None,
            "reason": reason,
        }

    def read(self) -> GraphReadSnapshot:
        request = self.request
        if set(request.relationship_cursors) - set(request.expanded_ids):
            raise GraphReadError("invalid_cursor")
        selected = _ref(request.selected_id, self.snapshot) if request.selected_id else None
        expanded = {key: _ref(key, self.snapshot) for key in sorted(request.expanded_ids)}
        if request.timeline_cursor is not None and (
            selected is None or selected.entity_type not in {"product", "family"}
        ):
            raise GraphReadError("invalid_cursor")
        overview_after = cast(
            tuple[str, int] | None, self.decode(request.overview_cursor, "overview", None)
        )
        relation_after = {
            key: cast(
                RelationKey | None,
                self.decode(request.relationship_cursors.get(key), "relationship", key),
            )
            for key in expanded
        }
        timeline_after = cast(
            tuple[str, int] | None,
            self.decode(request.timeline_cursor, "timeline", request.selected_id),
        )
        if selected:
            self.add_root(self.record(selected))
        for ref in expanded.values():
            self.add_root(self.record(ref))
        roots = read_roots(
            self.connection, query=request.query, after=overview_after, limit=request.page_size + 1
        )
        for record in roots[: request.page_size]:
            self.add_root(record)
        overview_more = len(roots) > request.page_size
        if overview_more:
            self.reasons.add("overview_limit")
        last_root = roots[request.page_size - 1].ref if overview_more else None
        pages: dict[str, Any] = {
            "overview": {
                "has_more": overview_more,
                "cursor": self.cursor(
                    "overview",
                    None,
                    (last_root.entity_type, last_root.row_id) if last_root else None,
                ),
            },
            "relationships": {},
            "timeline": {"has_more": False, "cursor": None},
        }
        for key, ref in expanded.items():
            pages["relationships"][key] = self.neighborhood(key, ref, relation_after[key])
        product_refs = {ref.row_id for ref in self.records if ref.entity_type == "product"}
        if selected and selected.entity_type == "product":
            product_refs.add(selected.row_id)
        counts = product_purchase_counts(
            self.connection, tuple(sorted(product_refs)), request.purchase_scope
        )
        for ref, record in tuple(self.records.items()):
            if ref.entity_type == "product" and ref.row_id in counts:
                self.records[ref] = replace(
                    record, attributes={**record.attributes, "purchase_count": counts[ref.row_id]}
                )
        # This is the final SQL work. Optional coverage may exhaust the remaining
        # budget after a complete selected summary; no query may follow it.
        selection = (
            read_selection(
                self.connection, selected, scope=request.purchase_scope, after_order=timeline_after
            )
            if selected
            else None
        )
        if selection and selection["timeline"] is not None:
            timeline = selection["timeline"]
            pages["timeline"] = {
                "has_more": timeline.page.has_more,
                "cursor": self.cursor("timeline", request.selected_id, timeline.page.after_order)
                if timeline.page.has_more
                else None,
            }
            selected_record = selection["record"]
            if (
                selected_record.ref.entity_type == "product"
                and selected_record.ref.row_id in counts
            ):
                selection["record"] = replace(
                    selected_record,
                    attributes={
                        **selected_record.attributes,
                        "purchase_count": counts[selected_record.ref.row_id],
                    },
                )
        coverage = {
            "shown_nodes": len(self.records),
            "shown_edges": len(self.relations),
            "partial": bool(self.reasons),
            "reasons": sorted(self.reasons),
            "hidden_by_type": self.hidden,
        }
        return GraphReadSnapshot(
            self.snapshot,
            request.purchase_scope,
            tuple(self.records.values()),
            tuple(self.relations.values()),
            pages,
            selection,
            coverage,
        )


def read_graph_view(
    settings: Settings, request: GraphViewRequest, *, expected_snapshot: SnapshotRef | None = None
) -> GraphView:
    if not isinstance(request, GraphViewRequest) or (
        expected_snapshot is not None and not isinstance(expected_snapshot, SnapshotRef)
    ):
        raise GraphReadError("invalid_input")
    assert_schema_current(settings.database_path, settings.migrations_dir)
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute("PRAGMA query_only=ON")
        steps = 0
        started = monotonic()

        def progress() -> int:
            nonlocal steps
            steps += PROGRESS_INTERVAL
            return int(steps >= MAX_VM_STEPS or monotonic() - started >= MAX_READ_SECONDS)

        try:
            with transaction(connection, immediate=False):
                connection.set_progress_handler(progress, PROGRESS_INTERVAL)
                try:
                    state = connection.execute(
                        "SELECT dataset_id,generation FROM graph_dataset_state WHERE id=1"
                    ).fetchone()
                    if state is None:
                        raise GraphReadError("not_found")
                    snapshot = SnapshotRef(state[0], state[1])
                    if expected_snapshot is not None and expected_snapshot != snapshot:
                        raise GraphReadError("stale_snapshot")
                    read = _ViewReader(connection, request, snapshot).read()
                finally:
                    connection.set_progress_handler(None, 0)
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
                raise GraphReadError("scope_too_large") from None
            raise
    # Pure projection/serialization run after the connection has closed.
    projection = project_graph(read)
    selection = None
    if read.selection is not None:
        selection = dict(read.selection)
        selected_record = selection.pop("record")
        selected_projection = project_graph(replace(read, records=(selected_record,), relations=()))
        selection["node"] = selected_projection.nodes[0]
    view = GraphView(
        read.snapshot,
        read.scope,
        projection.nodes,
        projection.edges,
        read.page,
        selection,
        read.coverage,
        {
            "built_at": datetime.now(UTC).isoformat(),
            "timezone": "Asia/Singapore",
            "date_basis": "scheduled_delivery",
            "mode": request.mode,
            "eligible_statuses": ["placed", "completed"],
            "method": "delivery-family-v1",
        },
    )
    canonical_payload(view)
    if len(canonical_json(view)) > MAX_JSON_BYTES:
        raise GraphReadError("scope_too_large")
    return view
