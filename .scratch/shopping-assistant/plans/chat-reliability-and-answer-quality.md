# Chat reliability and useful purchase answers — Implementation Plan

**Implementation update — 21 September 2026 (Singapore):** The operator subsequently
authorized execution. Ticket 22 records the completed local repairs and verification.
The unchecked task lists below preserve the original planning record rather than
serve as current status. See the ticket's final acceptance and the
[execution ledger](ticket-22-execution.md), including measured model compatibility
adjustments, actual-data checks and remaining host-verification limits.

**Queued:** [Ticket 22](../issues/22-implement-chat-remediation.md) executes this
accepted plan immediately after
[ticket 21's graph foundation](../issues/21-build-product-family-foundation.md).
[Ticket 19](../issues/19-define-chat-remediation-scope-and-acceptance.md) is the
resolved decision record, not evidence that its defects were fixed. This ordering
is project priority; the lifecycle repairs do not technically depend on graph data.

> **For agentic workers:** Use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` when implementation is requested. The operator has
> accepted the remediation scope and acceptance bar, not execution. No fixes are
> authorized by this document. Preserve the existing partial patch, checkpointed
> in `b5e6018`, while assessing its parts. Retain Luna/low for later implementation.

**Goal:** Keep Chat usable after Stop or malformed responses, preserve valid
Conversation selection/subscriptions, make ordinary conversation complete normally,
and answer “what are the items i bought last month” with the correct recorded items, dates, quantities,
purchase links, and honest pagination.

**Architecture:** Keep the existing Python/Ollama loop, SQLite, saved Conversations,
and FastHTML Chat. Add one focused, bounded month-item read to avoid fetching every
order separately. Resolve calendar context in the application and keep factual
retrieval, response validation, and user-facing formatting separate.

**Tech Stack:** Python 3.14, uv 0.12.3, SQLite, existing FastHTML/JavaScript, installed
Ollama/Qwen3.5 9B with thinking disabled. No new runtime dependency is proposed.

**Spec:** The user's 20 September 2026 report and exact query above; the accepted
[Chat plan](chat-mvp.md), [read contracts](../issues/02-define-read-tools.md),
[runtime contract](../issues/06-define-agent-runtime.md), and
[small acceptance checklist](../issues/09-plan-implementation-slices.md).
The operator accepted all four decisions in
[Define Chat remediation scope and acceptance](../issues/19-define-chat-remediation-scope-and-acceptance.md).
This supersedes the original four-tool count with a five-tool target while retaining
the other accepted contracts. Four tools currently exist; the fifth and the repairs
below remain unimplemented. Read the
[Chat investigation handoff](../research/chat-investigation-handoff.md) for evidence
and the earlier proposal history. The order below now puts R1–R3 first.

## Global constraints

- SQLite remains authoritative; read current revisions only, including `placed`.
- Purchase date remains `delivery_at`, interpreted in `Asia/Singapore`. Missing
  dates remain unknown; source-email dates are not substitutes. Current records
  describe scheduled delivery slots, not confirmed arrivals. This agrees with the
  later delivery-date decision in ticket 20.
- Monthly item listing retains individual repeated lines. Ticket 20's proposed
  grouping for purchase-frequency analysis does not change this listing contract;
  graph analytics and predictions remain outside this remediation plan.
- Preserve money as integer cents with currency. Do not sum partial pages, merge
  distinct products, infer completion, or estimate missing quantities.
- Keep 4 model requests, 8 proposed tool calls, 180 seconds work, 5 seconds cleanup,
  8,192 context tokens, 6,912 input tokens, and 768 generated tokens per request.
- Keep exact token accounting, one active attempt, cancellation, retry/reconnect
  semantics, short SQLite connections, and saved-before-display streaming.
- Tool envelopes remain at most 4,096 UTF-8 bytes with whole rows. Evidence remains
  application-owned order/product links from fresh reads in the current attempt.
- No schema migration, model replacement, general SQL tool, analytics feature,
  vector database, agent framework, or deployment change is proposed.
- Real development data remains private. Use synthetic temporary databases for
  automated/model checks. Do not copy household facts into plans, fixtures, logs,
  terminal output, screenshots, or research prompts.

## Review focus and execution order

1. Preserve the baseline, then repair Stop/tool-result and marker-only completion
   faults. A later valid send must work without restart. Tasks 1–2.
2. Failed selection of stale B must preserve A in both browser state and server
   subscription. Task 3.
3. Ordinary replies, purchase claims, empty/partial results, and incomplete answers
   need explicit behavior. Validate the proposed protocol with the installed model
   before relying on it, and preserve requested fields in fallback handling. Task 4.
4. Resolve the previous complete calendar month using a frozen Singapore date,
   including January rollover. Task 5.
5. Retrieve current monthly item rows directly within existing limits; retain
   repeated lines, exclude unknown dates honestly, and preserve month/limit on
   continuation. Tasks 6–7.
6. Assert actual requested facts and recovery, not only completion or a valid link.
   Distinguish local/model/browser/operator checks from homelab acceptance. Task 8.

## Diagnosis and confidence

### Confirmed from code and synthetic review

- Stop racing with a returning tool result can forward unsaved Evidence to terminal
  persistence, leaving the saved attempt `stopping` and generation `faulted` (R1).
- Marker-only clarification/unsupported output can become empty completed text;
  storage correctly rejects it, but subsequent generation becomes `faulted` (R2).
- Selecting stale B while viewing A can clear A's client state while retaining B,
  and the server subscription changes before snapshot success (R3). A's stored
  data is not deleted. See the handoff for the synthetic probes and their limits.
- `assistant/context.py` supplies static instructions without an application date.
  The model has no dependable reference for “last month.”
- `assistant/tools.py` offers no month/date filter. All four tools also share one
  generic description instead of explaining their different purposes.
- `purchases/queries.py` returns order headers from `list_recent_orders`; item rows
  require `get_order` for each order or a known product for `get_product_history`.
  Discovering orders and fetching their items cannot cover arbitrary months within
  four requests/eight tools. Even nine matching orders exceed that tool budget.
- The greeting shortcut accepts “hello” but not “hello world.” A benign uncited
  model greeting then becomes `incomplete / missing_evidence`.
- The new generic fallback can turn an unrelated record dump into `complete`. It
  omits some available fields, including fees and unit prices, and an existing
  product with no current history produces a name/link without explaining absence.
- The existing real-model smoke checks one known order total. It also passes when
  the fallback supplies the asserted amount/link, so it cannot establish general
  answer relevance or model compliance.
- The numeric tool-call ID correction is valid and should retain its integration
  regression. The greeting allowlist and generic fallback need reconsideration.

### Not established

The exact answer and tool sequence from the user's real-data query have not been
inspected. The gaps above explain why the system cannot reliably support the query;
they do not prove whether that attempt chose the wrong month, skipped tools, hit a
limit, or used a different development database. Do not label the Ollama tunnel as
the cause without new transport evidence.

## Accepted target behavior — not yet implemented

- On 20 September 2026 in Singapore, “last month” means **1–31 August 2026**.
  The equivalent UTC interval is `[2026-07-31T16:00:00+00:00,
  2026-08-31T16:00:00+00:00)`. Use a half-open interval.
- Return recorded line items, with item name, quantity/unit when known, purchase
  date and order link. Grouping rows by order/date is presentation only; repeated
  purchases stay separate. Do not add a spending summary to this listing request.
- Start with a bounded useful page. If more rows exist, say “More items are
  available; ask for the next page.” “Next page” continues the same resolved month
  and validated cursor, including after reconnect. Do not claim all rows fit.
- For no matches, say no recorded items with known Purchase dates were found for
  the displayed month. Rows with unknown dates cannot be assigned to a month.
- Ordinary conversation completes without fabricated purchase links. A request
  containing shopping facts still goes through fresh reads and evidence checks.

## Approach choice

| Option | Result | Decision |
| --- | --- | --- |
| Prompt changes alone | Cannot create a missing cross-order month query | Insufficient |
| Date-filter `list_recent_orders`, then fetch each order | Still needs one or more detail calls per order | Insufficient at larger months |
| Add `list_purchase_items` | One bounded page directly retrieves matching item rows across orders | Accepted scope; implementation pending |

Do not broaden product search, add spending analytics, or change the model as part
of this query fix. Those need their own observed failing examples.

## Task 1: Establish a reproducible baseline

**Files:** `tests/assistant/test_assistant_runtime.py`,
`tests/assistant/test_assistant_tools.py`, `tests/assistant/test_conversations.py`,
`tests/web/test_chat_streaming.py`, `tests/browser/chat_draft_recovery.js`,
`tests/conftest.py`, `tests/integration/test_ollama_smoke.py`.

Read the handoff and establish the lifecycle baseline first. Stage the month-query
fixture and model checks below for tasks 5–8; do not let them delay R1–R3.

- [ ] Record HEAD and any worktree diff, preserving the checkpointed partial patch.
  Do not overwrite unrelated work or treat earlier passing tests as proof of this
  query's correctness.
- [ ] Reproduce the handoff's Stop race, marker-only completion, and stale-switch
  probes using synthetic data. Record safe outcome categories. Turn their desired
  outcomes into regression tests in tasks 2–3; use controlled synchronization for
  the Stop race instead of a timing-only sleep.
- [ ] Check that the running local app uses the intended development database and
  current code. Report only configuration match/mismatch, schema readiness, and
  safe outcome categories. Do not print `.env`, household rows, or process secrets.
- [ ] Build a synthetic file-backed fixture containing August and September orders,
  a replaced revision, undated rows, and enough August orders to exceed eight calls
  under the old per-order strategy. Preserve the established fixture patterns.
- [ ] Capture a baseline for the exact user query against that fixture. Record
  selected tool names, argument validity, row counts, terminal code, and whether
  the answer came from the model or deterministic rendering. Use private-free
  temporary traces; no new permanent diagnostic subsystem is needed.
- [ ] Add targeted failing expectations: the requested month's item names must
  appear, other-month names must not, and the answer must state its period/coverage.
  Reproduce the existing “hello world” failure in the same runtime test module.

The baseline separates configuration, intent/date resolution, retrieval, response
formatting, and completion failures. An unrelated transport failure is recorded
separately rather than explained by these retrieval changes.

## Task 2: Contain terminal-state failures (R1/R2)

**Modify:** `src/shopping/assistant/runtime.py`, `src/shopping/web/chat.py`,
`tests/assistant/test_assistant_runtime.py`, `tests/web/test_chat_streaming.py`,
`tests/assistant/test_conversations.py`.
**Inspect:** `src/shopping/assistant/conversations.py`; retain its strict validation.

- [ ] Convert the handoff's `stop_race.py` into a deterministic integrated
  runtime → WebSocket → storage regression. Force Stop to be accepted while a
  read result is returning and before the tool outcome is saved.
- [ ] Reconcile the stopped terminal text and Evidence with durable tool results.
  Do not forward unsaved Evidence, weaken storage validation, or let late complete
  output overwrite an accepted Stop. Keep saved-before-display behavior.
- [ ] Test both `[[unsupported]]` and `[[clarification]]` with no visible content.
  Validate nonempty final text after mode handling; save a failed/incomplete
  outcome instead of returning an empty completed response or a global fault.
- [ ] After each trigger, assert the saved terminal status, text/Evidence consistency,
  reload result, released response slot, and successful next valid send without
  restart. Preserve the distinct fault for genuinely unsettled cleanup and real
  persistence failures; do not swallow every exception to keep the slot available.
- [ ] Retain numeric batch-position tool-call IDs and existing persistence/reload
  coverage. Run focused runtime, storage, and streaming regressions.

## Task 3: Preserve Conversation state on failed switching (R3)

**Modify:** `src/shopping/web/static/chat.js`, `src/shopping/web/chat.py`,
`tests/browser/chat_draft_recovery.js`, `tests/web/test_chat_streaming.py`.

- [ ] Turn the handoff's stale-B selection probe into a client regression. Track
  the requested Conversation target with its command ID so a `gone` response for
  B cannot clear the still-valid A selection or library entry.
- [ ] Make failed subscription/snapshot switching leave or restore a consistent
  server subscription. Cover failure after the old selection is known, not just
  the browser's displayed title.
- [ ] Verify A's stored history and visible selection remain, only stale B is
  removed, and later A updates arrive. Ensure successful switches and genuinely
  deleted current Conversations retain their correct behavior.
- [ ] Verify through the integrated browser/server flow as well as the minimal
  client handler test. Do not describe the archived Node VM probe alone as browser
  integration evidence.

## Task 4: Define truthful response and fallback behavior (R4/R6)

**Modify:** `src/shopping/assistant/runtime.py`, `src/shopping/assistant/context.py`,
`src/shopping/web/static/chat.js`, `tests/assistant/test_assistant_runtime.py`,
`tests/web/test_chat_streaming.py`, `tests/browser/chat_draft_recovery.js`.
**Create:** `src/shopping/assistant/answers.py` for focused response validation and
record rendering extracted from the growing runtime module.

- [ ] Keep completion policy explicit: conversation/help, clarification,
  unsupported request, grounded answer, empty result, and incomplete generation
  have different requirements. Do not globally accept uncited free-form prose.
- [ ] Replace the input greeting phrase allowlist with a response contract. For
  nonfactual greeting/help/acknowledgement modes, prefer application-owned wording
  selected by a validated mode rather than trusting arbitrary uncited shopping
  claims. Mixed greeting/purchase questions must still invoke a read tool.
- [ ] Before choosing the wire encoding, run a small synthetic probe on the
  installed Qwen/Ollama combination for these modes and tool use. Start with the
  existing marker protocol extended to typed conversational modes. Test structured
  output only if native support is verified. Do not assume JSON format support or
  add hidden repair requests. Record the chosen encoding and exact parser tests
  before changing the completion parser; if the probe fails, report that design
  result instead of widening the evidence bypass.
- [ ] Preserve task 2's rejection of empty completed text after mode handling.
  Validate evidence references against this attempt's reads. A valid link is necessary for
  shopping claims but remains insufficient proof that arbitrary prose is factual.
- [ ] Do not silently label arbitrary tool-record fallbacks as an answered question.
  For other supported questions, either produce the requested grounded answer or
  explain that answer generation was incomplete while retaining useful links.
  Fix the parent-product/empty-history distinction and cover requested fee/price
  fields so a total/items dump cannot pass as an answer to those questions.
- [ ] Verify ordinary final responses replace provisional text consistently in
  saved state and on reconnect. Test requested fees/unit prices, explicit empty
  product history, mixed greeting/purchase requests, and malicious mode-prefixed
  shopping claims. Keep task 2's failure isolation and existing budgets intact.

## Task 5: Supply authoritative calendar context

**Create:** `src/shopping/assistant/dates.py`,
`tests/assistant/test_assistant_dates.py`.
**Modify:** `src/shopping/assistant/context.py`,
`src/shopping/assistant/runtime.py`, `tests/assistant/test_assistant_context.py`.

**Interfaces:** `previous_month(today: date) -> str` returns `YYYY-MM`;
`month_bounds(month: str) -> tuple[str, str]` returns UTC ISO start/end strings.
Invalid months raise the same safe `invalid_arguments` category as other tool
arguments. `instructions_for(now: datetime) -> str` supplies the current Singapore
date and previous calendar month alongside the static instructions.

- [ ] Write boundary tests before implementation, including the following exact
  expectations, leap February, invalid month strings, and aware-datetime handling:

  ```python
  assert previous_month(date(2026, 9, 20)) == "2026-08"
  assert previous_month(date(2026, 1, 1)) == "2025-12"
  assert month_bounds("2026-08") == (
      "2026-07-31T16:00:00+00:00",
      "2026-08-31T16:00:00+00:00",
  )
  ```

- [ ] Freeze an aware application timestamp once at attempt start. Build the
  instructions once and reuse them through every generation request. Expose an
  optional `now: datetime | None` keyword on `run_attempt` for deterministic tests.
- [ ] Let `bounded_messages` receive that exact instructions string. Count the same
  messages sent to Ollama; do not prepend dates after counting tokens.
- [ ] Verify a simulated month rollover between model calls does not change the
  current attempt's date context. A later attempt gets a fresh reference date.
- [ ] Run the date, context, and runtime tests; review the change independently.

## Task 6: Retrieve a month of recorded items directly

**Modify:** `src/shopping/assistant/tools.py`, `src/shopping/purchases/queries.py`,
`tests/assistant/test_assistant_tools.py`, `tests/assistant/test_conversations.py`.

**Interface:** Add `list_purchase_items` with required `month: "YYYY-MM"`, optional
`limit` default 10 / maximum 20, and the existing optional cursor. Keep
`dispatch_tool(settings, name, arguments)` and the existing result envelope.

Returned `data` contains `month`, `timezone: "Asia/Singapore"`, and `items`. Each row
contains the existing item fields plus order ID/reference, retailer, Purchase
date, status and currency. Existing order/product evidence entries supply links.

- [ ] Add failing tests for valid/invalid month arguments, strict extra-argument
  rejection, cursor/month binding, and the new exact five-tool allowlist.
- [ ] Reuse `_ITEM_FROM` and `_ITEM_FIELDS` to read only current revisions. Bind
  the computed UTC start/end as SQL parameters:

  ```sql
  WHERE rev.delivery_at >= ? AND rev.delivery_at < ?
  ORDER BY rev.delivery_at DESC, o.id DESC, oi.line_number, oi.id
  LIMIT ? OFFSET ?
  ```

- [ ] Use the existing limit-plus-one, whole-row envelope sizing, evidence creation,
  and signed cursor machinery. Bind cursors to database, month, tool and limit.
  Unknown dates naturally stay outside the interval. No Python scan of the entire
  database and no model-generated SQL are needed.
- [ ] Assert exact item IDs at each boundary, exclusion of historical revisions,
  inclusion of `placed`, preservation of repeated lines, and `ok` with empty items
  for an empty month. Never convert an empty result into a provider failure.
- [ ] Follow every page on a fixed synthetic dataset and compare the concatenated
  row IDs against an independent expected list. Check no gaps/duplicates, 4 KiB
  envelopes, corrupt/cross-month cursors, oversized individual rows, and restart
  cursor expiration. Existing live-pagination semantics still apply if data changes.
- [ ] Verify the new tool persists and reconstructs through existing Conversations;
  retain the numeric batch-position call IDs. No migration is expected.
- [ ] Give each read tool a distinct purpose/argument description. The new tool is
  for item listings across a specified calendar month, not totals or forecasts.

## Task 7: Render and continue monthly item pages (R5)

**Modify:** `src/shopping/assistant/answers.py`, `src/shopping/assistant/runtime.py`,
`src/shopping/assistant/context.py`, `src/shopping/web/static/chat.js`,
`tests/assistant/test_assistant_runtime.py`, `tests/web/test_chat_streaming.py`,
`tests/browser/chat_draft_recovery.js`.

- [ ] Render a successful `list_purchase_items` page from its validated recorded
  rows and evidence, preserving the month, quantities, dates, and partial flag.
  This exact listing is useful deterministic output, not a generic record dump.
  Keep the renderer under existing saved-text/evidence limits and escape untrusted
  names without creating markers, HTML, or fake rows.
- [ ] Add the new human-readable tool activity label. Keep browser copy specific
  enough to distinguish a failed read/generation from valid empty/partial results.
- [ ] Verify streamed text is replaced consistently by the final recorded answer,
  including saved state and reconnect. “Next page” reuses the original resolved
  month; an expired cursor explicitly restarts listing instead of pretending to
  continue. Existing cancellation and duplicate-command safeguards must hold.
- [ ] Preserve the original resolved month and validated limit across turns,
  reconnect, and calendar rollover. Cover a nondefault limit as well as the default.
  State partial coverage and missing-date limitations without claiming an immutable
  snapshot of live data or computing whole-month totals from a page.

## Task 8: Verify useful answers end to end

**Modify:** `tests/integration/test_ollama_smoke.py`,
`tests/web/test_chat_streaming.py`, `tests/browser/chat_draft_recovery.js`,
`README.md`, `docs/MVP_PLAN.md`.

Keep a small fixed set, consistent with ticket 09, rather than a new benchmark:

| Input/condition | Acceptance |
| --- | --- |
| Stop during returning tool result | Durable stopped/incomplete state, only saved Evidence, and next send succeeds |
| Marker-only clarification/unsupported output | Failed/incomplete attempt, no global fault, and next send succeeds |
| Open stale B while viewing A | Only B removed; A remains selected and receives updates |
| “hello world”, “what can you do?”, “thanks” | Relevant nonempty reply; no purchase-link failure |
| Exact last-month query, September clock | August items, correct quantities/dates, valid purchase links |
| Same query, January clock | December of the preceding year |
| More than eight matching orders and multiple pages | Direct bounded item read, truthful partial notice, working continuation |
| Empty month and rows with unknown dates | Scoped absence; no invented dates or facts |
| Historical revisions and repeated products | Current rows only; distinct purchases retained |
| Product ambiguity / no current product history | Choice prompt / explicit empty history |
| Order fee question / existing total question | Requested recorded field, not an unrelated record dump |
| Malicious stored text / fake evidence / unsupported prediction | No instruction execution, invented links, or invented answer |
| Reload, reconnect, Stop and retry | Durable result, no duplicate generation or stale terminal overwrite |

- [ ] Run deterministic tests first. Assert requested fields, wrong-month
  exclusions, tool arguments, and coverage; `status == complete` alone is not enough.
- [ ] Run the selected installed model against synthetic temporary data, including
  the exact user query and one continuation. Distinguish model-generated answers
  from deterministic renderings in test observations; report which path passed.
- [ ] Verify Chat in an isolated browser/dev server. Then validate the user's
  selected query locally against the intended real-data app, keeping household
  output out of test artifacts/logs. Record only whether the expected records and
  links matched. Do not claim private-data acceptance before it happens.
- [ ] Update README and MVP scope to describe the implemented fifth tool, calendar
  semantics, response modes, and partial answers. Preserve older planning history;
  append a superseding decision/link when accepted. Do not mark homelab ticket 18
  complete based on local verification.
- [ ] Run repository format/lint/type/test/secret checks and built-wheel migration
  verification before implementation handoff. Use the committed lockfile and
  pinned toolchain. Review each coherent change before any requested commit.

## Completion bar and present status

Completion requires all six repairs: correct saved terminal outcomes and a usable
next send after R1/R2, consistent A selection/subscription after R3, truthful
ordinary/fallback behavior, and a correct, useful bounded item listing for the exact
last-month question. Results must survive save/reload. A working tunnel, successful
tool call, green total smoke, or
generic fallback is not sufficient evidence by itself.

This document is planning only. No source, test, configuration, database, model,
server, or deployment change was made while preparing it. The earlier partial
patch is checkpointed in `b5e6018` and is not certified as a complete fix by this
plan. The operator's accepted scope is recorded in the resolved decision ticket;
implementation and all new verification remain pending.
