# Make the graph show purchase frequency and dated order connections

Parent: ../map.md
Type: task
Status: resolved
Blocked by: 21

## Goal

The operator still finds the graph unhelpful after the renderer redesign. All
circles appear the same size, and clicking a Product does not visibly reveal its
past Orders. Make these two shopping questions apparent directly on the canvas:
which Products recur most often, and when a selected Product was purchased.

Continue the requested execution arrangement: Luna/low implements application and
test code; the controller researches, directs, reviews and verifies. Actual dev
data may be used locally without changing purchase facts. Ticket 22 remains
resolved; this is a follow-up to ticket 21's visualization.

## Direction

- Size Product circles by exact qualifying distinct Order count in the selected
  purchase scope. Count current placed/completed revisions with known delivery
  dates through the analysis date. Repeated lines, wrappers and old revisions do
  not add occurrences. Counts remain independent of graph pagination/visibility.
  Use a stable bounded scale, readable labels and a short size legend.
- Single-click or keyboard activation of a Product reveals direct, supported
  Product-to-Order links. Order nodes emphasize their Singapore scheduled delivery
  dates. All qualifying past Orders are eligible; this is not limited to the
  newest Order and does not require the revision-history toggle.
- Preserve Product context when an Order is selected, with useful order details
  and a link to the existing Order page. Emphasize the local connected graph, give
  the user a clear return to the overview, and retain deeper evidence exploration.
- Keep bounds, continuation, snapshot consistency, current/history distinctions,
  date/type filters, accessible controls, no external resources, and read-only
  graph queries. Reuse SQLite and the locally bundled Cytoscape renderer.

## Reference

[Graphify's HTML renderer](https://github.com/Graphify-Labs/graphify/blob/v8/graphify/exporters/html.py)
uses node size by degree, selection/inspection and connected graph layout. Adapt
the interaction to recorded purchase frequency; do not infer shopping connections
or copy its data pipeline. This follow-up supersedes the earlier same-size circles
and inspect-then-expand behavior.

## Acceptance

- [x] Synthetic Products purchased once versus repeatedly have visibly different
  circle sizes, with counts verified against SQL and repeated lines deduplicated.
- [x] One Product activation reveals multiple dated Order neighbors without a
  second Expand action; Order activation retains the context and evidence links.
- [x] Scope changes, history mode, pagination and node-type visibility remain
  truthful; no graph-derived metric depends on only the displayed nodes.
- [x] The controller reviews actual browser screenshots and interaction, including
  desktop/mobile and the authorized actual database, with private labels kept local.
- [x] Proportional regressions, repository checks and wheel verification pass;
  original purchase facts remain unchanged. No deployment is claimed.

## Comments

- Claimed after the operator's follow-up feedback on 21 September 2026 (Singapore).
  The existing renderer hard-codes 52-pixel circles. Product selection currently
  changes the inspector only; visible relationships require a separate expansion
  through technical Listing/Item/Revision records. Those defaults do not satisfy
  the requested purchase-oriented interaction.

- Controller review found and returned incomplete drafts: counts initially missed
  Products discovered through expansion, missing timeline summaries could become
  false zeroes, and the first focus filter accidentally hid the connecting edges.
  Browser checks now require visible edges as well as node data. The first mobile
  layout also overlapped Product and Order labels; responsive layout and the
  actual maximum-frequency case remain part of acceptance before resolution.

- An independent read-only oracle over the actual database matched 41 Product
  counts and 108 qualifying Product/Order pairs, including their Revision/Item
  support. The 12 original purchase/source tables match the verified backup.
  These data checks do not by themselves establish visual acceptance.

- Further controller review required stable Product context when selecting an
  Order, valid calendar dates in the pagination fixture, meaningful positive
  provenance tests before negative cases, and overview spacing based on complete
  node/label bounds. The actual maximum-frequency case exposes 12 dated Orders.
  Desktop and 390-pixel mobile checks verify distinct sizes, visible connections,
  readable non-overlapping labels, stable positions and Order evidence links.
  A final screenshot also exposed mobile edges crossing the Product label. Luna
  moved it above the circle with sufficient padding. Controller review then
  caught that a redraw could reset its placement; the corrected implementation
  reapplies placement on each focus render. Regression checks re-fetch live
  nodes after redraw and verify retained positions, label bounds and visibility.

## Answer

Implemented locally by Luna/low, with controller review, corrections and direct
verification. Product circles now use exact qualifying distinct Order counts in
the selected purchase period. A Product activation immediately displays its dated
Order neighborhood. Selecting an Order keeps those connections and opens details
with an Order evidence link. **All products** returns to the overview. Singapore
scheduled delivery dates retain the accepted Purchase Date meaning. Earlier
logical Orders are included without enabling earlier record versions.

The canvas uses readable colored circles, count labels, a size legend, chronological
desktop columns and a vertically scrollable mobile neighborhood. Detailed
Revision/Item evidence remains available. Derived `PURCHASED_IN` links require
support from current qualifying facts; no new stored purchase facts, infrastructure
or migration were introduced. Schema remains 3.

Verification completed:

- Independent actual-data checks matched all 41 Product counts and 108 supported
  Product/Order links. All 12 original purchase/source tables match the verified
  pre-migration backup. The largest actual neighborhood has 12 Orders.
- Controller browser checks passed on actual desktop/mobile views, including
  readable initial overview, distinct circle sizes, dated neighbors, visible
  connections, bounds and non-overlapping labels. Synthetic six- and twelve-Order
  checks verify deduplication, accessible activation, retained live Order nodes and
  positions, Product label placement, evidence links and overview return.
- Existing search/filter, current/history, keyboard, pagination, recovery,
  navigation and Family review browser checks passed. Server regressions include
  hidden/expanded Product counts, unavailable timeline summaries, valid dated
  pagination, consistent count scope and complete edge support.
- Repository checks passed: Ruff formatting/lint, Pyright, **550 tests passed**,
  diff checks and secret scan. Five opt-in live-Qwen tests were skipped in this
  graph follow-up; ticket 22 records their earlier separate execution.
- The final wheel includes migrations 001–003 and all six required static assets,
  byte-matched to the final checkout. Migration in an isolated environment and
  installed-package Graph/health/protected/static route smoke checks passed.

README, MVP plan, deployment notes and the accepted graph specification reflect
this behavior. Changes remain in the local working tree, and the actual development
app is running on loopback. No commit, push or homelab deployment is claimed.
Ticket 22 remains resolved locally; ticket 18 retains host verification.
