"""Bounded, delivery-date based purchase timeline reads."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from zoneinfo import ZoneInfo

from shopping.purchases.family_models import (
    PurchaseScope,
    TimelineCoverage,
    TimelineOccurrence,
    TimelinePage,
    TimelinePageInfo,
    TimelineSummary,
)

_SG = ZoneInfo("Asia/Singapore")
_STATUSES = ("placed", "completed")
MAX_ITEMS = 5000
MAX_SOURCES = 5000
MAX_MEMBERS = 500
MAX_COVERAGE_ORDERS = 5000
_SQLITE_INT_MAX = 2**63 - 1


class TimelineError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _validate(product_ids: tuple[int, ...], scope: PurchaseScope, events: tuple[int, ...], after):
    if type(product_ids) is not tuple or any(
        type(x) is not int or not 0 < x <= _SQLITE_INT_MAX for x in product_ids
    ):
        raise TimelineError("invalid_input")
    if type(events) is not tuple or any(
        type(x) is not int or not 0 < x <= _SQLITE_INT_MAX for x in events
    ):
        raise TimelineError("invalid_input")
    if (
        type(scope) is not PurchaseScope
        or type(scope.analysis_date) is not date
        or any(
            value is not None and type(value) is not date
            for value in (scope.start_date, scope.end_date)
        )
    ):
        raise TimelineError("invalid_input")
    if scope.start_date and scope.end_date and scope.start_date > scope.end_date:
        raise TimelineError("invalid_input")
    if scope.start_date and scope.start_date > scope.analysis_date:
        raise TimelineError("invalid_input")
    if scope.end_date and scope.end_date > scope.analysis_date:
        raise TimelineError("invalid_input")
    if after is not None and (
        type(after) is not tuple
        or len(after) != 2
        or type(after[0]) is not str
        or type(after[1]) is not int
        or not 0 < after[1] <= _SQLITE_INT_MAX
    ):
        raise TimelineError("invalid_input")
    if after is not None:
        try:
            if date.fromisoformat(after[0]).isoformat() != after[0]:
                raise ValueError
        except ValueError:
            raise TimelineError("invalid_input") from None
    try:
        _utc_boundary(scope.analysis_date, True)
        if scope.start_date:
            _utc_boundary(scope.start_date)
        if scope.end_date:
            _utc_boundary(scope.end_date, True)
    except TimelineError:
        raise


def _utc_boundary(day: date, end: bool = False) -> str:
    try:
        instant = datetime.combine(
            day + (timedelta(days=1) if end else timedelta()), datetime.min.time(), _SG
        )
    except (OverflowError, ValueError) as exc:
        raise TimelineError("invalid_input") from exc
    try:
        return instant.astimezone(UTC).isoformat()
    except (OverflowError, ValueError) as exc:
        raise TimelineError("invalid_input") from exc


def _in_clause(values: Iterable[int]) -> tuple[str, tuple[int, ...]]:
    vals = tuple(dict.fromkeys(values))
    return ",".join("?" for _ in vals), vals


def read_timeline(
    connection: sqlite3.Connection,
    *,
    product_ids: tuple[int, ...],
    scope: PurchaseScope,
    membership_event_ids: tuple[int, ...],
    after_order: tuple[str, int] | None = None,
) -> TimelinePage:
    _validate(product_ids, scope, membership_event_ids, after_order)
    if len(set(product_ids)) > MAX_MEMBERS or len(set(membership_event_ids)) > MAX_MEMBERS:
        return _too_large()
    if not product_ids:
        empty = TimelineSummary(True, 0, 0, (), ())
        coverage = TimelineCoverage(True, 0, 0, 0, 0, 0)
        return TimelinePage(empty, (), coverage, TimelinePageInfo(False, None))
    pc, pvals = _in_clause(product_ids)
    # Accepted events provide the evidence IDs used for family reads. Empty evidence
    # is intentionally valid for a direct Product selection.
    memberships: dict[int, tuple[int, ...]] = {}
    if membership_event_ids:
        ec, evals = _in_clause(membership_event_ids)
        member_sql = (
            "SELECT e.id, m.product_id FROM product_family_events e "
            "JOIN product_family_memberships m ON m.id=e.membership_id "
            "WHERE e.kind='accepted' AND m.product_id IN (" + pc + ") "
            "AND e.id IN (" + ec + ") AND NOT EXISTS "
            "(SELECT 1 FROM product_family_events newer WHERE newer.membership_id=e.membership_id "
            "AND newer.version > e.version)"
        )
        member_rows = connection.execute(
            member_sql + f" LIMIT {MAX_MEMBERS + 1}", pvals + evals
        ).fetchall()
        if len(member_rows) > MAX_MEMBERS:
            return _too_large()
        for event_id, product_id in member_rows:
            memberships.setdefault(int(product_id), tuple())
            memberships[int(product_id)] += (int(event_id),)
        if not memberships:
            return TimelinePage(
                TimelineSummary(True, 0, 0, (), ()),
                (),
                TimelineCoverage(True, 0, 0, 0, 0, 0),
                TimelinePageInfo(False, None),
            )
        product_ids = tuple(sorted(memberships))
        pc, pvals = _in_clause(product_ids)

    args: list[object] = list(pvals)
    sql = f"""SELECT o.id, rev.id, rev.delivery_at, oi.id, rp.id, p.id, oi.quantity, oi.unit
        FROM order_items oi JOIN retailer_products rp ON rp.id=oi.retailer_product_id
        JOIN products p ON p.id=rp.product_id
        JOIN order_revisions rev ON rev.id=oi.order_revision_id AND rev.is_current=1
        JOIN orders o ON o.id=rev.order_id WHERE p.id IN ({pc})
        AND rev.status IN ('placed','completed')
        AND rev.delivery_at IS NOT NULL AND rev.delivery_at < ?"""
    args.append(_utc_boundary(scope.analysis_date, True))
    if scope.start_date:
        sql += " AND rev.delivery_at >= ?"
        args.append(_utc_boundary(scope.start_date))
    if scope.end_date:
        sql += " AND rev.delivery_at < ?"
        args.append(_utc_boundary(scope.end_date, True))
    rows = connection.execute(sql + f" LIMIT {MAX_ITEMS + 1}", args).fetchall()
    if len(rows) > MAX_ITEMS:
        return _too_large()
    grouped: dict[int, dict] = {}
    for oid, rid, delivery, iid, listing, pid, qty, unit in rows:
        d = datetime.fromisoformat(delivery.replace("Z", "+00:00")).astimezone(_SG).date()
        item = grouped.setdefault(
            int(oid),
            {
                "revision": int(rid),
                "date": d,
                "items": [],
                "products": set(),
                "listings": set(),
                "quantities": defaultdict(Decimal),
            },
        )
        item["items"].append(int(iid))
        item["products"].add(int(pid))
        item["listings"].add(int(listing))
        item["quantities"][(int(pid), unit)] += Decimal(str(qty))
    ids = tuple(grouped)
    source_map: dict[int, tuple[int, ...]] = {}
    if ids:
        oc, ov = _in_clause(ids)
        source_sql = f"""SELECT rev.order_id, rev.email_message_id
            FROM order_revisions rev WHERE rev.order_id IN ({oc}) AND rev.is_current=1
            UNION SELECT rev.order_id, s.email_message_id
            FROM order_revisions rev JOIN order_revision_sources s ON s.order_revision_id=rev.id
            WHERE rev.order_id IN ({oc}) AND rev.is_current=1"""
        source_rows = connection.execute(
            source_sql + f" LIMIT {MAX_SOURCES + 1}", ov + ov
        ).fetchall()
        if len(source_rows) > MAX_SOURCES:
            return _too_large()
        sm: dict[int, set[int]] = defaultdict(set)
        for oid, sid in source_rows:
            sm[int(oid)].add(int(sid))
        source_map = {k: tuple(sorted(v)) for k, v in sm.items()}
    ordered = sorted(grouped.items(), key=lambda x: (x[1]["date"], x[0]))
    dates = tuple(sorted({v["date"] for v in grouped.values()}))
    summary = TimelineSummary(
        True, len(grouped), len(dates), dates, tuple((b - a).days for a, b in pairwise(dates))
    )
    start = 0
    if after_order:
        try:
            cursor_date = date.fromisoformat(after_order[0])
        except ValueError:
            raise TimelineError("invalid_input") from None
        start = next(
            (
                i
                for i, (oid, v) in enumerate(ordered)
                if (v["date"], oid) > (cursor_date, after_order[1])
            ),
            len(ordered),
        )
    page_rows = ordered[start : start + 100]
    occ = tuple(
        TimelineOccurrence(
            oid,
            v["revision"],
            v["date"],
            tuple(sorted(v["items"])),
            source_map.get(oid, ()),
            tuple(sorted(v["products"])),
            tuple(sorted(v["listings"])),
            tuple(sorted({event for pid in v["products"] for event in memberships.get(pid, ())})),
            tuple((p, u, q) for (p, u), q in sorted(v["quantities"].items())),
        )
        for oid, v in page_rows
    )
    next_cursor = (
        (page_rows[-1][1]["date"].isoformat(), page_rows[-1][0])
        if start + 100 < len(ordered) and page_rows
        else None
    )
    coverage = _coverage(connection, product_ids, scope)
    return TimelinePage(
        summary, occ, coverage, TimelinePageInfo(next_cursor is not None, next_cursor)
    )


def _too_large() -> TimelinePage:
    return TimelinePage(
        None,
        (),
        TimelineCoverage(False, None, None, None, None, None, "scope_too_large"),
        TimelinePageInfo(False, None),
    )


def _coverage(
    connection: sqlite3.Connection, product_ids: tuple[int, ...], scope: PurchaseScope
) -> TimelineCoverage:
    pc, pvals = _in_clause(product_ids)
    sql = f"""SELECT o.id, rev.status, rev.delivery_at
        FROM orders o JOIN order_revisions rev ON rev.order_id=o.id AND rev.is_current=1
        WHERE EXISTS (SELECT 1 FROM order_items oi
                      JOIN retailer_products rp ON rp.id=oi.retailer_product_id
                      WHERE oi.order_revision_id=rev.id AND rp.product_id IN ({pc}))
        LIMIT {MAX_COVERAGE_ORDERS + 1}"""
    try:
        rows = connection.execute(sql, pvals).fetchall()
    except sqlite3.OperationalError as exc:
        if exc.sqlite_errorcode != sqlite3.SQLITE_INTERRUPT:
            raise
        return TimelineCoverage(False, None, None, None, None, None, "coverage_budget")
    if len(rows) > MAX_COVERAGE_ORDERS:
        return TimelineCoverage(False, None, None, None, None, None, "coverage_budget")
    eligible = excluded = missing = upcoming = outside = 0
    start = _utc_boundary(scope.start_date) if scope.start_date else None
    end = _utc_boundary(scope.end_date, True) if scope.end_date else None
    analysis_end = _utc_boundary(scope.analysis_date, True)
    for _oid, status, delivery in rows:
        if status not in _STATUSES:
            excluded += 1
        elif delivery is None:
            missing += 1
        elif delivery >= analysis_end:
            upcoming += 1
        elif (start and delivery < start) or (end and delivery >= end):
            outside += 1
        else:
            eligible += 1
    return TimelineCoverage(True, eligible, excluded, missing, upcoming, outside)
