# SDD ledger — plan: .scratch/shopping-assistant/plans/product-family-graph-explorer.md

## Historical/current status

This ledger records the earlier native-SVG implementation path. That renderer and
its interim claimed status were superseded by the locally bundled Cytoscape
redesign and the resolved tickets 21–23. Current implementation and final browser
evidence are recorded in the graph redesign plan and ticket completion answers.

Ticket: 21. Base commit: `b5e601863167824941f1f405ec57804cb2e32f15`.
Branch: `codex/ticket-21-graph`. User explicitly requested Luna/low implementation
with controller review/corrections until correct. No deployment or ticket 22 work.

Existing uncommitted planning changes predate implementation and are preserved.
Ruling: use a feature branch in the existing checkout — all approved plans are
uncommitted here and only one implementer will own mutable source at a time;
avoids moving or losing the user's active planning work. Review compares source
against the recorded base, with planning-only changes tracked separately.
Ruling: keep execution records under this repository's required `.scratch/shopping-assistant/`
planning root rather than the skill's default workspace. No production writes.
Ruling: user-specified Luna/low overrides the skill's suggested implementer tier.
The controller reviews each stage and returns concrete fixes to the implementer.
No task commits/pushes are required; preserve a reviewable working-tree diff.

## Preflight consistency review

| Tasks | Contract or overlap | Finding/ruling |
| --- | --- | --- |
| 1 | Family state, migration, retry tests | Consistent; pending result points to its own proposal event |
| 2 | Eligibility/counts versus coverage bounds | Complete period counts are independent of optional lifetime coverage |
| 3 | Graph read versus history/filter behavior | One read transaction; visibility never scopes frequency |
| 4 | Protected writes versus page reads | Independent graph guard uses configured origin; no Chat runtime change |
| 5 | Navigation versus asynchronous rendering | Abort/generation guard and fresh history restoration required |
| 6 | Actual-data checks versus immutable originals | Backup API read-only source; migrate disposable copy only |
| 1–2 | Family states and family_models | Task 2 adds timeline records without changing review commands |
| 1–3 | Dataset generation, family reads, migration indexes | Track facts and memberships; no per-connection data_version identity |
| 1–4 | Create/propose/review commands | Command replay precedes version checks; same HTTP result on retry |
| 2–3 | read_timeline(connection), PurchaseScope | Caller owns snapshot; selected summary is independent of canvas limits |
| 3–4 | GraphViewRequest, GraphView, errors | Typed JSON and exact error codes, no raw SQL errors |
| 3–5 | IDs, cursors, selection/timeline | Replace complete bounded view; never merge snapshots |
| 4–5 | graph_views/layout/static lifecycle | One controller/root; inline inspector, not global order drawer |
| 1–6 | Migration and installed-wheel resources | Verify 001/003 and schema 3 from installed wheel |
| 4–6 | Web shell, CI assets/docs | Preserve baseline navigation/Chat, add graph resource checks |
| 5–6 | Browser acceptance | Synthetic server first, actual copy validation separately |

## Progress

- Baseline checks: `uv run pytest -q` — 287 passed, 1 optional Ollama smoke skipped,
  1 pre-existing Fastcore deprecation warning, 5.70 seconds.
- Task 1: complete — Luna/low source plus focused test agent; controller and
  Terra/high source review/correction loop completed. Final controller verification:
  26 family/validation/migration tests passed; full pyright passed. Ruff passed.
- Task 2: complete — controller reviewed source and concrete synthetic fixture,
  membership states/overlap, superseded cancellation, Singapore boundaries, mixed
  units, 105-order pagination and scope budgets. Combined family/timeline/migration/
  security verification: 64 tests passed; timeline type and Ruff checks pass.
- Task 3: complete — bounded snapshot/projection readers and timeline integration.
- Task 4: complete — protected Graph routes/workflow; body and history fixes verified.
- Task 5: complete — native SVG UI, explicit review writes, browser acceptance.
- Task 6: complete — actual-copy, full checks, installed wheel, docs and final review.

## Review and corrections

Each stage's findings, corrections and test evidence are appended here before
marking that stage complete. Ticket 21 remains claimed until all acceptance passes.

Task 1, early controller findings sent to implementer:
- Review state must join its proposal for original origin/rationale/support.
- Command receipts must replay their original full result after later decisions.
- A review must target the current proposal, not any old proposal for the pair.
- SQL must enforce proposal/review field shapes and bounded JSON types.
- Evidence references must resolve to authoritative rows within the transaction.
- Required concurrent review, rollback, backup, re-proposal, generation, and
  upgrade tests are implementer deliverables; three happy-path tests are insufficient.
- Reporting stall diagnosed: the implementer tried an app-level
  `send_message_to_thread` call instead of subagent messaging. Interrupted and
  resumed the same Luna/low agent with an explicit prohibition on app-thread tools;
  it must use `collaboration.send_message` to `/root` or a normal final response.
  No task is marked complete based on its stale draft report.
- Task 1 source review (`/root/ticket21_family_review`, Terra/high): transaction,
  original-result replay, proposal provenance and generation coverage are sound;
  requested malformed-evidence input validation and stronger SQL review-reference
  guards. Tests are being completed by `/root/ticket21_family_tests` (Luna/low).
- Ruling: add a SQL guard requiring reviews to reference a same-membership proposed
  event, and enforce the 20-reference array cap. Typed polymorphic reference/row
  existence validation remains in the public command boundary; do not duplicate
  the complete application validator or state machine in SQL. The spec requires
  valid reviewed assertions, not a second implementation of the domain service.
- Final source re-review confirmed corrections; controller verified the remaining
  `read_family_state` oversized-ID guard and its regression. Original-result replay,
  competing reviews, rollback/generation, provenance/backup and schema 002→003
  preservation now have meaningful coverage. Earlier partial reports are superseded
  by this verified Task 1 result. TDD was incomplete in the initial draft; regression
  corrections were verified, and no prior red-run evidence is invented.

Actual-data validation baseline: used the SQLite backup API with source URI
`mode=ro`, destination `data/ticket-21-validation/actual.sqlite3` (ignored, 0600,
private directory). Integrity check passed; schema 2, 15 orders/revisions,
110 items, 41 Products/Listings, 17 sources. Original database not migrated.

Ruling: the plan's browser example assumes a Playwright `page` variable, but this
repository uses `agent-browser eval --stdin` with DOM JavaScript. Task 5 must use
that real harness (or a deliberately provisioned test runner), not commit an
unrunnable example. Exercise real fetch/DOM interactions on a synthetic server;
controller separately checks screenshots, responsive states, and navigation.

Ruling: `.gitignore` currently has unanchored `knowledge/`, which also ignores the
planned `src/shopping/knowledge/` Python package (`git check-ignore -v` confirms).
Task 3 must anchor that private-artifact rule to `/knowledge/` so source is tracked
and packaged, while root private graph artifacts remain ignored. Verify both paths.

Ruling: while Task 2 is corrected, independently implement only Task 4 security
helpers and isolated tests. These have no timeline/graph dependency and disjoint
file ownership, so parallel work cannot build on the pending analytic defects.
The full Task 4 route integration remains gated on Task 3 contracts.

Task 2 review loop: first two drafts were incomplete despite passing the two
shallow timeline tests. Controller rejected them, split source corrections from
the required synthetic regression matrix, and requested all remaining tests.
Source re-review is independent; Task 2 is not complete on the draft's test count.
Task 4 security helper initial draft is in correction: bounded streaming before
copy, depth/non-finite JSON handling, normal exception behavior, and the missing
origin/token/body-boundary regression cases are required before approval.

Task 4 security helper: source review/corrections and required token/origin/size
regressions verified by controller; 12 tests pass. Full route/UI integration is pending.
Task 2 core fixture now verified: combined timeline/security suite 33 passed and
full pyright passed. Remaining membership-transition/pagination/budget tests are
being completed before final Task 2 approval.
Ruling: develop Task 3's pure data contracts/projection independently while the
remaining timeline tests run; no snapshot reader or analytical call integration
until Task 2 is approved. This isolates test-independent work behind stable records.
Ruling: reuse the available Luna/low implementer seats because spawning another
worker hit the agent-thread limit. Keep assignments narrow and file ownership
disjoint; controller review still gates integration.

Task 2 final corrections: current-only supplied membership evidence; direct Product
reads attach no family assertions; SQL limit-plus-one; Singapore half-open bounds;
independent optional coverage with honest null counts; strict input/cursor/date
validation; deterministic evidence ordering; source interrupt handling. Controller
rejected shallow tests whose names implied absent scenarios and required concrete
fixture/pagination/transition replacements. Remaining unrelated tests are unchanged.

Ruling: split Task 3 SQL record/relationship helpers into an internal `records.py`
module so the snapshot coordinator stays readable. Public graph contracts and
transaction ownership remain unchanged. No new dependency or storage authority.

Task 3 progress and review: models/projection have 13 passing focused tests;
records have 7, but controller requested root cursor overflow, independent
unassigned boolean, and stronger root paging/literal search assertions. Initial
relationship draft was rejected: reverse edge directions, missing provenance,
unreviewed family edges, unbounded reads and ignored dates. Rebuild is split into
reviewable predicate groups before snapshot integration. Initial cursor draft is
in correction for semantic validation before stale comparisons (including bool
versions/generations, root types and predicate/endpoint validation). No incomplete
Task 3 result is approved for route integration.

Index measurement: temporary synthetic database with 6,000 additional old Orders;
62 eligible narrow-period Item rows. Existing plan used listing/item indexes and
about 67,500 VM instructions. Adding `(is_current, delivery_at, id)` selected the
date index plus existing item revision index, about 1,500 instructions. Added
`idx_order_revisions_graph_delivery` to unreleased migration 003; no additional
item index is needed. The operator's original database remains untouched.

Ruling: after repeated incomplete relationship drafts, the controller supplied a
concrete code-level correction during review for Luna
to apply and test. This preserves the requested Luna implementation/review loop
while making the correction actionable. A separate suggested patch containing
placeholder dispatch was rejected and is marked not to apply. Production now uses
fixed root-incident SQL templates, canonical directions, bound keyset predicates
and SQL limits; tests are being strengthened before final snapshot integration.

Task 3 reviewed pieces: controller verified 45 passing projection/cursor/record
tests and seven-file Ruff format check. Selection helper is in correction for
complete details and exactly one final timeline call (no SQL after optional
coverage exhaustion). No Graph route/UI is claimed complete yet.

Task 3 helper re-review: 53 focused tests passed before the new snapshot smoke
test. Selection lifecycle now preserves exact Product results through family
withdrawal; Source union support is covered. Ruling: correct the reviewer's
January 11 test expectation to revisions 2 and 4 because the synthetic imported
email explicitly schedules revision 1 on January 12. No production date change.

Snapshot draft rejected for missing endpoint nodes, ignored caps/cursors/filters,
and absent work budgets. Narrow cursor regressions now pass (5 graph tests).
Ruling: provide concrete snapshot correction guidance during review
for Luna to apply, format and test, followed by independent source review. This
continues the user's requested implementation/correction loop; no draft is accepted
on the implementer's smoke-test claims. No implementation work is declared complete
until focused acceptance and integration verification pass.

Ruling: develop the disjoint review-history reader while snapshot integration is
corrected. Its own tests/review gate route integration. Initial draft was rejected
for empty history WHERE syntax, unused VM budget and raw interrupt errors.

Task 3 source review is now clear of confirmed Important defects after adjudication:
the 501st membership is intentionally a plus-one budget signal. It returns an
unavailable complete timeline summary, never capped 500-member totals. A concrete
500/501 regression now covers that behavior.
Root verified 138 focused tests and scoped Ruff/format; subsequent test additions
are being checked, including optional-type test corrections. Graph UI still pending.

Source-index benchmark (temporary synthetic 6,000 revisions/associations): history
Source lookup scanned both tables, approximately 36,000 VM instructions. Adding
covering indexes `(email_message_id,id)` on revisions and
`(email_message_id,order_revision_id)` on associations changed both scans to seeks,
under 100 measured instructions for an absent source. Ruling: add these indexes to
unreleased 003; preserve the original schema-2 database. No extra service required.

Ruling: begin disjoint HTTP integration against the reviewed graph contracts while
remaining graph snapshot regression tests are completed. `/graph` serves the shell
and obtains the protected graph bundle by fetch; it does not embed private graph
payloads in HTML or history. This replaces the plan's unused graph_page(view)
argument with an analysis-day input. Source/UI integration remains separately gated.

Task 3 final source verification: controller ran 148 combined domain/graph/review/
security/migration tests, all passed, and scoped knowledge Pyright 0 errors.
Concrete regressions now verify actual 200-node and 400-edge density, per-root
continuation, endpoint atomicity, concurrent writer snapshot consistency, rollback,
history/current timeline independence, canonical determinism, and optional coverage
SQL interruption with no subsequent SQL. Graph data contracts are approved for UI.
Empty first-run behavior and HTTP/installed-wheel integration remain in tasks 4–6.

Task 4 HTTP integration is in review/correction: shell IDs/real SVG, missing-origin
setup guidance, direct/HTMX rendering, token guard and basic create/propose/accept
flow exist. Strict GET query/snapshot parsing, complete retry/withdraw/security
coverage and final error handling remain. No route smoke report completes Task 4.

Task 5 initial UI draft rejected: it omitted edges, inspector/timeline, filters
ignored entered fields, and HTTP errors were rendered as successful data. Concrete
controller/canvas correction artifacts are being reviewed before Luna integrates
them. SVG layout, rendering and forms still require real browser acceptance.

Actual-data validation completed on the disposable backup only: CLI migration to
schema 3, integrity check, and exact six-table row comparison against read-only
schema-2 original passed. Counts remain 15 Orders/Revisions, 110 Items, 41 Products/
Listings, and 17 Sources. All 41 unassigned Products have complete direct timelines;
overview continuation and canonical repeat match. Zero Families were created.
Private results and scripts remain ignored under data/ticket-21-validation/.

Task 4 source/API corrections: register raw Starlette routes so FastHTML cannot
parse request bodies before the bounded security guard. Strict query/body errors,
original command replay after withdrawal, cross-session guards, empty database,
and direct/HTMX shell now have focused coverage. Controller final integration
verification remains pending the UI stage. UI source corrections have added
canonical relationship lists, safe details, delivery timelines, and responsive
panels. Explicit review/create/proposal controls remain in progress.

Controller repository checks at the UI integration checkpoint: full pytest 459
passed, 1 opt-in Ollama test skipped; full Pyright 0 errors; lock check resolved
65 packages unchanged. Web/Chat subset independently passed 66 tests. Full Ruff
found formatting in planning examples plus four long test SQL strings and the
active UI shell edits; corrections assigned. Secret scan found one synthetic
SessionMiddleware test key, pending a targeted false-positive annotation (no
baseline change). Browser screenshots confirmed initial tiny SVG labels; initial
auto-fit is included in the next UI correction. Review-write placeholders were
rejected again and replaced mechanically from the controller's reviewed workflow
reference, with integration hooks still under verification.

## Final verification and disposition

Controller final full suite: 459 passed, one opt-in Ollama smoke skipped, one
existing Fastcore deprecation warning. Full Pyright: 0 errors. Ruff format: 226
files already formatted; Ruff lint and lock check passed. Secret hook passed after
reviewing its baseline refresh: identical finding hashes/types/files, only ordering,
timestamp and one existing synthetic `.invalid` fixture line number changed. The
new test-only session key has a targeted false-positive annotation. Baseline was
staged for the hook's required baseline review check; no commit or push occurred.

Browser verification uses disposable synthetic state and the reusable scripts in
tests/browser/: graph_explorer.js, graph_reviews.js, graph_navigation.js and
graph_server.py. Read flow, Family 3-Order/2-day counts, visibility independence,
search, keyboard, bounded 60-item relationship continuation, zoom/fit/reset, actual
mouse drag without selection, delayed successful response exclusion, 409/500
recovery, three repeated navigations, Back/Forward and detached-response disposal
passed. 390px light/dark screenshots have no horizontal overflow; all resource
requests were local and no Graph result/DOM was stored in history/localStorage.
Review browser flow passed pending→accepted→withdrawn→pending→rejected (5 events),
0→3→0 Order counts, markup escaping, and lost-response retry without duplicate
creation. It also passed starting with Products but zero Families. Empty database
creation produced an empty Family with an honest zero timeline and coverage note.

Browser-found Important correction: uncached HTMX history restoration replaces
the document body, so `/graph` must return the full shell when both HX-Request and
HX-History-Restore-Request are true. Luna fixed the route, extended its regression,
and the controller reran the previously failing real Back/Forward scenario.

Final installed wheel was built from the corrected source, installed with locked
runtime dependencies in data/ticket-21-validation/wheel-venv, and made read-only.
Outside-checkout state `/private/tmp/ticket21-wheel.Mw4CbJ` reached schema 3 via the
installed CLI. Resource checks found migrations 001/002/003 and four assets;
health, empty Graph view, token, full/history shell and coverage notice passed.
Installed graph.js SHA-256 matches source. `uv pip check` passed. CI now uses
Starlette TestClient with an explicit loopback base URL: FastHTML get_testclient
silently ignores that kwarg for its returned client's base URL. Development origin
validation was preserved, not relaxed to permit `http://testserver`.

Actual copy final recheck: original schema 2, copy schema 3, all six fact tables
identical and integrity OK; 41 complete Product timelines, 41 single-day ranges
and 41 safe Source inspections passed. No actual Family assignment was created.

Final independent Astra/high source review found one Important acceptance gap:
the UI lacked parsed-record/archive/fulfillment/conversion limitations. Luna added
the visible coverage notice and shell regression; scoped re-review is clean.
See ticket-21-final-review.md. No outstanding Critical/Important findings remain.

Ruling: a secondary token review incorrectly required Origin on same-origin GET.
Browsers normally omit that header on same-origin GET; exact Host, supplied-Origin
validation, Sec-Fetch-Site rejection, custom X-Graph-Page header/no CORS, and
session-bound tokens implement the intended guard. POST still requires exact
Origin and token. Do not break legitimate issuance by requiring absent GET Origin.

Ticket 21 is resolved locally, and ticket 22 is also resolved locally after the
Cytoscape redesign and chat remediation. Keep the branch and working tree for
review. No homelab migration, restart, deployment, commit or push. Planning and
correction artifacts are not runtime resources.
