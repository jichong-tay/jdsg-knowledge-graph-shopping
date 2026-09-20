"""Bounded, filter-bound cursors for graph pagination."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import date
from typing import Any

from shopping.knowledge.models import PREDICATES, GraphReadError, GraphViewRequest, SnapshotRef

MAX_CURSOR = 2048
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DATASET = re.compile(r"[0-9a-f]{32}\Z")
_KINDS = {"overview", "relationship", "timeline", "reviews"}
_NODE_TYPES = {"order", "revision", "item", "listing", "product", "family", "retailer", "source"}


def request_fingerprint(request: GraphViewRequest) -> str:
    payload = {
        "query": request.query,
        "mode": request.mode,
        "node_types": sorted(request.node_types),
        "purchase_scope": {
            "analysis_date": request.purchase_scope.analysis_date.isoformat(),
            "start_date": request.purchase_scope.start_date.isoformat()
            if request.purchase_scope.start_date
            else None,
            "end_date": request.purchase_scope.end_date.isoformat()
            if request.purchase_scope.end_date
            else None,
        },
        "page_size": request.page_size,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def encode_cursor(
    snapshot: SnapshotRef, *, fingerprint: str, kind: str, root: str | None, last: tuple[Any, ...]
) -> str:
    _validate_common(snapshot, fingerprint, kind, root)
    _validate_last(kind, root, last)
    payload = {
        "v": 1,
        "dataset": snapshot.dataset_id,
        "generation": snapshot.source_generation,
        "fingerprint": fingerprint,
        "kind": kind,
        "root": root,
        "last": list(last),
    }
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if len(token) > MAX_CURSOR:
        raise GraphReadError("invalid_cursor")
    return token


def decode_cursor(
    token: str, snapshot: SnapshotRef, *, fingerprint: str, kind: str, root: str | None
) -> tuple[Any, ...]:
    _validate_common(snapshot, fingerprint, kind, root)
    if type(token) is not str or not token or len(token) > MAX_CURSOR or "=" in token:
        raise GraphReadError("invalid_cursor")
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        value = json.loads(raw)
        canonical = (
            base64.urlsafe_b64encode(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
    except ValueError, UnicodeError, json.JSONDecodeError, RecursionError, binascii.Error:
        raise GraphReadError("invalid_cursor") from None
    if (
        canonical != token
        or type(value) is not dict
        or set(value) != {"v", "dataset", "generation", "fingerprint", "kind", "root", "last"}
    ):
        raise GraphReadError("invalid_cursor")
    if type(value["v"]) is not int or value["v"] != 1:
        raise GraphReadError("invalid_cursor")
    try:
        stored = SnapshotRef(value["dataset"], value["generation"])
    except TypeError, ValueError:
        raise GraphReadError("invalid_cursor") from None
    _validate_common(stored, value["fingerprint"], value["kind"], value["root"])
    if type(value["last"]) is not list:
        raise GraphReadError("invalid_cursor")
    result = tuple(value["last"])
    _validate_last(value["kind"], value["root"], result)
    if (
        stored.dataset_id != snapshot.dataset_id
        or stored.source_generation != snapshot.source_generation
    ):
        raise GraphReadError("stale_snapshot")
    if value["fingerprint"] != fingerprint or value["kind"] != kind or value["root"] != root:
        raise GraphReadError("invalid_cursor")
    return result


def _validate_common(snapshot: SnapshotRef, fingerprint: str, kind: str, root: str | None) -> None:
    if (
        not isinstance(snapshot, SnapshotRef)
        or type(fingerprint) is not str
        or _HEX64.fullmatch(fingerprint) is None
    ):
        raise GraphReadError("invalid_cursor")
    if type(kind) is not str or kind not in _KINDS:
        raise GraphReadError("invalid_cursor")
    if root is not None and type(root) is not str:
        raise GraphReadError("invalid_cursor")
    if kind == "overview" and root is not None:
        raise GraphReadError("invalid_cursor")
    if root is not None:
        _validate_id(root)
        if kind == "relationship" and root.split(":")[1] not in _NODE_TYPES:
            raise GraphReadError("invalid_cursor")
        if kind == "timeline" and root.split(":")[1] not in {"product", "family"}:
            raise GraphReadError("invalid_cursor")
        if kind == "reviews" and root.split(":")[1] != "family":
            raise GraphReadError("invalid_cursor")
    elif kind in {"relationship", "timeline"}:
        raise GraphReadError("invalid_cursor")


def _validate_last(kind: str, root: str | None, last: tuple[Any, ...]) -> None:
    if type(last) is not tuple or len(last) > 6:
        raise GraphReadError("invalid_cursor")
    if kind == "overview":
        if (
            len(last) != 2
            or type(last[0]) is not str
            or last[0] not in {"family", "product"}
            or type(last[1]) is not int
            or not 0 < last[1] <= 2**63 - 1
        ):
            raise GraphReadError("invalid_cursor")
    elif kind == "relationship":
        if (
            len(last) != 6
            or type(last[0]) is not str
            or type(last[1]) is not str
            or type(last[2]) is not int
            or type(last[3]) is not str
            or type(last[4]) is not int
            or last[0] == ""
            or not 0 < last[2] <= 2**63 - 1
            or not 0 < last[4] <= 2**63 - 1
            or type(last[5]) is not int
            or not 0 <= last[5] <= 2**63 - 1
        ):
            raise GraphReadError("invalid_cursor")
        if last[1] not in _NODE_TYPES or last[3] not in _NODE_TYPES:
            raise GraphReadError("invalid_cursor")
        if last[0] not in PREDICATES or last[3] not in PREDICATES[last[0]].get(last[1], set()):
            raise GraphReadError("invalid_cursor")
        if (last[0] == "MEMBER_OF" and last[5] == 0) or (last[0] != "MEMBER_OF" and last[5] != 0):
            raise GraphReadError("invalid_cursor")
    elif kind == "timeline":
        if (
            len(last) != 2
            or type(last[0]) is not str
            or _iso(last[0]) is None
            or type(last[1]) is not int
            or not 0 < last[1] <= 2**63 - 1
        ):
            raise GraphReadError("invalid_cursor")
    elif len(last) != 1 or type(last[0]) is not int or not 0 < last[0] <= 2**63 - 1:
        raise GraphReadError("invalid_cursor")


def _validate_id(value: str) -> None:
    parts = value.split(":")
    if (
        len(parts) != 3
        or _DATASET.fullmatch(parts[0]) is None
        or parts[1] not in _NODE_TYPES
        or not parts[2]
        or any(char not in "0123456789" for char in parts[2])
        or (len(parts[2]) > 1 and parts[2][0] == "0")
        or not 0 < int(parts[2]) <= 2**63 - 1
        or len(value) > 70
    ):
        raise GraphReadError("invalid_cursor")


def _iso(value: str) -> str | None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == value else None
