"""Atomic product-family commands and bounded state reads."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal, cast

from shopping.config import Settings
from shopping.purchases.family_models import (
    EvidenceRef,
    FamilyRecord,
    FamilyStatePage,
    MembershipState,
)
from shopping.purchases.normalization import normalize_text
from shopping.storage.connection import connect_database, transaction
from shopping.storage.schema import assert_schema_current


class FamilyError(RuntimeError):
    def __init__(self, code: str, current_state: str | None = None):
        super().__init__(code)
        self.code, self.current_state = code, current_state


_SQLITE_INT_MAX = 2**63 - 1


def _text(value: str, maximum: int, label: str) -> str:
    if not isinstance(value, str) or not (value.strip() and len(value.strip()) <= maximum):
        raise FamilyError("invalid_input")
    return value.strip()


def _command(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise FamilyError("invalid_input")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _evidence(refs: tuple[EvidenceRef, ...]) -> str:
    allowed = {"product", "family", "membership", "order", "revision", "item", "source", "listing"}
    if (
        type(refs) is not tuple
        or len(refs) > 20
        or any(
            not isinstance(r, EvidenceRef)
            or type(r.entity_type) is not str
            or r.entity_type not in allowed
            or type(r.row_id) is not int
            or not 1 <= r.row_id <= _SQLITE_INT_MAX
            for r in refs
        )
    ):
        raise FamilyError("invalid_input")
    encoded = _json([{"entity_type": r.entity_type, "row_id": r.row_id} for r in refs])
    if len(encoded.encode()) > 8192:
        raise FamilyError("invalid_input")
    return encoded


def _validate_evidence(conn: sqlite3.Connection, refs: tuple[EvidenceRef, ...]) -> None:
    tables = {
        "product": "products",
        "family": "product_families",
        "membership": "product_family_memberships",
        "order": "orders",
        "revision": "order_revisions",
        "item": "order_items",
        "source": "email_messages",
        "listing": "retailer_products",
    }
    for ref in refs:
        if (
            conn.execute(
                f"SELECT 1 FROM {tables[ref.entity_type]} WHERE id=?", (ref.row_id,)
            ).fetchone()
            is None
        ):
            raise FamilyError("not_found")


def _fingerprint(operation: str, payload: object) -> str:
    return hashlib.sha256(_json([operation, payload]).encode()).hexdigest()


def _receipt(
    conn: sqlite3.Connection, command_id: str, operation: str, fingerprint: str
) -> object | None:
    row = conn.execute(
        "SELECT operation, fingerprint, outcome_json FROM family_commands WHERE id=?", (command_id,)
    ).fetchone()
    if row is None:
        return None
    if row[0] != operation or row[1] != fingerprint:
        raise FamilyError("command_conflict")
    return json.loads(row[2])


def _save(
    conn: sqlite3.Connection, command_id: str, operation: str, fingerprint: str, outcome: object
) -> None:
    conn.execute(
        "INSERT INTO family_commands VALUES (?, ?, ?, ?, ?)",
        (command_id, operation, fingerprint, _json(outcome), _now()),
    )


def _settings(settings: Settings) -> None:
    assert_schema_current(settings.database_path, settings.migrations_dir)


def create_family(
    settings: Settings, *, command_id: str, name: str, definition: str
) -> FamilyRecord:
    _settings(settings)
    command_id = _command(command_id)
    name = _text(name, 120, "name")
    definition = _text(definition, 2000, "definition")
    normalized = normalize_text(name)
    if not normalized or len(normalized) > 120:
        raise FamilyError("invalid_input")
    fp = _fingerprint("create_family", [name, definition])
    conn = connect_database(settings.database_path)
    try:
        with transaction(conn):
            old = _receipt(conn, command_id, "create_family", fp)
            if old is not None:
                return FamilyRecord(**cast(dict[str, Any], old))
            try:
                cur = conn.execute(
                    "INSERT INTO product_families "
                    "(name,normalized_name,definition,created_at) VALUES (?,?,?,?)",
                    (name, normalized, definition, _now()),
                )
            except sqlite3.IntegrityError as e:
                if "normalized_name" in str(e):
                    raise FamilyError("duplicate_family") from e
                raise
            if cur.lastrowid is None:
                raise FamilyError("invalid_input")
            result = FamilyRecord(
                cur.lastrowid,
                name,
                definition,
                conn.execute(
                    "SELECT created_at FROM product_families WHERE id=?", (cur.lastrowid,)
                ).fetchone()[0],
            )
            _save(conn, command_id, "create_family", fp, asdict(result))
            return result
    finally:
        conn.close()


def _state(conn: sqlite3.Connection, membership_id: int) -> MembershipState:
    row = conn.execute(
        """SELECT m.id,m.product_id,m.family_id,e.version,e.kind,e.id AS event_id,
        COALESCE(e.proposal_event_id,e.id),p.origin,p.method,p.rationale,p.support_json
        FROM product_family_memberships m JOIN product_family_events e ON e.membership_id=m.id
        JOIN product_family_events p ON p.id=COALESCE(e.proposal_event_id,e.id)
        WHERE m.id=? ORDER BY e.version DESC LIMIT 1""",
        (membership_id,),
    ).fetchone()
    if row is None:
        raise FamilyError("not_found")
    refs = tuple(
        EvidenceRef(x["entity_type"], int(x["row_id"])) for x in json.loads(row["support_json"])
    )
    return MembershipState(
        int(row[0]),
        int(row[1]),
        int(row[2]),
        int(row[3]),
        "pending" if row[4] == "proposed" else row[4],
        int(row[5]),
        int(row[6]),
        row[7],
        row[8],
        row[9],
        refs,
    )


def _state_json(state: MembershipState) -> dict[str, object]:
    return {
        "id": state.id,
        "product_id": state.product_id,
        "family_id": state.family_id,
        "version": state.version,
        "state": state.state,
        "event_id": state.event_id,
        "proposal_event_id": state.proposal_event_id,
        "origin": state.origin,
        "method": state.method,
        "rationale": state.rationale,
        "support_refs": [
            {"entity_type": r.entity_type, "row_id": r.row_id} for r in state.support_refs
        ],
    }


def _state_from_json(value: dict[str, object]) -> MembershipState:
    return MembershipState(
        int(cast(Any, value["id"])),
        int(cast(Any, value["product_id"])),
        int(cast(Any, value["family_id"])),
        int(cast(Any, value["version"])),
        cast(Any, value["state"]),
        int(cast(Any, value["event_id"])),
        int(cast(Any, value["proposal_event_id"])),
        cast(Any, value["origin"]),
        str(value["method"]),
        str(value["rationale"]),
        tuple(
            EvidenceRef(r["entity_type"], int(r["row_id"]))
            for r in cast(list[dict[str, Any]], value["support_refs"])
        ),
    )


def propose_membership(
    settings: Settings,
    *,
    command_id: str,
    product_id: int,
    family_id: int,
    expected_version: int,
    origin: Literal["manual", "inferred"],
    method: str,
    rationale: str,
    support_refs: tuple[EvidenceRef, ...] = (),
) -> MembershipState:
    _settings(settings)
    command_id = _command(command_id)
    method = _text(method, 120, "method")
    rationale = _text(rationale, 2000, "rationale")
    support = _evidence(support_refs)
    if (
        type(product_id) is not int
        or not 1 <= product_id <= _SQLITE_INT_MAX
        or type(family_id) is not int
        or not 1 <= family_id <= _SQLITE_INT_MAX
        or type(expected_version) is not int
        or not 0 <= expected_version <= _SQLITE_INT_MAX
        or origin not in ("manual", "inferred")
    ):
        raise FamilyError("invalid_input")
    fp = _fingerprint(
        "propose_membership",
        [product_id, family_id, expected_version, origin, method, rationale, json.loads(support)],
    )
    conn = connect_database(settings.database_path)
    try:
        with transaction(conn):
            old = _receipt(conn, command_id, "propose_membership", fp)
            if old is not None:
                return _state_from_json(cast(dict[str, object], old))
            if (
                conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone() is None
                or conn.execute(
                    "SELECT 1 FROM product_families WHERE id=?", (family_id,)
                ).fetchone()
                is None
            ):
                raise FamilyError("not_found")
            _validate_evidence(conn, support_refs)
            row = conn.execute(
                "SELECT id FROM product_family_memberships WHERE product_id=? AND family_id=?",
                (product_id, family_id),
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO product_family_memberships "
                    "(product_id,family_id,created_at) VALUES(?,?,?)",
                    (product_id, family_id, _now()),
                )
                if cur.lastrowid is None:
                    raise FamilyError("invalid_input")
                mid = cur.lastrowid
                version = 1
            else:
                mid = int(row[0])
                current = _state(conn, mid)
                version = current.version + 1
                if current.version != expected_version:
                    raise FamilyError("stale_version", current.state)
                if current.state in ("pending", "accepted"):
                    raise FamilyError("invalid_transition", current.state)
            if row is None and expected_version != 0:
                raise FamilyError("stale_version")
            conn.execute(
                "INSERT INTO product_family_events "
                "(membership_id,version,kind,origin,method,rationale,support_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (mid, version, "proposed", origin, method, rationale, support, _now()),
            )
            state = _state(conn, mid)
            _save(conn, command_id, "propose_membership", fp, _state_json(state))
            return state
    finally:
        conn.close()


def review_membership(
    settings: Settings,
    *,
    command_id: str,
    membership_id: int,
    proposal_event_id: int,
    expected_version: int,
    decision: Literal["accepted", "rejected", "withdrawn"],
    reason: str,
) -> MembershipState:
    _settings(settings)
    command_id = _command(command_id)
    reason = _text(reason, 2000, "reason")
    if (
        type(membership_id) is not int
        or not 1 <= membership_id <= _SQLITE_INT_MAX
        or type(proposal_event_id) is not int
        or not 1 <= proposal_event_id <= _SQLITE_INT_MAX
        or type(expected_version) is not int
        or not 1 <= expected_version < _SQLITE_INT_MAX
        or decision not in ("accepted", "rejected", "withdrawn")
    ):
        raise FamilyError("invalid_input")
    fp = _fingerprint(
        "review_membership", [membership_id, proposal_event_id, expected_version, decision, reason]
    )
    conn = connect_database(settings.database_path)
    try:
        with transaction(conn):
            old = _receipt(conn, command_id, "review_membership", fp)
            if old is not None:
                return _state_from_json(cast(dict[str, object], old))
            current = _state(conn, membership_id)
            if current.version != expected_version:
                raise FamilyError("stale_version", current.state)
            proposal = conn.execute(
                "SELECT kind, membership_id FROM product_family_events WHERE id=?",
                (proposal_event_id,),
            ).fetchone()
            if (
                proposal is None
                or int(proposal[1]) != membership_id
                or proposal[0] != "proposed"
                or current.proposal_event_id != proposal_event_id
            ):
                raise FamilyError("invalid_transition", current.state)
            if decision in ("accepted", "rejected") and current.state != "pending":
                raise FamilyError("invalid_transition", current.state)
            if decision == "withdrawn" and current.state != "accepted":
                raise FamilyError("invalid_transition", current.state)
            conn.execute(
                "INSERT INTO product_family_events "
                "(membership_id,version,kind,proposal_event_id,review_reason,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (membership_id, expected_version + 1, decision, proposal_event_id, reason, _now()),
            )
            state = _state(conn, membership_id)
            _save(conn, command_id, "review_membership", fp, _state_json(state))
            return state
    finally:
        conn.close()


def read_family_state(
    connection: sqlite3.Connection, *, family_id: int, limit: int = 501
) -> FamilyStatePage:
    if (
        type(family_id) is not int
        or not 1 <= family_id <= _SQLITE_INT_MAX
        or type(limit) is not int
        or not 1 <= limit <= 501
    ):
        raise FamilyError("invalid_input")
    family = connection.execute(
        "SELECT id,name,definition,created_at FROM product_families WHERE id=?", (family_id,)
    ).fetchone()
    if family is None:
        raise FamilyError("not_found")
    rows = connection.execute(
        "SELECT id FROM product_family_memberships WHERE family_id=? ORDER BY id LIMIT ?",
        (family_id, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    states = tuple(_state(connection, int(r[0])) for r in rows[:limit])
    return FamilyStatePage(
        FamilyRecord(int(family[0]), family[1], family[2], family[3]), states, more
    )
