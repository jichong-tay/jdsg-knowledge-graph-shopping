# Implement the accepted Chat reliability and monthly-answer repairs

Parent: ../map.md
Type: task
Status: resolved
Blocked by: 19, 21
Implementation plan: ../plans/chat-reliability-and-answer-quality.md

## Goal

Execute [ticket 19's accepted decisions](19-define-chat-remediation-scope-and-acceptance.md):
keep Chat usable after Stop or malformed responses, preserve Conversation switching,
handle ordinary replies and factual answers correctly, and answer the monthly-item
question with exact recorded rows and useful evidence.

Ticket 19 is resolved because its scope/acceptance decisions were accepted. This
task records their completed local implementation and verification, performed after
[ticket 21's graph foundation](21-build-product-family-foundation.md).
The dependency on 21 expresses project priority; lifecycle repairs do not technically
require graph data. Forecasting and additional graph tools do not take priority
over these repairs. The completion evidence below supersedes the original queued state.

## Read first

- [Chat investigation handoff](../research/chat-investigation-handoff.md): recorded
  symptoms, probes, partial patch, and evidence limits.
- [Accepted remediation decisions](19-define-chat-remediation-scope-and-acceptance.md):
  authoritative response, retrieval, and acceptance scope.
- [Chat reliability and useful purchase answers — Implementation Plan](../plans/chat-reliability-and-answer-quality.md):
  eight implementation tasks, exact file boundaries, regression cases, and checks.

## Execution order

1. Reproduce the synthetic baseline and preserve the valid numeric tool-call ID
   correction from checkpoint `b5e6018`; assess the remaining partial patch.
2. **R1/R2:** Fix Stop versus returning-tool persistence and marker-only completion.
   Save consistent terminal text/Evidence or an explicit failure; a later valid
   send must work without restarting the service.
3. **R3:** A failed switch to stale Conversation B preserves A in both browser
   selection and server subscription.
4. **R4/R6:** Support ordinary nonfactual replies while requiring fresh evidence
   for purchase claims. Preserve requested fields and empty/partial meanings;
   an unrelated record dump is not successful fallback. Run the planned synthetic
   protocol compatibility probe against the installed model before relying on it.
5. **R5:** Add frozen Singapore calendar context, the fifth bounded
   `list_purchase_items` tool, deterministic monthly-row rendering, and continuation.
6. Run the focused factual/recovery suite, browser/real-model checks, repository
   checks and installed-wheel smoke test. Record operator acceptance separately
   from local test results and keep host verification under ticket 18.

## Boundaries

- Keep the existing Python/Ollama/SQLite design, selected model, and valid earlier
  implementation. No RAG, BM25, vector database, graph tool, or model replacement.
- Preserve 4 model requests, 8 tool proposals, 180 seconds work plus 5 cleanup,
  6,912 input/768 generated-token limits, one active response, and saved-before-display.
- `list_purchase_items(month="YYYY-MM", limit=10, cursor=...)` returns at most
  20 whole rows within 4,096 UTF-8 bytes. Continuation preserves month and limit.
- Purchase Date is `delivery_at` in `Asia/Singapore`; unknown dates stay unknown.
  Read current revisions including `placed`. Retain repeated Item lines; do not
  replace this listing with ticket 21's Family/order/day aggregation.
- Keep factual evidence, origin/session protection, cancellation, reconnect, and
  short-lived database connections. No unrelated schema or deployment changes.
- Use synthetic records for automated/model probes. Any authorized private check
  stays local and does not put household facts into fixtures or documentation.

## Acceptance

- [x] Stop/tool-return races and empty marker completions settle safely; a later
  valid send succeeds without a restart and genuinely unsettled cleanup stays guarded.
- [x] A failed Conversation switch leaves the previous selection/subscription usable.
- [x] Ordinary greetings/help can complete without purchase citations; factual or
  mixed purchase requests still require valid evidence from fresh reads.
- [x] Empty and partial results remain truthful, requested fields are preserved,
  and unsupported requests do not masquerade as successful record dumps.
- [x] “What are the items I bought last month” returns the correct current recorded
  lines, delivery dates, quantities, evidence links, and honest pagination;
  January rollover, unknown dates, repeated lines, and continuation are covered.
- [x] Existing runtime/tool bounds and the numeric call-ID correction retain coverage.
- [x] Synthetic regressions, browser/real-model checks, repository checks, and wheel
  verification are recorded with their limits. No local pass is called a completed
  homelab deployment or a resolution of ticket 18.

## Comments

- Created on 20 September 2026 when the operator asked for the graph implementation
  ticket and whether ticket 19 would still be worked on. The accepted repair work
  remains in scope and is explicitly next after ticket 21. Status is open/queued;
  no repair or test execution is claimed by this planning update.

- Claimed on 20 September 2026 after the requested UI redesign passed review and
  actual-data checks. The operator explicitly authorized implementation while away,
  with Luna/low coding and controller review. This supersedes the preparation-only
  wording above. Baseline failures reproduced; see the
  [execution directions](../plans/ticket-22-execution.md).

- Completed locally on 21 September 2026 (Singapore). All application and test
  coding was delegated to Luna/low; the controller inspected changes, returned
  concrete corrections and independently verified the integrated outcome.

## Answer

All six repairs are implemented. Stop uses only durable text/Evidence; marker-only
responses fail within their own attempt; stale switching preserves the previous
selection/subscription. Initial authentication also loads the saved library when
a restored Conversation has disappeared. Ordinary modes use fixed application
wording, and fresh recorded answers preserve available requested fields and
explicit empty/partial meanings. Unsupported or uncertain lookup requests remain
incomplete rather than being certified by an unrelated record dump.

The fifth read tool lists current individual purchase lines by Singapore delivery
month, default 10/max 20 within a 4096-byte envelope. Frozen calendar context,
deterministic formatting, repeated-line preservation and signed cursor scope are
implemented. Explicit next-page requests use saved complete tool groups, retain
month/limit across reconnect and calendar rollover, and perform one fresh read
without another model request. Expired cursors ask to restart the original month.

Verified evidence:

- Repository checks: Ruff format/lint, Pyright, 539 tests passed; five opt-in
  real-model tests are skipped in the ordinary suite. Lockfile/sync, secret hook
  and diff whitespace checks passed. One dependency deprecation warning remains.
- Opt-in installed Qwen suite: five tests passed, covering recorded order total,
  greeting, thanks, help, exact previous-month items and deterministic continuation
  from the real-model first page. Explicit mode guidance and temperature 0 address
  observed sampling inconsistency without changing the model or runtime budgets.
- Deterministic regressions cover the actual unsaved-tool Stop race through
  runtime/WebSocket/storage, marker-only recovery, stale switching, empty history,
  requested fees/prices, month boundaries, cursor expiry, limits and reconnect.
- Browser verification covers stale-B selection with A preserved, initial stale
  restore with a populated library, new sends and rename updates. The authorized
  actual-data browser query returned all 15 monthly rows in pages of 6, 6 and 3,
  including continuation after reload. Names, quantities, dates, statuses, period,
  cursor scope and evidence matched independent SQLite reads; the largest envelope
  in that flow was 3686 bytes. A saved dev Conversation remains available to inspect.
- All 12 original non-Conversation purchase/source tables match the schema-2
  backup. Actual schema remains 3, with no new family assignments. The earlier
  all-month retrieval oracle matched 110 current rows over nine months and 20 pages.
- The final wheel was installed outside the checkout in a read-only environment:
  migrations 001–003, six required browser assets including Cytoscape/license,
  schema-3 migration, protected Chat bootstrap, Graph and empty monthly read passed.

The graph redesign and this implementation are uncommitted working-tree changes.
The local application runs against the authorized dev database. No homelab
deployment, commit or push occurred. Ticket 18 remains open for host verification;
predictions, RAG/BM25 and further graph tools remain outside this ticket. These
checks establish the recorded cases, not perfect natural-language understanding.
