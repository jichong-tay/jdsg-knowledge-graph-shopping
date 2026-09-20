"""Pure validation, projection, and canonical serialization."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from shopping.knowledge.models import (
    NODE_TYPE_SET,
    PREDICATES,
    SUPPORT_TYPES,
    GraphEdge,
    GraphNode,
    GraphProjection,
    GraphReadError,
    GraphReadSnapshot,
    GraphView,
    RecordRef,
)

MAX_NODES = 200
MAX_EDGES = 400
MAX_JSON_BYTES = 1 << 20
SOURCE_ATTRIBUTES = {
    "id",
    "source_kind",
    "parse_status",
    "parser_version",
    "received_at",
    "source_sent_at",
    "fetched_at",
    "parsed_at",
}


def _node_id(dataset: str, ref: RecordRef) -> str:
    return f"{dataset}:{ref.entity_type}:{ref.row_id}"


def project_graph(snapshot: GraphReadSnapshot) -> GraphProjection:
    nodes = tuple(
        sorted(
            (_project_node(snapshot.snapshot.dataset_id, record) for record in snapshot.records),
            key=lambda n: n.id,
        )
    )
    edges_list: list[GraphEdge] = []
    for relation in snapshot.relations:
        source = _node_id(snapshot.snapshot.dataset_id, relation.source)
        target = _node_id(snapshot.snapshot.dataset_id, relation.target)
        supports = tuple(sorted(relation.support, key=lambda ref: (ref.entity_type, ref.row_id)))
        support_id = ":".join(f"{ref.entity_type}:{ref.row_id}" for ref in supports)
        edge_id = f"{relation.type}:{source}:{target}:{support_id}"
        edges_list.append(
            GraphEdge(edge_id, relation.type, source, target, relation.state, supports)
        )
    edges = tuple(sorted({edge.id: edge for edge in edges_list}.values(), key=lambda e: e.id))
    projection = GraphProjection(nodes, edges)
    validate_projection(projection)
    if len(canonical_json(projection)) > MAX_JSON_BYTES:
        raise GraphReadError("scope_too_large")
    return projection


def _project_node(dataset: str, record: Any) -> GraphNode:
    if (
        record.ref.entity_type not in NODE_TYPE_SET
        or type(record.ref.row_id) is not int
        or record.ref.row_id <= 0
    ):
        raise GraphReadError("invalid_input")
    return GraphNode(
        _node_id(dataset, record.ref),
        record.ref.entity_type,
        record.label,
        record.ref,
        record.attributes,
        record.local_url,
    )


def validate_projection(projection: GraphProjection) -> None:
    if len(projection.nodes) > MAX_NODES or len(projection.edges) > MAX_EDGES:
        raise GraphReadError("scope_too_large")
    nodes = {node.id: node for node in projection.nodes}
    if len(nodes) != len(projection.nodes) or any(
        node.type not in NODE_TYPE_SET for node in projection.nodes
    ):
        raise GraphReadError("invalid_input")
    datasets: set[str] = set()
    for node in projection.nodes:
        try:
            _validate_graph_id(node.id)
        except ValueError:
            raise GraphReadError("invalid_input") from None
        expected = f"{node.id.split(':', 1)[0]}:{node.type}:{node.record.row_id}"
        if (
            node.record.entity_type != node.type
            or type(node.record.row_id) is not int
            or not 0 < node.record.row_id <= 2**63 - 1
            or node.id != expected
            or (node.local_url is not None and not _valid_local_url(node))
        ):
            raise GraphReadError("invalid_input")
        datasets.add(node.id.split(":", 1)[0])
        if node.type == "source" and set(node.attributes) - SOURCE_ATTRIBUTES:
            raise GraphReadError("invalid_input")
    if len(datasets) > 1:
        raise GraphReadError("invalid_input")
    seen: set[str] = set()
    for edge in projection.edges:
        if (
            edge.id in seen
            or edge.type not in PREDICATES
            or edge.source not in nodes
            or edge.target not in nodes
        ):
            raise GraphReadError("invalid_input")
        seen.add(edge.id)
        source_type, target_type = nodes[edge.source].type, nodes[edge.target].type
        if target_type not in PREDICATES[edge.type].get(source_type, set()):
            raise GraphReadError("invalid_input")
        if edge.state not in {"active", "inactive"}:
            raise GraphReadError("invalid_input")
        if edge.type == "MEMBER_OF":
            support_types = {ref.entity_type for ref in edge.support}
            if not {"membership", "membership_event"} <= support_types:
                raise GraphReadError("invalid_input")
        elif not edge.support:
            raise GraphReadError("invalid_input")
        elif edge.type == "PURCHASED_IN":
            support_types = {ref.entity_type for ref in edge.support}
            if not {"product", "order", "revision", "item"} <= support_types:
                raise GraphReadError("invalid_input")
        for ref in edge.support:
            if (
                ref.entity_type not in SUPPORT_TYPES
                or type(ref.row_id) is not int
                or not 0 < ref.row_id <= 2**63 - 1
            ):
                raise GraphReadError("invalid_input")


def _valid_local_url(node: GraphNode) -> bool:
    return (
        node.type in {"product", "order"}
        and node.local_url == f"/{node.type}s/{node.record.row_id}"
    )


def _validate_graph_id(value: str) -> None:
    parts = value.split(":")
    if (
        len(parts) != 3
        or len(parts[0]) != 32
        or any(char not in "0123456789abcdef" for char in parts[0])
        or parts[1] not in NODE_TYPE_SET
        or not parts[2]
        or (len(parts[2]) > 1 and parts[2][0] == "0")
        or any(char not in "0123456789" for char in parts[2])
        or not 0 < int(parts[2]) <= 2**63 - 1
        or len(value) > 70
    ):
        raise ValueError("invalid graph ID")


def canonical_payload(view: GraphView) -> bytes:
    projection = GraphProjection(
        tuple(sorted(view.nodes, key=lambda node: node.id)),
        tuple(
            sorted(
                (
                    GraphEdge(
                        edge.id,
                        edge.type,
                        edge.source,
                        edge.target,
                        edge.state,
                        tuple(sorted(edge.support, key=lambda ref: (ref.entity_type, ref.row_id))),
                    )
                    for edge in view.edges
                ),
                key=lambda edge: edge.id,
            )
        ),
    )
    validate_projection(projection)
    if any(node.id.split(":", 1)[0] != view.snapshot.dataset_id for node in projection.nodes):
        raise GraphReadError("invalid_input")
    payload = {
        "snapshot": view.snapshot,
        "scope": view.scope,
        "nodes": projection.nodes,
        "edges": projection.edges,
        "page": view.page,
        "selection": view.selection,
        "coverage": view.coverage,
        "build_metadata": {k: v for k, v in view.build_metadata.items() if k != "built_at"},
    }
    raw = canonical_json(payload)
    if len(raw) > MAX_JSON_BYTES:
        raise GraphReadError("scope_too_large")
    return raw


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value
