# Product Family and graph explorer Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` to implement this plan task by task. Checkboxes
> track execution. Preparing this plan does not implement or deploy the feature.

**Goal:** Create and review Product Families, explore their purchase evidence in
the existing app, and inspect delivery-based purchase frequency without changing
historical purchase facts.

**Architecture:** Add authoritative family definitions and append-only membership
decisions to SQLite. Read a bounded, consistent source snapshot into typed graph
records and a separate complete-scope timeline. Render them locally with native
SVG and ordinary JavaScript inside the existing FastHTML/Stitchyard shell.

**Tech Stack:** Python 3.14, uv 0.12.3, the committed lockfile, SQLite, FastHTML,
Stitchyard, existing HTMX, native SVG, and vanilla JavaScript. No new runtime or
frontend package, graph service, RAG, BM25, or model call is required.

**Spec:** [Accepted knowledge graph model](../specs/shopping-knowledge-graph-model.md).
Execution ticket: [21 — Product Family foundation](../issues/21-build-product-family-foundation.md).
Planning date: 20 September 2026. Status: completed locally; see [the execution ledger](ticket-21-execution.md) and [resolved ticket](../issues/21-build-product-family-foundation.md) for verification and process exceptions.

Execution note: checked steps record delivered outcomes and final verification.
Initial test-first ordering was not fully followed in early drafts; no missing red-run
evidence is claimed. Corrective regressions and final acceptance were verified.

## Global Constraints

- SQLite is authoritative. Graph records and calculated timelines are rebuildable.
- Preserve exact Products, Listings, every Item, revision ordering, and all source
  associations. Do not change ingestion, normalization, or the Chat tools.
- Purchase Date is scheduled `delivery_at` in `Asia/Singapore`; no fallback date.
  Current `placed`/`completed` records dated on or before the analysis day qualify.
- Count each Product/Family once per logical Order; gaps use distinct purchase days.
  Keep quantities per exact Product and recorded unit; never infer package conversion.
- Only reviewed, currently accepted memberships affect family frequency. Preserve
  proposal origin, rationale, reviews, withdrawals, and earlier interpretations.
- Only `shopping migrate` changes schema. Add migration 003 if still available;
  never edit migrations 001/002 or migrate the operator's database while developing.
- Use short-lived connections in their owning thread. No browser interaction,
  layout, model call, or filesystem export inside a database transaction.
- Synthetic fixtures use reserved `.invalid` addresses. Actual-data validation is
  local, read-only at its source, and produces no committed household records.
- Keep loopback/private access, existing SQLite runtime safeguards, `0700`
  directories, and `0600` databases/artifacts. Raw emails are immutable.
- Ticket 19's accepted repairs execute separately through ticket 22 after this
  foundation. Predictions, automatic classification, and ingestion repairs are separate.

## Review Focus

1. Two tabs review the same proposal: one decision wins, uncertain retries return
   their original result, and the losing tab explains the conflict (tasks 1, 4).
2. Two members, duplicate lines, alternate wrappers, and same-day Orders must not
   multiply occasions or lose contributing evidence (task 2).
3. Membership or current revision changes between page requests must never combine
   an old graph with a new timeline or silently reuse an invalid cursor (task 3).
4. Rapid selection, HTMX navigation, and Back/Forward must not apply a late response
   to the wrong node or retain invisible listeners (task 5).
5. Large or malicious stored labels and dense neighborhoods must remain escaped,
   bounded, navigable, and honest about incomplete results (tasks 3–5).

## File ownership and interfaces

| File | Responsibility |
| --- | --- |
| `src/shopping/storage/migrations/003_product_families.sql` | Family/event/command tables, dataset identity/generation, indexes and guards |
| `src/shopping/purchases/family_models.py` | Validated command/state records, typed evidence references, purchase scope and timeline records |
| `src/shopping/purchases/families.py` | Atomic create/propose/review operations; bounded connection-taking family reads |
| `src/shopping/purchases/timelines.py` | Eligible order occurrences, days/gaps, exact-product quantities, coverage |
| `src/shopping/knowledge/__init__.py` | Package boundary; no startup work |
| `src/shopping/knowledge/models.py` | Validated graph requests, snapshot identity, typed nodes/edges/view responses |
| `src/shopping/knowledge/snapshot.py` | Indexed bounded reads, snapshot/cursor checks, one transaction per view |
| `src/shopping/knowledge/projection.py` | Pure projection, endpoint/type validation, deterministic serialization |
| `src/shopping/web/graph_security.py` | Graph origin/session/token checks, independent of Chat runtime |
| `src/shopping/web/graph_views.py` | Graph page, inline details/list/timeline, first-run and review controls |
| `src/shopping/web/graph.py` | HTTP validation and orchestration of domain functions |
| `src/shopping/web/static/graph.js` | SVG layout, controls, fetch lifecycle, selection and review interactions |
| `src/shopping/web/factory.py`, `layout.py`, `static/shopping.css` | Route registration, sidebar/script, responsive themed styling |
| `tests/purchases/`, `tests/knowledge/`, `tests/web/`, `tests/browser/` | Focused domain, read/projection, route, and browser coverage |

Use frozen dataclasses for internal records and strict Pydantic request models
(`extra="forbid"`; reject booleans where integer IDs are expected). Public operation
contracts, defined in task 1:

```text
create_family(settings: Settings, *, command_id: str, name: str,
              definition: str) -> FamilyRecord
propose_membership(settings: Settings, *, command_id: str, product_id: int,
                   family_id: int, expected_version: int,
                   origin: Literal["manual", "inferred"], method: str,
                   rationale: str, support_refs: tuple[EvidenceRef, ...] = ())
                   -> MembershipState
review_membership(settings: Settings, *, command_id: str, membership_id: int,
                  proposal_event_id: int, expected_version: int,
                  decision: Literal["accepted", "rejected", "withdrawn"],
                  reason: str) -> MembershipState
read_family_state(connection: sqlite3.Connection, *, family_id: int,
                  limit: int = 501) -> FamilyStatePage
```

`FamilyRecord`: integer `id`, `name`, `definition`, UTC `created_at`.
`EvidenceRef`: allowlisted entity type and positive local row ID; no arbitrary URL/path.
`MembershipState`: `id`, `product_id`, `family_id`, `version`, `state`, `event_id`,
`proposal_event_id`, and the proposal's `origin`, `method`, `rationale`, `support_refs`.
The visible state for a `proposed` event is `pending`; its returned
`proposal_event_id` is that event's own ID (the stored reference remains null).
`FamilyStatePage` contains
the Family, ordered membership states, and `has_more`; it never implies completeness
when the requested limit was exceeded. Read history separately with bounded pages.

Task 2 defines `PurchaseScope(analysis_date, start_date=None, end_date=None)` with date values;
analysis day is frozen when the browser opens or explicitly refreshes the view.
Timezone is always Singapore, date basis always scheduled delivery; serialize both.
`TimelinePage` contains `summary`, `occurrences`, `coverage`, and `page`.
`summary` contains `complete_for_scope`, `order_count`, `purchase_day_count`,
`purchase_dates`, and `gaps_days`. It is null if the complete scope exceeds a budget.
Each occurrence retains Order/Revision/Item/Product/Source IDs, used membership
event IDs, Purchase Date, and quantities grouped by `(product_id, unit)`.

Task 3 defines `GraphViewRequest`, `SnapshotRef`, `GraphReadSnapshot`, `GraphProjection`,
and `GraphView`. The exact read/projection boundary is:

```text
read_graph_view(settings: Settings, request: GraphViewRequest,
                *, expected_snapshot: SnapshotRef | None = None) -> GraphView
project_graph(snapshot: GraphReadSnapshot) -> GraphProjection
validate_projection(projection: GraphProjection) -> None
canonical_payload(view: GraphView) -> bytes
```

`GraphReadSnapshot` contains the source identity/scope, bounded typed authoritative
rows (including reference mappings), selected details/timeline, and paging/coverage.
`GraphProjection` contains nodes and edges. A node has `id`, `type`, `label`, a
typed `record` reference, allowlisted type-specific `attributes`, and optional
`local_url`. An edge has `id`, `type`, `source`, `target`, `state` active/inactive,
and typed row/assertion `support` references. `GraphReadError(code)` uses stable
codes `invalid_input`, `not_found`, `invalid_cursor`, `stale_snapshot`, or
`scope_too_large`. These are domain failures, not raw SQLite exception strings.

Graph response fields are `snapshot`, `scope`, `nodes`, `edges`, `page`, `selection`,
`coverage`, and `build_metadata` (UTC `built_at`, excluded from canonical bytes).
Selection contains the selected node, its safe details, and a
Product/Family `TimelinePage` when applicable. A timeline and its graph always
come from one source transaction. A standalone timeline endpoint is unnecessary.

## Task 1: Persist reviewed family membership

**Files:** Create migration 003, `purchases/family_models.py`, `purchases/families.py`,
and `tests/purchases/test_families.py`. Modify `tests/storage/test_migrations.py`.
**Consumes:** `Settings`, `normalize_text`, `connect_database`, `transaction`, and
  schema verification already in the repository. **Produces:** family operations
and record types defined above; graph snapshot metadata for task 3.

- [x] Add file-backed migration tests for fresh 003 and 002→003 upgrade, preserving
  existing ingestion and Conversations. Retain checksum/dirty-state/concurrent
  migration tests; update latest-schema assertions without erasing 002-specific tests.
- [x] Add the command retry and review tests before implementation. This example
  uses the existing `purchase_facts` fixture, which contains synthetic Product 1:

```python
def test_review_retry_retains_original_outcome_after_withdrawal(purchase_facts):
    from uuid import uuid4
    from shopping.purchases.families import (
        create_family,
        propose_membership,
        review_membership,
    )

    family = create_family(
        purchase_facts,
        command_id=uuid4().hex,
        name="Example drinks",
        definition="Include the example oat drinks; exclude dairy drinks.",
    )
    pending = propose_membership(
        purchase_facts,
        command_id=uuid4().hex,
        product_id=1,
        family_id=family.id,
        expected_version=0,
        origin="manual",
        method="operator",
        rationale="Matches the family definition.",
    )
    command_id = uuid4().hex
    accepted = review_membership(
        purchase_facts,
        command_id=command_id,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=1,
        decision="accepted",
        reason="Reviewed product type.",
    )
    withdrawn = review_membership(
        purchase_facts,
        command_id=uuid4().hex,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=2,
        decision="withdrawn",
        reason="Grouping corrected.",
    )
    replay = review_membership(
        purchase_facts,
        command_id=command_id,
        membership_id=pending.id,
        proposal_event_id=pending.proposal_event_id,
        expected_version=1,
        decision="accepted",
        reason="Reviewed product type.",
    )
    assert replay == accepted
    assert withdrawn.state == "withdrawn" and withdrawn.version == 3
    assert replay.origin == "manual" and replay.version == 2
```

- [x] Run `uv run pytest -q tests/purchases/test_families.py` and establish a failure
  for missing behavior before adding the implementation.
- [x] Add four STRICT tables with these columns/constraints. Store UTC timestamps
  with `utc_iso`; use existing `normalize_text` for unique Family names. Names are
  1–120 characters; definitions/reasons/rationales 1–2000; method 1–120.
  Reject blank text after trimming and names whose normalized form exceeds the
  limit; normalization must not create an empty or silently truncated identifier.

| Table | Columns and constraints |
| --- | --- |
| `product_families` | `id` PK, `name`, unique `normalized_name`, `definition`, `created_at`; immutable definition in v1 |
| `product_family_memberships` | `id` PK, FK `product_id`, FK `family_id`, `created_at`, unique Product/Family pair |
| `product_family_events` | `id` PK, FK `membership_id`, positive `version`, `kind`, `proposal_event_id`, `origin`, `method`, `rationale`, `support_json`, `review_reason`, `created_at`; unique `(membership_id, version)` and `(id, membership_id)` |
| `family_commands` | 32-hex `id` PK, allowlisted `operation`, SHA-256 `fingerprint`, object `outcome_json`, `created_at`; original successful result |

`kind` is proposed/accepted/rejected/withdrawn. A proposal requires manual/inferred
origin, method, rationale, and an array of validated support references; it has no
proposal reference or review reason. A review requires a proposal reference and
review reason; its suggestion fields are null. Use a composite FK from
`(proposal_event_id, membership_id)` to `(id, membership_id)`; also verify that the
target event is a proposal. Limit support to 20 references and 8 KiB serialized.
Add update/delete abort triggers for these four immutable tables; no cascades.
Create `idx_family_memberships_family(family_id, product_id)`.

- [x] Implement the state machine with one short `BEGIN IMMEDIATE` per write:

```text
absent(version 0) -> pending
pending          -> accepted | rejected
accepted         -> withdrawn
rejected         -> pending (new proposal)
withdrawn        -> pending (new proposal)
```

Validate input before entering the transaction. Verify schema without migrating.
Inside the transaction check `family_commands` first: identical command/payload
returns its saved result; changed payload gives `command_conflict`. Then check
references, current version and proposal ID, append one event, and save the result
atomically. A new proposal cannot replace pending/accepted membership. A failed
write creates no receipt or partial membership. Do not retry a stale review as a
new decision. Raise a typed `FamilyError(code, current_state=None)` with stable
codes `invalid_input`, `not_found`, `duplicate_family`, `command_conflict`,
`stale_version`, or `invalid_transition`.

- [x] Test concurrent accept/reject, same command with changed payload, full
  propose/accept/withdraw/re-propose/reject lifecycle, cross-membership proposal
  references, rollback after event insert, and update/delete rejection. Reopen a
  SQLite backup and assert the same state/provenance. Different names may define
  overlapping Families; no inferred duplicate-family semantics or hierarchy.
- [x] Add persisted snapshot identity and source-generation tracking:

```sql
CREATE TABLE graph_dataset_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    dataset_id TEXT NOT NULL UNIQUE CHECK (length(dataset_id) = 32),
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0)
) STRICT;
INSERT INTO graph_dataset_state (id, dataset_id) VALUES (1, lower(hex(randomblob(16))));

CREATE TRIGGER graph_revisions_update AFTER UPDATE ON order_revisions
BEGIN
    UPDATE graph_dataset_state SET generation = generation + 1 WHERE id = 1;
END;
```

Install INSERT/UPDATE/DELETE generation triggers for `retailers`, `products`,
`retailer_products`, `orders`, `order_revisions`, `order_items`, `email_messages`,
and `order_revision_sources`; INSERT triggers suffice for the three guarded
family/domain tables. Command receipts and Chat tables do not change graph state.
Protect the dataset ID against modification/deletion while allowing counter
updates. A rollback must also roll back generation changes. Test a changed current
revision, listing mapping, source association, and family review; each invalidates
an old snapshot. Do not use file mtimes, max IDs, or per-connection `data_version`.
- [x] Run focused family/migration tests and `uv run pyright`. Review this slice
  before connecting it to UI; record results in ticket 21. Commit only the task's
  verified files when repository execution/commit instructions permit it.

## Task 2: Calculate trustworthy purchase timelines

**Files:** Create `purchases/timelines.py`, `tests/purchases/test_timelines.py`;
extend `family_models.py`. **Consumes:** accepted membership states and existing
purchase tables. **Produces:** `PurchaseScope`, `TimelinePage`, and
`read_timeline(connection, *, product_ids: tuple[int, ...], scope: PurchaseScope,
membership_event_ids: tuple[int, ...], after_order: tuple[str, int] | None = None)
-> TimelinePage`. The caller owns the read transaction.

- [x] Build a synthetic file-backed fixture with two exact Products A/B, reviewed
  into one Family, and these current Orders. Use explicit column lists; unique
  synthetic fingerprints; `source@example.invalid` as source identity. Keep an
  older revision and a second source wrapper on Order 1.

| Order | UTC delivery | Status | Lines | Analytic result |
| --- | --- | --- | --- | --- |
| 1 | 2026-08-31T18:00:00+00:00 | placed | A×1, A×2, B×1 | Sep 1, one occurrence |
| 2 | 2026-09-01T10:00:00+00:00 | completed | B×2 | Sep 1, separate Order |
| 3 | 2026-09-05T02:00:00+00:00 | placed | A×1 | Sep 5 |
| 4 | 2026-10-01T02:00:00+00:00 | placed | A×1 | Upcoming |
| 5 | null | placed | A×1 | Unknown date |
| 6/7/8 | 2026-09-06T02:00:00+00:00 | cancelled/refunded/unknown | A×1 each | Excluded status |

Define `timeline_facts` in this test file to return `(settings, product_ids,
accepted_event_ids)` after constructing those records. The executable assertion
for its eligible population is:

```python
def test_order_union_and_singapore_day_gaps(timeline_facts):
    from contextlib import closing
    from datetime import date
    from shopping.purchases.family_models import PurchaseScope
    from shopping.purchases.timelines import read_timeline
    from shopping.storage.connection import connect_database, transaction

    settings, product_ids, accepted_event_ids = timeline_facts
    with closing(connect_database(settings.database_path)) as connection:
        with transaction(connection, immediate=False):
            result = read_timeline(
                connection,
                product_ids=product_ids,
                scope=PurchaseScope(analysis_date=date(2026, 9, 20)),
                membership_event_ids=accepted_event_ids,
            )
    assert result.summary is not None
    assert result.summary.order_count == 3
    assert result.summary.purchase_day_count == 2
    assert result.summary.purchase_dates == (date(2026, 9, 1), date(2026, 9, 5))
    assert result.summary.gaps_days == (4,)
    first = next(row for row in result.occurrences if row.order_id == 1)
    assert len(first.item_ids) == 3
    assert len(first.source_ids) == 2
```

- [x] Run the test to establish the missing implementation, then implement scoped
  joins through Product→Listing→Item→current Revision→Order. Do not reuse the
  completed-only, fallback-date `purchase_history` view. Retrieve source links
  separately to avoid multiplying Item rows; union the primary source and every
  `order_revision_sources` association.
- [x] Convert known UTC timestamps with `ZoneInfo("Asia/Singapore")`, apply
  eligibility, and group Items by logical Order. Use this calculation after reading
  complete qualifying rows; retain the original Item records as evidence:

```python
purchase_dates = tuple(sorted({row.purchase_date for row in occurrences}))
gaps_days = tuple(
    (later - earlier).days for earlier, later in zip(purchase_dates, purchase_dates[1:])
)
```

For supplementary coverage, classify each matching current Order once, in this
precedence: excluded status, missing date, upcoming, outside selected range,
eligible. Read eligible-period inputs first. Lifetime coverage counts use separate
bounded aggregate queries; they are not a prerequisite for a complete period
summary. If their budget is exhausted, return null for unavailable counts with
`coverage.counts_complete=false` and a reason. Do not infer zero or lifetime
coverage from only the period's rows. Unknown/upcoming records can still be
inspected through separately bounded graph expansion.
Use inclusive user dates converted to UTC half-open bounds for indexed queries.
Classification edges stay visible regardless of this activity filter. Quantities
sum only within the same exact Product and recorded unit; use decimal conversion
of stored values to avoid introducing binary-float artifacts in displayed sums.

- [x] Bound complete selected-scope input to 500 active members, 5,000 Item rows,
  and 5,000 source references for eligible-period activity, using limit-plus-one
  probes before materialization. Supplemental lifetime coverage has its own query
  budget within the overall view budget; failure there does not erase an already
  complete period summary.
  Timeline pages return at most 100 occurrences; summary counts/dates/gaps refer
  to the complete eligible scope, not the current page. Over budget returns
  `summary=None`, `coverage.reason="scope_too_large"`, and no partial totals;
  request a narrower range for activity/evidence limits, or select an exact
  Product for the membership limit. Empty accepted membership produces complete zero
  counts. Product selection works without any family membership.
- [x] Test pending/rejected/withdrawn membership, overlapping Families evaluated
  independently, history mode not changing frequency, cancellation superseding a
  formerly eligible revision, no-date fallback, single-day/empty gaps, range
  boundaries, pagination, mixed units, and over-budget scope. Add a large lifetime
  history with a small selected period: period counts remain complete while
  unavailable lifetime coverage is explicitly null. Assert hiding Item
  or Source nodes has no effect on this API's inputs or counts.
- [x] Run `uv run pytest -q tests/purchases/test_timelines.py tests/purchases/test_families.py`
  and `uv run pyright`; record the independently reviewed result before task 3.

## Task 3: Read and project bounded, consistent graph views

**Files:** Create the four `knowledge/` files and `tests/knowledge/test_graph.py`;
add needed indexes to the unreleased migration 003. **Consumes:** task 1's metadata
and family reads, task 2's connection-taking timeline function. **Produces:** the
graph contracts listed under File ownership; no web or Chat dependency.

- [x] Define `GraphViewRequest`: literal `query` (0–200 characters), optional
  `selected_id`, at most 12 distinct `expanded_ids`, `mode` current/history,
  allowlisted `node_types`, `purchase_scope`, and optional overview/relationship/
  timeline cursors. Default overview has 40 roots, maximum 80. Validate IDs, date
  ranges, types, and cursor sizes before SQL. Default root types are Family/Product.
- [x] Define `SnapshotRef(dataset_id, source_generation,
  projection_schema_version=1, method_version="delivery-family-v1")`. The source
  generation covers both facts and membership state. Include the accepted
  membership event IDs and listing/Product mapping IDs used by each timeline.
  This identifies an interpretation; it does not promise old DB states can be
  reconstructed without a saved database snapshot.
- [x] Write the changed-snapshot test before the reader. Use existing
  `purchase_facts`; its `order_revisions` row 1 is mutable in `is_current`:

```python
def test_changed_current_revision_rejects_old_snapshot(purchase_facts):
    from contextlib import closing
    from datetime import date
    import pytest
    from shopping.knowledge.models import GraphReadError, GraphViewRequest
    from shopping.knowledge.snapshot import read_graph_view
    from shopping.purchases.family_models import PurchaseScope
    from shopping.storage.connection import connect_database, transaction

    request = GraphViewRequest(
        purchase_scope=PurchaseScope(analysis_date=date(2026, 9, 20)),
    )
    before = read_graph_view(purchase_facts, request)
    with closing(connect_database(purchase_facts.database_path)) as connection:
        with transaction(connection):
            connection.execute("UPDATE order_revisions SET is_current=0 WHERE id=1")
    with pytest.raises(GraphReadError, match="stale_snapshot"):
        read_graph_view(purchase_facts, request, expected_snapshot=before.snapshot)
```

- [x] Run the test, then implement one read transaction: `PRAGMA query_only=ON`,
  `transaction(immediate=False)`, read generation first, verify expected snapshot,
  read roots/neighborhood and selected details/timeline, close connection. Pure
  projection and serialization follow outside the transaction. Use fixed SQL
  query templates/parameters; escape `%`, `_`, and backslash for literal search.
- [x] Use typed node IDs `dataset:type:row_id`, including all eight spec entities.
  Factual edge IDs include predicate and authoritative endpoint identities;
  `MEMBER_OF` includes membership and accepted decision IDs. Validate predicate
  endpoint types against the spec diagram. For Sources emit only ID, source kind,
  parse status/parser version, and safe timestamps. Retain every source association.
  Product/Order links are generated application paths, never stored arbitrary URLs.
- [x] Read only requested neighborhoods with indexed queries and limit-plus-one.
  Cap a response at 200 nodes/400 edges, an expansion at 60 relationships, and
  serialized JSON at 1 MiB. Include endpoints atomically or omit the edge and mark
  continuation. Graph `shown_*` counts describe only the displayed subset; they
  never substitute for timeline totals. Label truncation even when the global cap
  prevents another expansion; collapse or narrow the view to continue.
- [x] Implement keyset cursors as validated, bounded base64url JSON containing
  dataset/generation, query-and-scope fingerprint, relationship root/type, and
  last ordering key. All cursor fields are untrusted query parameters; they
  confer no authority. Cursors are valid only for identical filters/snapshot.
  Return `stale_snapshot` or `invalid_cursor`, never an inconsistent continuation.
  A page response is the complete bounded replacement view for the requested
  roots/expansions, not an unbounded append-only browser graph.
- [x] Add `(is_current, delivery_at, id)` on revisions and `(order_revision_id, id)`
  on items if query-plan evidence shows they are needed beyond existing indexes.
  Set a connection progress handler every 5,000 VM instructions; abort after
  2,000,000 instructions or 2 seconds. Clear it on exit. These are internal v1
  safety bounds, test-overridable; tune only against measured synthetic workloads.
  Return `scope_too_large` for essential-read budget exhaustion and retain the
  browser's last view. If only optional coverage exceeds its budget after the
  selected summary is complete, return that summary with unavailable coverage
  counts instead; do not run additional queries after the overall work limit.
- [x] History mode adds prior revisions/items and previously accepted membership
  edges marked inactive with their decision IDs. Pending/rejected proposals stay
  in review/details. Current eligibility and accepted membership continue to drive
  the timeline. Date filters scope dated activity; unknown dates have a separate
  labeled branch. Type visibility filters only presentation, never analytic inputs.
- [x] Implement canonical sorted serialization (node/edge IDs, ordered refs, sorted
  keys); omit build time from canonical bytes. Validate before exposing/exporting
  output. A filesystem export command is not required for this ticket. If an
  existing derived file is replaced, use restrictive permissions and atomic rename.
- [x] Test deterministic output, all predicates/source links, empty/missing nodes,
  unassigned Products, literal searches, snapshot changes from mapping/review/source
  writes, simultaneous reads/writes, invalid cursors, rollback not invalidating a
  snapshot, and a dense synthetic graph exceeding every bound. Assert no dangling
  endpoints or forbidden source metadata. Test selected summary is unchanged by
  graph pagination/type filters and reports incomplete rather than capped totals.
- [x] Run `uv run pytest -q tests/knowledge/test_graph.py tests/purchases/test_timelines.py`
  and `uv run pyright`; inspect representative `EXPLAIN QUERY PLAN` output on the
  large synthetic fixture, recording only structural findings.

## Task 4: Expose the page and protected first-run/review workflow

**Files:** Create `web/graph.py`, `graph_security.py`, `graph_views.py`, and
`tests/web/test_graph_web.py`; modify `factory.py`, `layout.py`, and
`tests/web/test_web.py`. **Consumes:** family operations and `read_graph_view`.
**Produces:** `register_graph(app, settings)`, `graph_page(view)`, and these routes:

| Route | Behavior |
| --- | --- |
| `GET /graph` | Existing shell or HTMX main-view fragment; graph toolbar, SVG/list, inline details, review entry |
| `GET /graph/view` | Validated query → one graph/details/timeline bundle |
| `GET /graph/token` | Requires `X-Graph-Page: 1`; issue session-bound mutation token |
| `GET /graph/reviews` | Keyset-paginated pending/current/history membership states, maximum 50 per page |
| `POST /graph/families` | `command_id`, `name`, `definition` → created Family |
| `POST /graph/memberships` | One Product/Family proposal command → pending state |
| `POST /graph/memberships/{id}/review` | Version/proposal-bound accept/reject/withdraw command → recorded state |

Use `/graph/view` search for selectable existing Products. A multi-select UI sends
one idempotent proposal command per Product and shows individual outcomes; it
does not claim all-or-nothing batching. Review pagination also carries generation
and filter identity and rejects stale continuation.

- [x] Test direct/HTMX page loads and the missing-origin-configuration state before
  implementing routes. Add Graph navigation; update the old Graph-absent assertion
  and expected latest schema version. Keep app startup verification-only.
- [x] Apply an independent guard using the existing validated `app_origin`:
  without configuration, Graph returns 503 with setup guidance and no data/write
  actions. Match Host exactly, validate supplied Origin, reject cross-site and
  same-site `Sec-Fetch-Site` requests; normal top-level `none` navigation is allowed.
  Writes require exact Origin plus the session token; missing Origin fails closed.
  Do not change Chat guards/runtime as part of this task.
- [x] Use `TimestampSigner(app.secret_key, salt="shopping-graph-page-v1")`, a random
  session `graph_id`, and a 30-minute token lifetime. The token endpoint requires
  the custom header and same-origin checks; writes carry `X-Graph-Token`.
  Never put tokens in URLs, localStorage, logs, graph exports, or history state.
  Set private/no-store, no-referrer, nosniff, and `frame-ancestors 'none'` headers.
  Preserve the existing secure/same-site session cookie configuration; no CORS.
- [x] Validate JSON Content-Type, a 16 KiB body cap, UUID-hex command IDs, strict
  fields/versions, and text/reference bounds. Map invalid input to 400, auth guard
  failure to 403, missing entity to 404, review/snapshot conflicts to 409, and
  bounded-work failure to 422. Do not expose SQL/raw exception contents.
- [x] Add a full route flow using synthetic Product 1: obtain token, create Family,
  propose Product, confirm pending contributes no active edge, accept, fetch view,
  withdraw, and inspect preserved review history. Include retry/conflict checks:

```python
# In test_graph_web.py, graph_client is TestClient(create_app(settings_with_origin)),
# populated from purchase_facts; its base_url and app_origin are both ORIGIN.
ORIGIN = "http://127.0.0.1:8000"


def test_graph_token_is_required_for_family_write(graph_client):
    payload = {
        "command_id": "a" * 32,
        "name": "Example drinks",
        "definition": "Include oat drinks; exclude dairy drinks.",
    }
    denied = graph_client.post(
        "/graph/families",
        json=payload,
        headers={"Origin": ORIGIN},
    )
    assert denied.status_code == 403
    token_response = graph_client.get(
        "/graph/token",
        headers={"X-Graph-Page": "1", "Origin": ORIGIN},
    )
    token = token_response.json()["token"]
    headers = {"Origin": ORIGIN, "X-Graph-Token": token}
    created = graph_client.post("/graph/families", json=payload, headers=headers)
    assert created.status_code == 201
    retry = graph_client.post("/graph/families", json=payload, headers=headers)
    assert retry.json() == created.json()
```

Also test wrong Host/Origin, missing Origin, expired/cross-session token, oversized
body, unsupported fields, and malicious stored Family/Product labels. Family
create returns 201 (also for exact replay); proposal/review returns 200. A successful
write response includes its command outcome, then the UI requests a fresh entire
view. If refresh fails, retain the old view labeled stale and report the saved
decision; do not portray a successful mutation as rolled back.
- [x] Use existing PageFrame/PageHeader/Panel/Icon components and theme conventions.
  Empty data and no-family states explain the next action. Family definitions are
  create-only in v1; no editing, deletion, automatic assignment, or bulk acceptance.
- [x] Run `uv run pytest -q tests/web/test_graph_web.py tests/web/test_web.py tests/web/test_chat_web.py`
  and `uv run pyright`. Confirm Graph access needs no model inference or Chat connection.

## Task 5: Make graph exploration usable across navigation and devices

**Files:** Create `static/graph.js` and `tests/browser/graph_explorer.js`; extend
`graph_views.py`, `static/shopping.css`, and `layout.py`. **Consumes:** task 4 routes
and typed view payload. **Produces:** a working local SVG explorer and equivalent
keyboard relationship list, integrated with the existing app shell.

- [x] Add browser assertions for `#shopping-graph`, a toolbar, selected-node
  inspector, and relationship list. Use a synthetic dev database with an accepted
  Family, an unassigned Product, and enough facts to expand an evidence path.
  Run against the unimplemented page to establish the missing interactions.
- [x] Load `graph.js` once from the shared document, not from swapped fragments.
  Use one controller per `#shopping-graph` root, guarded with a WeakMap. Mount on
  initial load, `htmx:afterSwap`, and `htmx:historyRestore`; dispose before the root
  is removed or replaced. Cancel pending requests/animation frames and remove
  controller listeners on disposal. Do not modify the order drawer's global state.
  Set `hx-history="false"` on the Graph root to prevent HTMX from storing this
  page's private graph/review DOM in local history storage; restoration refetches
  the page/state. Test the history-cache-miss path as well as ordinary navigation.
- [x] Make `loadView()` own one AbortController and a monotonically increasing
  request ID. Only the latest successful request may replace the entire graph and
  matching selection/timeline. Implement its response-acceptance rule as:

```javascript
const requestId = ++this.requestId;
this.pending?.abort();
this.pending = new AbortController();
const response = await fetch(url, {signal: this.pending.signal, cache: "no-store"});
const payload = await response.json();
if (!this.root.isConnected || requestId !== this.requestId) return;
if (!response.ok) { this.showError(payload); return; }
this.renderView(payload);
```

The controller defines `root`, `requestId=0`, `pending=null`, `showError(payload)`
and `renderView(payload)`. Its caller catches abort/network/JSON errors and
preserves the last valid view. A 409 displays a Refresh action that drops cursors
and obtains a fresh snapshot; it never merges old and new payloads.
- [x] Use a deterministic layered SVG layout by entity type with stable ID ordering,
  readable labels, and a selected-node highlight. Keep model relationships in
  response records; layout cannot add inferred edges. Use textContent/SVG text
  nodes for stored values. Clip long canvas labels (120 characters) while keeping
  safe full detail text available in the inspector. No external fonts/layout service.
- [x] Implement pointer pan with capture, wheel/buttons zoom clamped to 0.25–4,
  Fit and Reset controls, and node select/Expand/Collapse controls. Convert pointer
  coordinates through the SVG screen transform; tolerate absent matrices/detached
  elements. Use a click-distance threshold to distinguish selection from dragging.
  Touch users can use buttons and the list; dragging is never required.
- [x] Show complete selected-scope timeline counts independently of the canvas's
  shown-node/edge counts. Display Purchase Date range, analysis day, history/current
  mode, provisional identity, unassigned state, upcoming/unknown/excluded counts,
  and parsed-records-only coverage. No invented fulfillment or archive completeness.
  Family details include criteria, member origin/review state, evidence links,
  delivery days/gaps, and quantities per exact Product. History assertions are
  visibly inactive; proposals appear only in the review area.
- [x] Put graph filters/selection in URL query parameters. Use the same state parser
  for direct links and browser history; popstate refetches a full view and drops
  transient cursors/tokens. Persist navigation state, not private result payloads,
  in history. Preserve entered review form text after errors; retry uses the same
  command ID/payload until the intent changes. Refresh expired tokens once before
  retrying the same idempotent command. Announce saved decisions and conflicts.
- [x] Use an inline inspector and responsive stacked panels; provide focusable
  relationship buttons/list and real keyboard-operable controls, selected state,
  screen-reader status announcements, and type labels/icons as well as colors.
  Display both light/dark themes and honor reduced motion. Keep destructive review
  wording explicit; node selection/dragging never executes a membership write.
- [x] Implement `tests/browser/graph_explorer.js` using the existing browser
  harness's `page` object. Assertions must cover actual interactions, for example:

```javascript
const before = await page.locator("[data-graph-order-count]").innerText();
await page.getByRole("checkbox", {name: "Show Source nodes"}).uncheck();
await page.getByRole("button", {name: "Apply filters"}).click();
await page.locator("#shopping-graph[data-load-state='ready']").waitFor();
const after = await page.locator("[data-graph-order-count]").innerText();
if (after !== before) throw new Error("Visibility changed purchase counts");
```

Additionally test first Family/proposal/accept/withdraw flow, search, evidence
navigation, zoom/fit/reset, expand/collapse, 390px/desktop layout, keyboard-only
selection, light/dark contrast, direct load, sidebar HTMX entry, Back/Forward,
repeated visits, delayed A→B selection, leaving mid-request, failed expansion,
stale review/snapshot recovery, and zero requests to external graph assets/services.
Assert only one request per action after repeated mounting.
- [x] Run the browser script with the repository browser-verification workflow
  against the synthetic server, plus `uv run pytest -q tests/web/test_graph_web.py`.
  Record browser evidence and viewport sizes separately from Python checks.

## Task 6: Verify integration, packaging, and authorized actual-data coverage

**Files:** Modify `.github/workflows/ci.yml`, `README.md`, `docs/MVP_PLAN.md`, and
ticket 21; update `CONTEXT.md` only if implemented vocabulary differs. Extend
focused tests above for any newly found integration defect.
**Consumes:** complete graph workflow from tasks 1–5. **Produces:** verified local
feature, clear limitations, and a handoff that keeps host verification separate.

- [x] Extend existing wheel resource assertions to require migration 003 and
  `graph.js`; update schema-version 2 expectations to 3 where they mean latest.
  Preserve explicit earlier-version tests. Run Graph page/asset smoke checks from
  the installed wheel with configured loopback origin; do not require Ollama.
- [x] Exercise actual records only on a disposable private SQLite backup made with
  SQLite's backup API, not a plain live-file copy. Open the source URI read-only,
  place the copy in ignored `data/` with existing restrictive permissions, migrate
  only that copy, and compare structural counts/evidence paths against the prior
  audit. Do not run actual email import or alter original facts/family assignments.
  The prior audit's 15 Orders, 110 Items, 41 Products and two failed imports are a
  dated observation; recheck instead of hard-coding them into application behavior.
  No Family total is asserted before concrete memberships have been reviewed.
- [x] Verify no-family actual-data browsing, unassigned Product history, delivery
  ranges, representative repeated-line/same-day behavior where present, and safe
  evidence links. Keep private screenshots/output local. Record only structural
  outcomes, discrepancies, and limitations in the ticket. Synthetic tests remain
  the proof for absent states such as cancellation or concurrent reviews.
- [x] Run the repository checks once after final implementation changes:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
git ls-files -co --exclude-standard -z | xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline
```

- [x] Reproduce the wheel smoke-test sequence in `.github/workflows/ci.yml` using
  temporary wheel/venv/state paths: build the wheel without build isolation, sync
  runtime dependencies from the lockfile, install the wheel without dependencies,
  run `uv pip check`, assert migration/static resources, make installed package
  read-only, and run `shopping migrate` plus web/health checks from outside the
  source tree. Confirm both `001_ingestion.sql` and `003_product_families.sql` are
  packaged and schema 3 is usable. Do not claim source-tree tests prove packaging.
- [x] Update README/MVP implementation status and existing origin requirement for
  Graph. Keep predictions, Chat remediation, and homelab verification marked pending.
  Obtain code review of domain counts, write protection, snapshot consistency,
  and browser lifecycle. Fix findings and rerun affected checks; record evidence.
- [x] Resolve ticket 21 only when its acceptance is satisfied. Ticket 22 is the
  next implementation priority; ticket 19 remains its resolved decision record.
  No homelab migration/restart/deploy is performed just by completing this plan.

## Technical references and handoff

- [HTMX lifecycle events](https://htmx.org/events/) — cleanup, swaps, and history
  restoration are separate lifecycle events; test each supported navigation path.
- [HTMX history caching](https://htmx.org/attributes/hx-history/) — Graph disables
  stored page snapshots and restores its URL from the server.
- [SVG screen transforms](https://developer.mozilla.org/en-US/docs/Web/API/SVGGraphicsElement/getScreenCTM)
  and [pointer capture](https://developer.mozilla.org/en-US/docs/Web/API/Element/setPointerCapture)
  support the local pan/zoom interaction; they do not determine business relationships.

The model and first-run workflow have already been accepted. The technical choices
above close implementation-planning gaps without activating any real membership.
Recommended execution is task-by-task with review at the storage, consistent-read,
and UI boundaries. This document records no executed test, migration, or fix.
