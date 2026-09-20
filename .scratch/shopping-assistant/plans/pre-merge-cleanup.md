# Pre-merge file cleanup decision

Parent: ../map.md
Scope: local `codex/ticket-21-graph` work for tickets 21–23, before merging into
`main`. Cleanup applied; controller verification is complete. Local integration is
recorded in Git history; no push or deployment is claimed.

## Decision

Keep the implementation and regression suite intact. Reduce the 39 new planning
files to six durable records by removing five generated diff/patch artifacts and
consolidating 28 interim documents before removing their originals. This removes
approximately 677 KiB of duplicate working material before consolidation adds a
small amount to the retained records. This cleanup decision file is additional to
that inventory.

Do not change application behavior or refactor modules as part of this cleanup.

## Keep

- All source modules and tests for Graph, Product Families and Chat remediation.
  No unused source or test file was established by this audit.
- Migration `003_product_families.sql`; it is applied to the authorized dev DB and
  must not be deleted or rewritten.
- The Cytoscape bundle, license and vendor README. The browser serves the bundle
  locally, and wheel/CI checks require these assets.
- `.gitignore`'s `/knowledge/` correction. The former unanchored rule also hid the
  new `src/shopping/knowledge/` and `tests/knowledge/` directories.
- The existing staged `.secrets.baseline` update. Its changes are ordering, line
  location and generation time; detector findings and hashes are unchanged.
- Tickets, map, accepted specification, research, README, domain documentation,
  MVP plan, deployment notes and CI checks.
- Previously tracked plans: `chat-mvp.md`,
  `chat-reliability-and-answer-quality.md`, and `source-layout.md`.
- These six new planning records:
  - `product-family-graph-explorer.md`
  - `graph-ui-redesign.md`
  - `ticket-21-execution.md`
  - `ticket-21-final-review.md`
  - `ticket-22-execution.md`
  - `ticket-22-task-4-marker-probe.md`

The marker probe contains measured model compatibility evidence; preserve it even
though its filename resembles an interim task report. Retain the independent final
review while marking its earlier renderer/line references as historical.

## Delete generated transport artifacts

These five files contain source snapshots or correction patches that have already
been applied and reviewed. Their rationale belongs in the execution/review records,
and their code is represented by the final source and tests. They total 504,968
bytes (about 493 KiB).

- `ticket-21-final-review.diff`
- `ticket-21-knowledge-review.diff`
- `ticket-21-relationships-correction.patch`
- `ticket-21-task-1-source-fixes.patch`
- `ticket-21-task-1-source-review.patch`

## Consolidate, then remove these interim documents

Preserve any unique accepted decision, confirmed review correction or measured
result in the appropriate execution ledger before deleting its original. Do not
copy obsolete instructions or incomplete agent completion claims into current
status. Accepted requirements already live in the specification and primary plans.

- `graph-ui-redesign-report.md`
- `graph-ui-shell-report.md`
- `ticket-21-canvas-reference-report.md`
- `ticket-21-canvas-reference.md`
- `ticket-21-final-validation-notes.md`
- `ticket-21-js-controller-reference.md`
- `ticket-21-knowledge-review.md`
- `ticket-21-relationships-reference.md`
- `ticket-21-reviews-brief.md`
- `ticket-21-reviews-report.md`
- `ticket-21-routes-brief.md`
- `ticket-21-security-report.md`
- `ticket-21-snapshot-brief.md`
- `ticket-21-snapshot-reference.md`
- `ticket-21-snapshot-report.md`
- `ticket-21-task-1-brief.md`
- `ticket-21-task-1-report.md`
- `ticket-21-task-2-brief.md`
- `ticket-21-task-2-report.md`
- `ticket-21-task-3-brief.md`
- `ticket-21-task-4-brief.md`
- `ticket-21-task-5-brief.md`
- `ticket-21-task-6-brief.md`
- `ticket-21-ui-core-brief.md`
- `ticket-21-ui-core-report.md`
- `ticket-21-ui-integration-notes.md`
- `ticket-21-ui-workflow-correction.md`
- `ticket-22-continuation-brief.md`

Examples requiring care:

- The knowledge review explains why a 501-member Family has unavailable complete
  analytics rather than misleading totals from 500 displayed members. Preserve the
  ruling and point to its regression coverage.
- Snapshot/relationship notes explain the single-transaction read and the rule
  against further SQL after optional coverage exhaustion. Preserve those contracts,
  not complete duplicate implementations.
- The Chat continuation brief describes completed R5 work. Preserve the original
  month/limit/cursor and Stop/persistence semantics; it is not pending work.
- Several reports still say full tests or browser checks are pending, or list
  intermediate Pyright failures. The ticket completion answers supersede them.

## Documentation cleanup needed

- Update `docs/MVP_PLAN.md` where it still says ticket 22 execution is queued.
- Update README's opening current-focus statement to reflect the implemented
  model/Graph rather than the earlier modeling investigation.
- Add a clear historical/current-status distinction at the top of the ticket 21
  execution ledger: its native SVG renderer and claimed status were superseded by
  Cytoscape and the resolved tickets 21–23.
- Rewrite references to removed correction files, including the relationship and
  snapshot reference names in the ticket 21 execution ledger. Check all remaining
  links after consolidation.
- Retain the three tracked `research/chat-review-repros/` scripts as historical
  investigation evidence for now. The handoff links to them; add a historical-use
  note and point readers to the permanent Stop-race, marker-only response and
  Conversation-switching tests. They are not release tests or pending fixes.

## Leave local state alone

The actual database, raw emails, backups, screenshots, browser helpers, generated
state, `.env`, virtual environments and build/cache directories are already ignored.
They should not enter the merge. Do not delete `data/` or its helpers during this
cleanup: the dev server uses the actual database and a helper there. No newly
tracked private database or raw-email file was found.

## Applied inventory and results — 21 September 2026

Consolidated accepted evidence into the ticket 21 and ticket 22 execution
ledgers, including the 501-member unavailable-summary rule, the
single-transaction snapshot/no-SQL-after-optional-coverage contract, Cytoscape
renderer/browser disposition, and monthly continuation plus Stop/durable-evidence
contracts. Updated README/MVP status, marked the historical SVG ledger, rewrote
removed-file references, and added the chat probe historical-use note.

Deleted exactly the 28 interim Markdown records listed above and the five listed
diff/patch transport artifacts. Retained the six durable plans, tracked research
scripts, tickets/specifications/research, independent final review, and all
source, tests, migrations, static assets, and private state. Cleanup applied;
controller verification complete; local integration is recorded in Git history.

## Completion checks after applying cleanup

Verify remaining document references, inspect the staged file inventory, run the
secret scan and diff checks, then run repository validation before the already
requested merge. Keep source changes out of this cleanup unless a specific defect
is independently established.

Root validation completed: 550 tests passed; Ruff and Pyright passed; the exact
33 cleanup removals and protected source/test/config hashes were checked; and no
new broken document links were found. Final installed-wheel verification passed:
fresh isolated schema 3 migration, all three migration resources, six byte-matched
assets, and protected Graph/Chat/health/token/static routes.
