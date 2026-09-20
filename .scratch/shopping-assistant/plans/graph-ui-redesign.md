# Graph UI redesign after actual-data review

Status: resolved
Date: 20 September 2026

## Direction and authorization

The operator rejected the current UI as black squares with unreadable content and
asked for Graphify or comparable researched interaction, then ticket 22. The
operator authorized autonomous work while away and requires Luna/low to perform
all coding; the controller researches, directs, reviews, and verifies. The actual
development database is authorized and already backed up and migrated to schema 3.
No actual Family assignments, raw-email changes, deployment, commits, or pushes
are needed for this UI work.

Completed locally: the controller reviewed the Luna/low implementation and verified
readability, graph interaction, responsive themes, keyboard/list fallback, actual
data and installed assets. See ticket 21's superseding completion record and
ticket 22 for the subsequent full repository checks.

Ruling: replace the native SVG renderer with pinned, locally served Cytoscape.js
core. The observed 1.25px initial labels, unreadable dark tiles, camera defects,
and explicit operator rejection establish a measured usability need. This
supersedes the earlier no-renderer-dependency preference, not the SQLite graph
contracts. Cost: one bundled MIT-licensed browser asset to maintain; no Python,
Node build, database, cloud service, or runtime CDN dependency.

Ruling: retain the existing Stitchyard shell and its light/dark theme tokens.
Adding a second component/CSS framework would introduce unrelated styling and
build changes. Improve the existing graph page directly.

## Research

- [Graphify](https://github.com/Graphify-Labs/graphify): interactive graph with
  colored groups, search, filters, and click-to-inspect. Use these interaction
  ideas; its generated artifact/data pipeline is not the live purchase store.
- [Cytoscape.js](https://js.cytoscape.org/): app graph renderer, layouts, directed
  edges, pan/zoom, events, and explicit styles. Pin
  [3.34.3](https://github.com/cytoscape/cytoscape.js/releases/tag/v3.34.3).
- [Obsidian Graph view](https://obsidian.md/help/plugins/graph): search, colored
  groups, local neighborhoods, and hover focus.
- [Sigma.js](https://www.sigmajs.org/docs/): useful WebGL alternative for much
  larger graphs; unnecessary extra Graphology dependency at the current cap.

## Required experience

1. Put the graph immediately below a compact header/search toolbar. Give the
   canvas the majority of a desktop viewport (roughly 600–720px tall). Keep the
   inspector beside it on wide screens and below it on mobile. Avoid the current
   long wall of filters and forms before users see the graph.
2. Replace black rectangular cards with colored circular/rounded nodes, a visible
   legend by entity type, subtle directed edges, and selected/neighbor emphasis.
   Explicit renderer colors must work in both app themes and refresh on theme
   changes. Labels at the initial/default scale must be readable (at least 12px).
   Full names remain accessible in the list/inspector. Use plain text only.
3. Show a tidy, spaced Product/Family overview when there are no edges. Do not
   invent families or connections. Explain that selecting and expanding a node
   reveals purchase evidence. For connected views, use a useful bounded layout
   (Cytoscape core COSE without ongoing animation, or a clear breadth-first layout)
   and focus the selected neighborhood rather than shrinking everything to dots.
4. Pan, wheel/pinch zoom, Fit all, Focus selected, Reset, and expansion must work.
   Zoom out always zooms out, including after Fit. Preserve camera across ordinary
   data refresh/selection where sensible; layout only on changed topology or an
   explicit re-layout. No perpetual physics or layout on every keystroke.
5. Keep the accessible searchable/list exploration path and evidence links. Allow
   list/canvas selection to inspect details and then explore connections. Keyboard
   users must reach every loaded node through real buttons. Keep canonical edge
   predicates, historical inactive state, server counts, caps, cursors, and partial
   coverage honest; visible graph filtering must not change timeline totals.
6. Move advanced date/type/history filters into a compact disclosure. Put Family
   creation/proposal/review in a clearly labeled secondary section/disclosure;
   preserve all behavior, tokens, idempotency/retry, and first-run guidance.
7. Handle empty, loading, request error, stale snapshot, and missing-renderer
   conditions explicitly. Preserve latest-request guards and dispose renderer,
   observers, listeners, timers/layouts when leaving the page. No private graph
   payload in history/localStorage; no external resource requests.
8. Serve the pinned renderer and license locally, record upstream URL/hash in a
   short vendor note, and ensure the built wheel contains it. Version the changed
   static assets to prevent stale CSS/JS after a code update. Keep route/origin
   protection intact.

## Implementation boundaries

Primary files: web/graph_views.py, web/static/graph.js (replace GraphCanvas; preserve
controller contracts), graph-specific shopping.css, web/layout.py asset inclusion,
static/vendor/ pinned asset/license, focused shell/browser tests and documentation.
Do not alter graph business rules, schema, real data, Chat logic, or unrelated UI.
Current backend suite is 459 passed, one optional model smoke skipped; Pyright clean.

## Verification before moving to ticket 22

- Synthetic 40-Product dataset catches dense-view readability (no private fixtures).
- Real browser screenshots on 1440px desktop and 390px mobile in light/dark themes;
  inspect synthetic screenshots directly, redact actual household labels before
  emitting/viewing actual screenshots. Computed styling alone is insufficient.
- Search, selection, evidence expansion, pan/zoom/fit/focus/reset, list keyboard
  path, resize, date/type filters, timeline counts, continuation, empty state,
  failed fetch/retry, navigation/back/forward, and Family write workflow remain good.
- Read-only actual-data check: 41 Products, 15 Orders, 110 Items; all 41 timelines
  and date ranges matched independent SQL and the six fact tables matched the
  pre-migration backup. Repeat preservation check after visual acceptance.
- Run appropriate tests/lint/type checks/secret scan and wheel asset smoke. Have
  an independent reviewer assess the final UI changes and direct Luna to fix
  concrete findings before accepting them.

## Progress

- Initial native SVG first render measured 1.25px labels on the actual 40-node page.
- Latest CSS colors are valid, but dark tiles have little contrast and stale CSS
  can produce default black SVG fills. The user rejects the design as a whole.
- Read-only actual browser checks passed search, 40+1 pagination, date filters,
  history/visibility-independent totals, and six linked evidence types. These
  establish data behavior, not visual acceptance of the rejected interface.
