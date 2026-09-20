import base64
import json
from datetime import date

import pytest

from shopping.knowledge.cursors import decode_cursor, encode_cursor, request_fingerprint
from shopping.knowledge.models import GraphReadError, GraphViewRequest, SnapshotRef
from shopping.purchases.family_models import PurchaseScope

S = SnapshotRef("a" * 32, 4)
R = "a" * 32 + ":product:1"


def test_roundtrip_kinds_and_fingerprint_excludes_selection():
    first = GraphViewRequest(purchase_scope=PurchaseScope(date(2026, 9, 20)))
    second = first.model_copy(update={"selected_id": R, "expanded_ids": (R,)})
    fingerprint = request_fingerprint(first)
    assert fingerprint == request_fingerprint(second)
    values = {
        "overview": ("product", 1),
        "relationship": ("MEMBER_OF", "product", 1, "family", 2, 3),
        "timeline": ("2026-09-20", 1),
        "reviews": (1,),
    }
    roots = {"overview": None, "relationship": R, "timeline": R, "reviews": None}
    for kind, last in values.items():
        token = encode_cursor(S, fingerprint=fingerprint, kind=kind, root=roots[kind], last=last)
        assert decode_cursor(token, S, fingerprint=fingerprint, kind=kind, root=roots[kind]) == last


def test_stale_and_filter_root_mismatch():
    fp = "b" * 64
    token = encode_cursor(S, fingerprint=fp, kind="overview", root=None, last=("product", 1))
    with pytest.raises(GraphReadError, match="stale_snapshot"):
        decode_cursor(token, SnapshotRef("a" * 32, 5), fingerprint=fp, kind="overview", root=None)
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        decode_cursor(token, S, fingerprint="c" * 64, kind="overview", root=None)


@pytest.mark.parametrize("token", ["!", "e30=", "eyJ2IjoxfQ", "a" * 2049])
def test_malformed_tokens_rejected(token):
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        decode_cursor(token, S, fingerprint="b" * 64, kind="overview", root=None)


def test_invalid_last_and_boolean_are_rejected():
    with pytest.raises(GraphReadError):
        encode_cursor(S, fingerprint="b" * 64, kind="overview", root=None, last=("product", True))


@pytest.mark.parametrize(
    "field,value",
    [
        ("v", True),
        ("v", 2),
        ("generation", True),
        ("generation", -1),
        ("generation", 2**63),
        ("dataset", 123),
        ("dataset", "bad"),
        ("fingerprint", 123),
        ("fingerprint", "bad"),
        ("kind", []),
        ("root", []),
        ("last", []),
        ("last", ["product", True]),
    ],
)
def test_semantic_payload_validation(field, value):
    fp = "b" * 64
    token = encode_cursor(S, fingerprint=fp, kind="overview", root=None, last=("product", 1))
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    payload = json.loads(raw)
    payload[field] = value
    mutated = (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        decode_cursor(mutated, S, fingerprint=fp, kind="overview", root=None)


def test_semantic_payload_extra_field_and_stale_snapshot():
    fp = "b" * 64
    token = encode_cursor(S, fingerprint=fp, kind="overview", root=None, last=("product", 1))
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    payload = json.loads(raw)
    payload["extra"] = 1
    mutated = (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        decode_cursor(mutated, S, fingerprint=fp, kind="overview", root=None)
    old = SnapshotRef("c" * 32, 4)
    old_token = encode_cursor(old, fingerprint=fp, kind="overview", root=None, last=("product", 1))
    with pytest.raises(GraphReadError, match="stale_snapshot"):
        decode_cursor(old_token, S, fingerprint=fp, kind="overview", root=None)


@pytest.mark.parametrize(
    "last",
    [
        ("UNKNOWN", "product", 1, "family", 2, 0),
        ("MEMBER_OF", "family", 1, "product", 2, 1),
        ("MEMBER_OF", "product", 1, "family", 2, 0),
    ],
)
def test_relationship_semantic_validation(last):
    with pytest.raises(GraphReadError, match="invalid_cursor"):
        encode_cursor(S, fingerprint="b" * 64, kind="relationship", root=R, last=last)
