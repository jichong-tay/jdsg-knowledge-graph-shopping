# Chat reliability and useful purchase answers — Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` when implementation is requested. This is a proposed
> plan, not authorization to execute it. The user explicitly requested review and
> planning only. Preserve the existing uncommitted patch while reviewing its parts.

**Goal:** Make ordinary conversation complete normally and answer “what are the
items i bought last month” with the correct recorded items, dates, quantities,
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
This proposal explicitly changes the four-read-tool scope to five. Existing
decisions remain authoritative until this change is accepted for implementation.

## Global constraints

- SQLite remains authoritative; read current revisions only, including `placed`.
- Purchase date remains `delivery_at`, interpreted in `Asia/Singapore`. Missing
  dates remain unknown; source-email dates are not substitutes.
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

## Review focus

1. Relative dates at a Singapore month boundary and January rollover must select
   the previous complete calendar month, not the last 30 days. Owned by task 2.
2. A month with many orders/items must remain useful within the existing budget;
   a displayed first page must not imply full coverage. Owned by tasks 3 and 4.
3. Empty months, unknown dates, and replaced revisions must not become invented
   purchases or false claims that no purchases ever occurred. Owned by task 3.
4. Greetings, capabilities, and thanks need no purchase evidence; a mixed request
   such as “hello, list last month's items” still needs a fresh read. Owned by task 4.
5. A successful tool read or valid citation alone does not prove an answer is
   relevant or correct. Test the actual requested facts and answer path. Task 5.

## Diagnosis and confidence

### Confirmed from code and synthetic review

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

## Proposed behavior

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
| Add `list_purchase_items` | One bounded page directly retrieves matching item rows across orders | Recommended scope change |

Do not broaden product search, add spending analytics, or change the model as part
of this query fix. Those need their own observed failing examples.

## Task 1: Establish a reproducible baseline

**Files:** `tests/assistant/test_assistant_runtime.py`,
`tests/assistant/test_assistant_tools.py`, `tests/conftest.py`,
`tests/integration/test_ollama_smoke.py`.

- [ ] Preserve and record the existing worktree diff; do not overwrite unrelated
  work or treat earlier passing tests as proof of this query's correctness.
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

## Task 2: Supply authoritative calendar context

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

## Task 3: Retrieve a month of recorded items directly

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

## Task 4: Make completion and rendered answers truthful

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
- [ ] Reject empty completed text even when a mode marker is present. Validate
  evidence references against this attempt's reads. A valid link is necessary for
  shopping claims but remains insufficient proof that arbitrary prose is factual.
- [ ] Render a successful `list_purchase_items` page from its validated recorded
  rows and evidence, preserving the month, quantities, dates, and partial flag.
  This exact listing is useful deterministic output, not a generic record dump.
  Keep the renderer under existing saved-text/evidence limits and escape untrusted
  names without creating markers, HTML, or fake rows.
- [ ] Do not silently label arbitrary tool-record fallbacks as an answered question.
  For other supported questions, either produce the requested grounded answer or
  explain that answer generation was incomplete while retaining useful links.
  Fix the parent-product/empty-history distinction and cover requested fee/price
  fields so a total/items dump cannot pass as an answer to those questions.
- [ ] Add the new human-readable tool activity label. Keep browser copy specific
  enough to distinguish a failed read/generation from valid empty/partial results.
- [ ] Verify streamed text is replaced consistently by the final recorded answer,
  including saved state and reconnect. “Next page” reuses the original resolved
  month; an expired cursor explicitly restarts listing instead of pretending to
  continue. Existing cancellation and duplicate-command safeguards must hold.

## Task 5: Verify useful answers end to end

**Modify:** `tests/integration/test_ollama_smoke.py`,
`tests/web/test_chat_streaming.py`, `tests/browser/chat_draft_recovery.js`,
`README.md`, `docs/MVP_PLAN.md`.

Keep a small fixed set, consistent with ticket 09, rather than a new benchmark:

| Input/condition | Acceptance |
| --- | --- |
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

Completion requires the exact last-month question to return the correct, useful
bounded item listing, ordinary conversation to complete, and the same result to
survive save/reload. A working tunnel, successful tool call, green total smoke, or
generic fallback is not sufficient evidence by itself.

This document is planning only. No source, test, configuration, database, model,
server, or deployment change was made while preparing it. The earlier uncommitted
fix remains present and is not certified as a complete fix by this plan.
