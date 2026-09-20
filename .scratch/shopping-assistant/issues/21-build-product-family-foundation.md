# Build Product Family foundation, graph explorer, and purchase timelines

Parent: ../map.md
Type: task
Status: resolved
Assignee: Codex with Luna/low implementers
Blocked by: 20
Implementation plan: ../plans/product-family-graph-explorer.md

## Goal

Make the accepted knowledge graph model concrete: persist Product Families and
reviewable membership decisions, visualize connected purchase records in the app,
and inspect a Family's delivery-based purchase timeline. Read the
[accepted model specification](../specs/shopping-knowledge-graph-model.md) and
[ticket 20](20-define-shopping-knowledge-graph-model.md) before implementation.

Implemented and verified locally on `codex/ticket-21-graph`. The
[implementation plan](../plans/product-family-graph-explorer.md),
[execution ledger](../plans/ticket-21-execution.md), and
[final source review](../plans/ticket-21-final-review.md) record the work.
The operator database remains unchanged; no homelab deployment occurred.
The operator explicitly requested a UI to visualize the knowledge graph. An
interactive Graph page in the existing FastHTML/Stitchyard app is now a required
deliverable, including family review and purchase timelines. A CLI/export alone
does not complete this ticket; no separate graph service is required.

## Boundaries

- Preserve exact Products, Listings, Items, revision history, source evidence,
  and the existing Chat monthly-listing contract.
- Use SQLite for family definitions, membership suggestions, review decisions,
  and their history. Graph exports and timelines remain rebuildable.
- Add the next numbered migration; `003_product_families.sql` is available at
  preparation time, but verify the sequence before implementing. Never edit an
  applied migration or migrate the operator's actual database during development.
- Only reviewed, accepted memberships affect frequency. Concrete household
  assignments need their own review; accepting the model does not accept them.
- Current `placed`/`completed` past/current delivery dates qualify. Count unique
  family/order occurrences and distinct Singapore purchase days. Retain quantity
  detail per exact Product and all contributing evidence.
- Use deterministic typed node/edge records with stable dataset-scoped IDs.
  Retain source/membership snapshot metadata and explicit analytic coverage.
- Graph browsing is read-only. Membership review is a separate explicit action
  with the existing web write protections; selecting or dragging nodes never
  changes membership or purchase facts. Serve graph assets and data locally.

## Required Graph UI

- Add **Graph** to the existing sidebar at `/graph`, using the current shell,
  light/dark themes, and responsive components.
- Start with a readable Family/Product overview. Provide family/product search,
  node-type filters, and a Singapore Purchase Date range for purchase activity.
  Show unassigned Products when no reviewed families exist; never invent families
  to populate the screen. Filtering activity does not delete membership facts.
- Provide pan, zoom, fit/reset, node selection, and bounded expansion/collapse of
  connections. Identify node types through labels/icons as well as color, and
  explain relationship meanings on selection/focus. Show counts/continuation when
  only part of the graph is loaded; do not imply a partial graph is complete.
- A selected-node panel shows its business details and relevant evidence. Family
  selection shows its definition, accepted members, distinct order/day counts,
  delivery-date timeline/gaps, and quantity breakdown by Product. Product/Order
  nodes link to the existing history/detail pages. Show provisional Product
  identity and membership origin/review state; distinguish recorded purchase
  facts, reviewed grouping assertions, and calculated counts.
- Allow progressive inspection of Listing, Item, Revision, Retailer, and Source
  connections without displaying every technical node by default. Source details
  use safe evidence metadata/references; no raw email rendering or archive links.
- Include a distinct family membership review area for proposed assignments,
  rationale, and explicit accept/reject/withdraw actions. Unreviewed suggestions
  must not look like active graph facts. Successful review refreshes graph and
  timeline from the same resulting membership state.
- Make first-run setup usable: **Create Family** records a name and inclusion/
  exclusion definition; **Propose membership** selects existing Products and records
  rationale/origin in a pending queue. Prepared operator/agent suggestions use
  this same review path. Creating a proposal does not accept it, and no automatic
  classifier is needed to populate the first review queue.
- Keep graph/timeline period, selected entity, history/current mode, and partial
  coverage visible and consistent. A date filter scopes purchase activity and
  the visible timeline; retain factual entities and display zero matching activity
  honestly. Node-type filters change the drawn graph, not the timeline's eligible
  purchase population. Excluded statuses and upcoming/unknown dates remain distinguishable.
- Support touch/mobile sizing and a keyboard-accessible relationship list with
  the same selection/details, so graph dragging is not the sole way to explore.
  Handle loading, empty, missing-node, and failed-expansion states while preserving
  the last valid view. Browser back/forward and app navigation must work reliably.

## Implementation sequence

The [implementation plan](../plans/product-family-graph-explorer.md) supplies exact
file ownership, operation/data contracts, tests, and verification steps:

1. Add Family definitions, stable Product/Family pairs, append-only proposal/review
   events, idempotent command receipts, and dataset/snapshot tracking in migration 003.
2. Build delivery-based Product/Family timelines with complete-scope counts,
   per-Product quantities, evidence, and explicit eligibility/coverage limits.
3. Build consistent bounded graph reads and deterministic typed projection;
   reject stale continuations rather than mixing source/membership snapshots.
4. Add protected Graph routes and first-run create/propose/review controls.
5. Add a local native-SVG explorer with an inline inspector, accessible relationship
   list, pan/zoom/expansion, and reliable HTMX/navigation lifecycle. No renderer
   dependency or graph service is required.
6. Verify synthetic edge cases, browser flows, an isolated actual-data copy,
   repository checks, and installed-wheel migrations/assets; update implementation docs.

Definitions are create-only in this first version. Membership correction uses
withdrawal and a new reviewed proposal; earlier assertions remain intact. Graph
origin/session protections are explicit and use the existing configured app origin.
The plan defines request and work limits so a capped canvas never becomes a false
complete-history count. Forecast methods are not a prerequisite.

After this ticket, implement the accepted Chat repairs through
[ticket 22](22-implement-chat-remediation.md), which executes ticket 19's decisions.
That ordering is project priority, not a claim that Chat lifecycle fixes technically
depend on family data. No implementation, commit, migration, or deployment is
performed by this planning update.

## Implementation boundaries

- `src/shopping/storage/migrations/`: family and membership/history persistence.
- `src/shopping/purchases/`: family operations and timeline queries; reuse
  short-lived connections and current-order query patterns. Keep ingestion parsing
  and exact-product normalization unchanged.
- A small application-owned projection module: typed entities/edges from a
  consistent snapshot, validation, deterministic export, and evidence references.
- `src/shopping/web/graph.py` plus `factory.py` and `layout.py`: Graph routes,
  sidebar entry, details/timeline rendering, and explicit protected membership
  review actions in the existing shell. Reuse existing product/order destinations.
  Current origin/token enforcement is Chat-specific; graph review endpoints must
  enforce their own protections rather than assume registration inherits them.
- `src/shopping/web/static/graph.js` and existing styles: graph interaction and
  responsive panels. Plan page-specific asset initialization/cleanup for direct
  loads, HTMX swaps/history restoration, and navigation away; avoid duplicate
  listeners, stale selection responses, and leaked layout work.
- Use native SVG and existing JavaScript as selected in the implementation plan;
  the renderer must not become the source of business relationships.
  Enforce node/edge/expansion limits on the server with no dangling displayed edges.
  Prefer an inline inspector; existing global drawer history/inert behavior is
  order-specific and must not trap graph focus or break Back/Forward.
- Synthetic migration, membership, history, projection, and web tests under `tests/`,
  plus browser scenarios for the graph interactions and review flow.
  Actual data is for explicit local validation, not committed fixtures.

## Acceptance

- [x] Family definitions and membership review history survive restart and backup;
  duplicate suggestions/reviews do not create duplicate active membership edges.
- [x] Pending/rejected suggestions do not affect frequency; acceptance/withdrawal
  rebuilds the current timeline while retaining prior decision history.
- [x] Multiple family members/repeated lines in one Order produce one family
  occurrence; same-day Orders remain distinct but contribute one interval date.
- [x] Current revisions, cancellation/refund/unknown status, future dates, missing
  dates, Singapore boundaries, and membership changes follow the specification.
- [x] Unassigned/provisional Products and known data-coverage gaps remain visible;
  no unsupported package conversion or family quantity total is invented.
- [x] The graph includes Order, Revision, Item, Listing, Product, Family, Retailer,
  and Source relationships with inspectable evidence and reproducible output.
- [x] The Graph page opens directly and through sidebar navigation; search, filters,
  pan/zoom/reset, selection, and bounded expand/collapse work on actual graph records.
- [x] Selecting a Family shows the matching members, order/day counts, delivery
  timeline, Product quantities, and working order/product evidence destinations.
  Filtering or partial graph loading cannot silently change an unscoped total.
- [x] The no-family state shows unassigned Products and a review entry point; an
  empty database, missing selection, failed request, and truncated neighborhood
  have truthful recoverable states. Malicious stored names remain escaped text.
- [x] An operator can review a concrete proposed membership in the UI; acceptance
  updates the active graph/timeline, rejection does not add membership, and
  withdrawal removes it from the current view while preserving review history.
- [x] Starting without any Families or proposals, an operator can create a Family,
  propose existing Products, and explicitly accept the proposal to produce the
  first active family graph/timeline. Repeated actions do not duplicate effective
  memberships; a stale conflicting review cannot silently overwrite newer decisions.
- [x] Browser checks cover mobile/desktop, keyboard/list exploration, light/dark
  themes, repeated navigation/history restore, stale responses, and request errors.
  Record browser evidence separately from unit checks; no source email content
  or external graph asset/data requests are exposed by the page.
- [x] Update existing navigation coverage that currently expects Graph to be absent.
  A large synthetic neighborhood respects server limits and contains no dangling
  edges; rapidly changing selection or leaving the page cannot apply stale details.
- [x] Proportional focused tests, repository checks, secret scanning, and isolated
  built-wheel migration verification pass. README/MVP documentation distinguishes
  implemented features from pending work.

## Separate work

Forecast algorithms/thresholds, prediction accuracy evaluation, alerts, advanced
layout customization, automatic classification machinery, and Chat repairs/tools are not required
to complete this foundation. Neither are the two failed email imports or package
metadata corrections; expose their limitations without silently changing facts.

## Comments

- Follow-up operator review rejected the visual UI as unreadable black squares.
  Reopened for the [researched UI redesign](../plans/graph-ui-redesign.md), using
  Luna/low for coding and controller review/browser acceptance. The operator
  explicitly authorized testing and migrating the actual development database,
  then implementing ticket 22, while away. A verified backup precedes the direct
  migration; purchase facts remain unchanged. Earlier completion below records
  the previous checkpoint and does not certify the revised UI.

- Prepared after the operator accepted ticket 20's family meaning, reviewed
  assignment, delivery-date basis, and purchase eligibility/counting decisions.
  At that point detailed implementation planning and execution had not started.
- The operator subsequently asked to “add a ui to visualize the knowledge graph.”
  Added the interactive Graph page and integrated membership review/timeline as
  required acceptance, replacing the earlier CLI-or-web interface choice. This
  updates implementation scope; no UI code or runtime dependency has been added.
- Implementation-readiness review found no unresolved product requirement. Added
  explicit first-run Family creation and membership proposal actions so review
  works without an automatic classifier. Schema/API/renderer/lifecycle choices
  were assigned to the implementation plan, now linked above. Known incomplete imports and package
  metadata are visible data limitations, not prerequisites for building this feature.
- The operator requested the implementation ticket and asked whether ticket 19
  would be worked on. Prepared the linked six-task plan and marked this ticket
  ready for implementation, still open/unclaimed. Added ticket 22 as the next
  implementation priority for ticket 19's accepted repairs. No code was changed.
- Plan review checked model/UI coverage, interface consistency, stale-snapshot
  handling, and limits. Clarified that optional lifetime coverage may be unavailable
  while the selected period's counts remain complete. Local document links and
  whitespace checks pass; implementation tests have not been run.
- The operator requested implementation by a Luna/low subagent with controller
  review and correction loops. Claimed on branch `codex/ticket-21-graph`; execution
  is tracked in [the implementation ledger](../plans/ticket-21-execution.md).


## Answer

Resolved on 20 September 2026. Luna/low implementers delivered migration 003,
append-only Family membership proposals/reviews, consistent bounded graph reads,
delivery-based Product/Family timelines, protected Graph endpoints, and the local
native-SVG explorer. The controller inspected the implementation and returned
concrete corrections, then independently verified the results. Final source review
found one missing coverage notice; it was fixed and re-reviewed with no outstanding
Critical/Important finding.

Verified results:

- Full Python suite: 459 passed; one opt-in Ollama smoke test skipped. Ruff format,
  Ruff lint, Pyright, lockfile and secret checks passed. No new runtime dependency.
- Browser checks: search, visibility-independent timelines, keyboard selection,
  zoom/fit/reset and mouse pan, bounded continuation, delayed-success races,
  409/500 recovery, repeated HTMX navigation, Back/Forward, and disposal. Checked
  390px mobile and desktop layouts in light/dark themes, no external resources or
  Graph payload persisted in browser history.
- Explicit create/propose/accept/reject/withdraw and re-propose workflow passed,
  including first-run Products without Families and an empty database. Lost-response
  retry reused its command and created no duplicate. Stored markup remained text.
- Final installed wheel in a read-only isolated environment outside the checkout
  includes migrations 001–003 and all four assets. CLI migration reached schema 3;
  health, Graph shell/view/token/assets and history restoration passed.
- A read-only SQLite backup of actual data was migrated separately. All six fact
  tables are unchanged: 15 Orders/Revisions, 110 Items, 41 Products/Listings, and
  17 Sources. All 41 Product timelines, single-day ranges, safe Source views and
  canonical repeat checks passed; no actual Families were created. Original schema
  remains 2. Private artifacts stay ignored under data/.

The implementation is an uncommitted working-tree change on the feature branch.
No deployment or original-database migration is part of this completion. Ticket 22
is now the next unblocked implementation priority for ticket 19's accepted repairs;
forecasts, automatic classification, and new Chat tools remain outside ticket 21.

### Completion comment

Controller review rejected incomplete early drafts rather than accepting their
reports. Test-first ordering was not fully followed in those drafts; final checks
and correction regressions are verified without inventing earlier red-run evidence.
See the execution ledger for scope rulings and detailed verification.


### Superseding UI and actual-database verification — 20 September 2026

The operator rejected the original visualization and authorized a Graphify-inspired
redesign followed by ticket 22, retaining Luna/low coding and controller review.
The [redesign brief](../plans/graph-ui-redesign.md) replaces the historical native-SVG
choice with locally bundled Cytoscape 3.34.3 (MIT), colored circles, bounded readable
labels, human relationship labels, pan/zoom/focus, an inspector and compact controls.
No external browser resource or new Python dependency is required. The wheel
contains the renderer and its license.

Root verification: 189 focused tests passed; actual overview has 40 initially loaded
nodes, 14-pixel labels, zero label overlaps and zero external resources. Actual
read-only browser checks passed for search, timelines, date filters, product/order
links and source inspection. Synthetic checks passed for keyboard Enter selection,
renderer-unavailable warning with accessible list, empty state, dense desktop/mobile
readability, navigation and review flows. Full repository checks will run again with
ticket 22. The actual dev DB is schema 3, directly migrated with explicit operator
authorization; its verified backup remains schema 2. All six purchase fact tables
match the backup, all 41 Product timelines match independent SQL, and no actual
Family memberships were created. This supersedes earlier original-DB/schema-2
statements above. No homelab deployment is claimed.

### Final integrated checks — 21 September 2026 (Singapore)

The repository and installed-wheel checks referenced above have now passed with
ticket 22: 539 tests plus five separately enabled live-Qwen tests, Ruff, Pyright,
lockfile and secret checks. Actual Graph browser checks and independent Product
timeline comparisons passed again. The installed wheel contains the renderer and
license and runs schema-3 migration and the Graph page outside the checkout.
[Ticket 22](22-implement-chat-remediation.md#answer) is also resolved locally and
records the full final verification. No homelab deployment occurred.

### Purchase-oriented graph follow-up — ticket 23

The operator's subsequent feedback about uniform node sizes and weak purchase
connections is implemented and verified in [ticket 23](23-make-graph-show-purchase-frequency-and-orders.md#answer).
Product size now reflects qualifying distinct Orders; Product activation exposes
dated Orders directly, and Order activation keeps that neighborhood visible.
Actual-data, desktop/mobile, repository and final-wheel checks are recorded there.
This supersedes the earlier same-size and inspect-then-expand interaction. Schema
remains 3, original purchase/source facts are unchanged and deployment is pending.
