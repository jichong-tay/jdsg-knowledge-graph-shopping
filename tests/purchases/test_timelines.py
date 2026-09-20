# ruff: noqa: E501
import sqlite3
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest

from shopping.purchases.families import create_family, propose_membership, review_membership
from shopping.purchases.family_models import PurchaseScope
from shopping.purchases.timelines import TimelineError, read_timeline
from shopping.storage.connection import connect_database, transaction


@pytest.fixture
def timeline_facts(settings):
    """The exact two-product, eight-order synthetic timeline from Task 2."""
    with closing(connect_database(settings.database_path)) as c, transaction(c):
        c.execute("INSERT INTO retailers VALUES (1,'synthetic','Synthetic','SG','2026-01-01')")
        for pid, name in ((1, "Product A"), (2, "Product B")):
            c.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    f"product-{pid}",
                    name,
                    name.lower(),
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
            c.execute(
                "INSERT INTO retailer_products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    1,
                    f"SKU-{pid}",
                    f"listing-{pid}",
                    pid,
                    name,
                    None,
                    "confirmed",
                    "manual",
                    1.0,
                    "2026-01-01",
                    "2026-01-01",
                ),
            )
        for sid in (1, 2):
            c.execute(
                "INSERT INTO email_messages (id,source_kind,source_message_key,source_fingerprint,sender,subject,received_at,raw_sha256,raw_path,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    "manual",
                    f"message-{sid}",
                    f"fingerprint-{sid}",
                    "source@example.invalid",
                    "Synthetic",
                    "2026-09-01T00:00:00+00:00",
                    f"sha-{sid}",
                    f"/tmp/synthetic-{sid}",
                    "2026-09-01T00:00:00+00:00",
                ),
            )
        specs = (
            (1, "2026-08-31T18:00:00+00:00", "placed"),
            (2, "2026-09-01T10:00:00+00:00", "completed"),
            (3, "2026-09-05T02:00:00+00:00", "placed"),
            (4, "2026-09-20T16:00:00+00:00", "placed"),
            (5, "2026-09-20T15:59:59+00:00", "placed"),
            (6, "2026-09-06T02:00:00+00:00", "cancelled"),
            (7, "2026-09-06T02:00:00+00:00", "refunded"),
            (8, "2026-09-06T02:00:00+00:00", "unknown"),
        )
        for oid, delivery, status in specs:
            c.execute(
                "INSERT INTO orders VALUES (?,?,?,?)",
                (oid, 1, f"ORDER-{oid}", "2026-01-01T00:00:00+00:00"),
            )
            c.execute(
                "INSERT INTO order_revisions (id,order_id,email_message_id,revision_number,revision_kind,revision_fingerprint,parser_version,source_event_at,delivery_at,currency,total_cents,status,is_current,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    oid,
                    oid,
                    1,
                    1,
                    "confirmation",
                    f"revision-{oid}",
                    "test",
                    "2026-01-01T00:00:00+00:00",
                    delivery,
                    "SGD",
                    100,
                    status,
                    1,
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        c.execute(
            "INSERT INTO order_revisions (id,order_id,email_message_id,revision_number,revision_kind,revision_fingerprint,parser_version,source_event_at,delivery_at,currency,total_cents,status,is_current,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                9,
                1,
                2,
                2,
                "amendment",
                "old-revision",
                "test",
                "2025-01-01T00:00:00+00:00",
                "2025-01-01T00:00:00+00:00",
                "SGD",
                100,
                "placed",
                0,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        lines = (
            (1, 1, 1, 1, "item"),
            (2, 1, 1, 2, "item"),
            (3, 1, 2, 3, "item"),
            (4, 2, 2, 1, "item"),
            (5, 3, 1, 1, "kg"),
            (6, 4, 1, 1, "item"),
            (7, 5, 1, 1, "item"),
            (8, 6, 1, 1, "item"),
            (9, 7, 1, 1, "item"),
            (11, 8, 1, 1, "item"),
            (10, 9, 1, 1, "item"),
        )
        for iid, rev, pid, line, unit in lines:
            c.execute(
                "INSERT INTO order_items (id,order_revision_id,line_number,line_fingerprint,retailer_product_id,raw_name,quantity,unit,net_cents,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    iid,
                    rev,
                    line,
                    f"line-{iid}",
                    pid,
                    f"Product {pid}",
                    2 if iid in (2, 4) else (99 if iid == 10 else 1),
                    unit,
                    100,
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        c.execute("INSERT INTO order_revision_sources VALUES (1,2,'2026-01-01')")
        c.execute(
            "INSERT INTO product_families VALUES (1,'Family','family','Family definition','2026-01-01')"
        )
        for mid, pid in ((1, 1), (2, 2)):
            c.execute(
                "INSERT INTO product_family_memberships VALUES (?,?,?,?)",
                (mid, pid, 1, "2026-01-01"),
            )
            c.execute(
                "INSERT INTO product_family_events (id,membership_id,version,kind,origin,method,rationale,support_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (mid * 2 - 1, mid, 1, "proposed", "manual", "test", "fixture", "[]", "2026-01-01"),
            )
            c.execute(
                "INSERT INTO product_family_events (id,membership_id,version,kind,proposal_event_id,review_reason,created_at) VALUES (?,?,?,?,?,?,?)",
                (mid * 2, mid, 2, "accepted", mid * 2 - 1, "fixture", "2026-01-01"),
            )
    return settings, (1, 2), (2, 4)


def timeline_call(facts, scope=None):
    settings, products, events = facts
    with closing(connect_database(settings.database_path)) as c, transaction(c, immediate=False):
        return read_timeline(
            c,
            product_ids=products,
            membership_event_ids=events,
            scope=scope or PurchaseScope(date(2026, 9, 20)),
        )


def test_task2_fixture_order_union_and_evidence(timeline_facts):
    result = timeline_call(timeline_facts)
    assert result.summary is not None
    assert result.summary.order_count == 4
    assert result.summary.purchase_day_count == 3
    assert result.summary.purchase_dates == (date(2026, 9, 1), date(2026, 9, 5), date(2026, 9, 20))
    assert result.summary.gaps_days == (4, 15)
    first = next(row for row in result.occurrences if row.order_id == 1)
    assert len(first.item_ids) == 3 and first.source_ids == (1, 2)
    assert first.product_ids == (1, 2) and first.listing_ids == (1, 2)
    assert first.membership_event_ids == (2, 4)
    assert (1, "item", Decimal("3")) in first.quantities
    assert (2, "item", Decimal("1")) in first.quantities


def test_task2_fixture_lifetime_coverage(timeline_facts):
    coverage = timeline_call(timeline_facts).coverage
    assert (
        coverage.eligible_order_count,
        coverage.excluded_order_count,
        coverage.missing_date_count,
        coverage.upcoming_order_count,
        coverage.outside_range_count,
    ) == (4, 3, 0, 1, 0)


def test_task2_fixture_narrow_period(timeline_facts):
    result = timeline_call(
        timeline_facts, PurchaseScope(date(2026, 9, 20), date(2026, 9, 5), date(2026, 9, 5))
    )
    assert result.summary is not None and result.summary.order_count == 1
    assert result.coverage.outside_range_count == 3


def test_membership_states_and_overlapping_families(timeline_facts):
    settings, products, family1_events = timeline_facts
    family2 = create_family(settings, command_id=uuid4().hex, name="Family 2", definition="overlap")
    pending = propose_membership(
        settings,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family2.id,
        expected_version=0,
        origin="manual",
        method="test",
        rationale="test",
    )
    pending_result = timeline_call((settings, (1,), (pending.event_id,)))
    assert pending_result.summary is not None and pending_result.summary.order_count == 0
    rejected = review_membership(
        settings,
        command_id=uuid4().hex,
        membership_id=pending.id,
        proposal_event_id=pending.event_id,
        expected_version=1,
        decision="rejected",
        reason="test",
    )
    rejected_result = timeline_call((settings, (1,), (rejected.event_id,)))
    assert rejected_result.summary is not None and rejected_result.summary.order_count == 0
    reproposed = propose_membership(
        settings,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family2.id,
        expected_version=2,
        origin="manual",
        method="test",
        rationale="test",
    )
    accepted = review_membership(
        settings,
        command_id=uuid4().hex,
        membership_id=reproposed.id,
        proposal_event_id=reproposed.event_id,
        expected_version=3,
        decision="accepted",
        reason="test",
    )
    family2_result = timeline_call((settings, (1,), (accepted.event_id,)))
    assert family2_result.summary is not None and family2_result.summary.order_count == 3
    review_membership(
        settings,
        command_id=uuid4().hex,
        membership_id=1,
        proposal_event_id=1,
        expected_version=2,
        decision="withdrawn",
        reason="correction",
    )
    family1_result = timeline_call((settings, products, family1_events))
    assert family1_result.summary is not None and family1_result.summary.order_count == 2
    assert all(row.membership_event_ids == (4,) for row in family1_result.occurrences)
    assert all(
        row.membership_event_ids == (accepted.event_id,) for row in family2_result.occurrences
    )
    direct = timeline_call((settings, (1,), ()))
    assert direct.summary is not None and direct.summary.order_count == 3
    assert all(not row.membership_event_ids for row in direct.occurrences)


def call(settings, products=(1,), scope=None, events=(), **kwargs):
    with closing(connect_database(settings.database_path)) as c, transaction(c, immediate=False):
        return read_timeline(
            c,
            product_ids=products,
            membership_event_ids=events,
            scope=scope or PurchaseScope(date(2026, 12, 31)),
            **kwargs,
        )


def test_current_delivery_date_and_decimal_quantity(purchase_facts):
    result = call(purchase_facts)
    assert result.summary is not None
    assert result.summary.order_count == 3
    assert result.summary.purchase_dates == (date(2026, 1, 11), date(2026, 1, 12))
    assert result.occurrences[0].quantities == ((1, "kg", Decimal("0.5")),)


def test_missing_date_has_no_fallback(purchase_facts):
    result = call(purchase_facts, scope=PurchaseScope(date(2026, 12, 31)))
    assert result.coverage.missing_date_count == 1


def test_range_boundaries_and_single_day(purchase_facts):
    result = call(
        purchase_facts, scope=PurchaseScope(date(2026, 1, 12), date(2026, 1, 12), date(2026, 1, 12))
    )
    assert result.summary is not None and result.summary.order_count == 2
    assert result.summary.gaps_days == ()


def test_empty_selection_is_complete():
    result = read_timeline(
        cast(sqlite3.Connection, cast(Any, object())),
        product_ids=(),
        membership_event_ids=(),
        scope=PurchaseScope(date(2026, 9, 20)),
    )
    assert result.summary is not None and result.summary.order_count == 0


@pytest.mark.parametrize("products", [(True,), (2**63,), (object(),)])
def test_invalid_ids(products, purchase_facts):
    with pytest.raises(TimelineError):
        call(purchase_facts, products=products)


@pytest.mark.parametrize(
    "scope",
    [
        cast(Any, PurchaseScope)(None),
        cast(Any, PurchaseScope)("2026-09-20"),
        PurchaseScope(datetime(2026, 9, 20)),
    ],
)
def test_invalid_scope_even_empty(scope):
    with pytest.raises(TimelineError):
        read_timeline(
            cast(sqlite3.Connection, cast(Any, object())),
            product_ids=(),
            membership_event_ids=(),
            scope=scope,
        )


@pytest.mark.parametrize("cursor", [("2026-9-1", 1), ("bad", 1), ("2026-09-01", 0)])
def test_invalid_cursor_even_empty(cursor):
    with pytest.raises(TimelineError):
        read_timeline(
            cast(sqlite3.Connection, cast(Any, object())),
            product_ids=(),
            membership_event_ids=(),
            scope=PurchaseScope(date(2026, 9, 20)),
            after_order=cursor,
        )


def test_pagination_cursor_preserves_summary(timeline_facts):
    settings, _, _ = timeline_facts
    with closing(connect_database(settings.database_path)) as c, transaction(c):
        for oid in range(100, 202):
            c.execute(
                "INSERT INTO orders VALUES (?,?,?,?)",
                (oid, 1, f"ORDER-{oid}", "2026-01-01T00:00:00+00:00"),
            )
            c.execute(
                "INSERT INTO order_revisions (id,order_id,email_message_id,revision_number,revision_kind,revision_fingerprint,parser_version,source_event_at,delivery_at,currency,total_cents,status,is_current,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    oid,
                    oid,
                    1,
                    1,
                    "confirmation",
                    f"revision-{oid}",
                    "test",
                    "2026-01-01T00:00:00+00:00",
                    "2026-09-10T02:00:00+00:00",
                    "SGD",
                    100,
                    "placed",
                    1,
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            c.execute(
                "INSERT INTO order_items (id,order_revision_id,line_number,line_fingerprint,retailer_product_id,raw_name,quantity,unit,net_cents,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    oid + 20,
                    oid,
                    1,
                    f"line-{oid}",
                    1,
                    "Product A",
                    1,
                    "item",
                    100,
                    "2026-01-01T00:00:00+00:00",
                ),
            )
    first = timeline_call(timeline_facts)
    assert first.summary is not None and first.summary.order_count == 106
    assert len(first.occurrences) == 100 and first.page.has_more
    settings, products, events = timeline_facts
    with closing(connect_database(settings.database_path)) as c, transaction(c, immediate=False):
        second = read_timeline(
            c,
            product_ids=products,
            membership_event_ids=events,
            scope=PurchaseScope(date(2026, 9, 20)),
            after_order=first.page.after_order,
        )
    assert second.summary == first.summary
    assert len(second.occurrences) == 6 and not second.page.has_more
    assert set(x.order_id for x in first.occurrences).isdisjoint(
        x.order_id for x in second.occurrences
    )
    assert len({x.order_id for x in first.occurrences + second.occurrences}) == 106


def test_singapore_analysis_boundary(timeline_facts):
    settings, products, events = timeline_facts
    with closing(connect_database(settings.database_path)) as c, transaction(c):
        c.execute(
            "INSERT INTO order_items (id,order_revision_id,line_number,line_fingerprint,retailer_product_id,raw_name,quantity,unit,net_cents,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (30, 5, 2, "boundary-kg-1", 1, "Product A", 0.1, "kg", 10, "2026-01-01T00:00:00+00:00"),
        )
        c.execute(
            "INSERT INTO order_items (id,order_revision_id,line_number,line_fingerprint,retailer_product_id,raw_name,quantity,unit,net_cents,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (31, 5, 3, "boundary-kg-2", 1, "Product A", 0.2, "kg", 20, "2026-01-01T00:00:00+00:00"),
        )
    result = timeline_call(
        (settings, products, events),
        PurchaseScope(date(2026, 9, 20), date(2026, 9, 20), date(2026, 9, 20)),
    )
    assert result.summary is not None and result.summary.order_count == 1
    assert result.occurrences[0].order_id == 5 and result.occurrences[0].purchase_date == date(
        2026, 9, 20
    )
    assert (1, "item", Decimal("1")) in result.occurrences[0].quantities
    assert (1, "kg", Decimal("0.3")) in result.occurrences[0].quantities
    assert result.coverage.upcoming_order_count == 1
    assert result.coverage.outside_range_count == 3
    next_day = timeline_call(
        (settings, products, events),
        PurchaseScope(date(2026, 9, 21), date(2026, 9, 21), date(2026, 9, 21)),
    )
    assert next_day.summary is not None and next_day.summary.order_count == 1
    assert next_day.occurrences[0].order_id == 4


def test_cancelled_current_revision_supersedes_eligible_history(timeline_facts):
    settings, products, events = timeline_facts
    with closing(connect_database(settings.database_path)) as c, transaction(c):
        c.execute("UPDATE order_revisions SET is_current=0 WHERE id=1")
        c.execute(
            "INSERT INTO order_revisions (id,order_id,email_message_id,revision_number,revision_kind,revision_fingerprint,parser_version,source_event_at,delivery_at,currency,total_cents,status,is_current,created_at) SELECT 10,order_id,email_message_id,3,'amendment','revision-10',parser_version,'2026-09-21T00:00:00+00:00',delivery_at,currency,total_cents,'cancelled',1,created_at FROM order_revisions WHERE id=1"
        )
        c.execute("UPDATE order_revisions SET delivery_at='2026-09-01T00:00:00+00:00' WHERE id=10")
        c.execute(
            "INSERT INTO order_items (id,order_revision_id,line_number,line_fingerprint,retailer_product_id,raw_name,quantity,unit,net_cents,created_at) SELECT id+20,10,line_number,'superseded-' || id,retailer_product_id,raw_name,quantity,unit,net_cents,created_at FROM order_items WHERE order_revision_id=1"
        )
    result = timeline_call((settings, products, events))
    assert result.summary is not None and result.summary.order_count == 3
    assert all(row.order_id != 1 for row in result.occurrences)
    assert result.coverage.excluded_order_count == 4
    with closing(connect_database(settings.database_path)) as c:
        old = tuple(
            c.execute("SELECT status,is_current FROM order_revisions WHERE id=1").fetchone()
        )
        old_items = c.execute(
            "SELECT count(*) FROM order_items WHERE order_revision_id=1"
        ).fetchone()[0]
    assert old == ("placed", 0)
    assert old_items == 3


def test_direct_product_does_not_attach_memberships(purchase_facts):
    result = call(purchase_facts, events=())
    assert all(not row.membership_event_ids for row in result.occurrences)


def test_scope_rejects_reversed_dates(purchase_facts):
    with pytest.raises(TimelineError):
        call(
            purchase_facts,
            scope=PurchaseScope(date(2026, 9, 20), date(2026, 9, 10), date(2026, 9, 1)),
        )


def test_budget_limits_return_no_partial_totals(timeline_facts, monkeypatch):
    import shopping.purchases.timelines as timelines

    monkeypatch.setattr(timelines, "MAX_ITEMS", 1)
    result = timeline_call(timeline_facts)
    assert result.summary is None and result.occurrences == ()


def test_membership_limit_returns_no_partial_totals(timeline_facts, monkeypatch):
    import shopping.purchases.timelines as timelines

    monkeypatch.setattr(timelines, "MAX_MEMBERS", 1)
    result = timeline_call(timeline_facts)
    assert result.summary is None and result.occurrences == ()


def test_source_limit_returns_no_partial_totals(timeline_facts, monkeypatch):
    import shopping.purchases.timelines as timelines

    monkeypatch.setattr(timelines, "MAX_SOURCES", 1)
    result = timeline_call(timeline_facts)
    assert result.summary is None and result.occurrences == ()


def test_coverage_budget_preserves_period_summary(timeline_facts, monkeypatch):
    import shopping.purchases.timelines as timelines

    monkeypatch.setattr(timelines, "MAX_COVERAGE_ORDERS", 1)
    result = timeline_call(
        timeline_facts, PurchaseScope(date(2026, 9, 20), date(2026, 9, 5), date(2026, 9, 5))
    )
    assert result.summary is not None and result.summary.order_count == 1
    assert not result.coverage.counts_complete
    assert result.coverage.reason == "coverage_budget"
