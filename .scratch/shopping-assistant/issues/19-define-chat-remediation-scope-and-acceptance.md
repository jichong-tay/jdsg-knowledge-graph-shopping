# Define Chat remediation scope and acceptance

Parent: ../map.md
Type: grilling
Status: open
Prepared: 20 September 2026

## Question

Which repair sequence, response contract, and retrieval scope should guide the
Shopping Assistant's Chat remediation, and what evidence will establish that
ordinary Conversation and “what are the items i bought last month” work correctly?

## Work boundary

The operator requested **ticket preparation first, without implementing fixes**.
This is an unclaimed decision ticket for a future discussion with the operator.
Preparing it does not accept the recommendations below or authorize implementation,
commits, service restarts, model changes, or deployment. Do not claim or resolve it
merely because its questions and proposed acceptance checks have been written.

The existing four-Read-Tool scope remains authoritative. A fifth tool is an open
scope decision. Preserve the earlier uncommitted patch and assess its parts;
neither revert it wholesale nor describe it as a complete fix.

## Read first

- [Chat investigation handoff](../research/chat-investigation-handoff.md) is the
  primary evidence record, including the synthetic probes and known limitations.
- [Chat reliability and useful purchase answers — Implementation Plan](../plans/chat-reliability-and-answer-quality.md)
  is an earlier proposal. It predates the lifecycle review; its task order must not
  take precedence over the handoff's recommendation to address R1–R3 first.
- Retain the accepted [read-tool and evidence contracts](02-define-read-tools.md),
  [durable Conversation lifecycle](04-define-conversation-lifecycle.md),
  [agent runtime](06-define-agent-runtime.md), and
  [streaming, cancellation, and reconnect semantics](07-define-streaming-protocol.md).
- Keep verification proportional to
  [Plan the implementation and rollout slices](09-plan-implementation-slices.md).
  Local remediation cannot resolve
  [Verify the homelab Shopping Assistant MVP](18-verify-homelab-chat-mvp.md).

## Findings to address

These are findings recorded by the handoff, not fresh reproduction results from
this ticket-preparation session. Details and probes stay in that evidence record.

| Finding | Recorded impact | Proposed priority and repair outcome |
| --- | --- | --- |
| R1 — Stop races with a returning tool result (P1) | Unsaved Evidence reaches terminal persistence; the Response Attempt remains `stopping` and all generation becomes `faulted`. | First: terminal text/Evidence agree with saved tool records; normal Stop settles and a later valid send works. Preserve the safeguard for genuinely unsettled cleanup. |
| R2 — Marker-only completion (P1) | `[[unsupported]]` or `[[clarification]]` becomes empty completed text; storage rejects it and later sends fail globally. | First, alongside R1: validate the final visible text, save an explicit failed/incomplete outcome, and keep the next valid send usable. Do not weaken storage validation. |
| R3 — Failed Conversation switch (P2) | Selecting stale B while viewing A clears A's UI entry/selection, leaves B visible, and may change the server subscription. A's stored data is not deleted. | Next: identify B as the failed target, remove only stale B, preserve A, and keep later A updates arriving. Cover client and server boundaries. |
| R4 — Ordinary Conversation fails Evidence checks (P1) | Benign replies to `hello world`, thanks, help, and natural clarification still return `missing_evidence`. | Replace the exact-phrase greeting shortcut with an explicit response contract; mixed purchase requests still require fresh reads. |
| R5 — Last-month item retrieval gap | No application-owned date context or month-item Read Tool; per-order discovery/detail calls cannot cover larger months within the tool budget. | Decide whether to accept the proposed fifth bounded Read Tool and calendar semantics. This is recorded-item retrieval, not spending analytics. |
| R6 — Fallback loses requested facts (P2) | A requested delivery fee can disappear into an order-total summary; empty current product history can appear as a name/link with no absence explanation. | Preserve the requested fields and empty/partial meanings; a successful read or generic record dump cannot certify that the question was answered. |

## Decisions to resolve with the operator

1. **Repair order and treatment of the existing patch.** Recommend R1/R2, then R3,
   then the response/fallback contract, followed by any accepted monthly retrieval
   work. Retain the verified numeric batch-position tool-call IDs such as `1:0`
   and their persistence/reload regression. Revisit the greeting allowlist and
   generic fallback. Keep useful failure explanations without mistaking them for
   repaired behavior.

2. **When may a response complete without purchase Evidence?** Recommend explicit
   behavior for ordinary Conversation/help, clarification, unsupported requests,
   grounded purchase answers, empty results, and incomplete generation. Prefer
   application-owned nonfactual wording selected by a validated mode; arbitrary
   uncited shopping claims must not pass because of a prefix. Mixed requests such
   as “hello, list last month's items” require fresh reads. A valid Evidence link
   alone does not prove semantic correctness. Choose the wire encoding only after
   a small synthetic probe of the installed Qwen/Ollama combination; native
   structured-output support and reliability are not established. Do not add a
   hidden repair-generation loop.

3. **Accept, revise, or defer monthly item retrieval?** Recommend freezing the
   Singapore date once per Response Attempt and adding
   `list_purchase_items(month="YYYY-MM", limit=10, cursor=...)`, maximum 20 whole
   rows within the existing 4 KiB result envelope. The alternatives of prompt-only
   changes or order-by-order detail reads do not remove the larger-month retrieval
   gap. If deferred, record that reliable support for the exact month query remains
   unresolved rather than calling the overall user report fixed.

   Purchase Date continues to mean `delivery_at` in `Asia/Singapore`. On
   20 September 2026, “last month” means August, with UTC interval
   `[2026-07-31T16:00:00+00:00, 2026-08-31T16:00:00+00:00)`.
   Include current revisions and `placed` records, retain repeated purchase lines,
   and leave unknown dates unknown. Recommend deterministic rendering of validated
   month-item rows with quantities, dates, Evidence, and honest partial coverage.
   Continuation must retain the resolved month and original limit across turns,
   reconnect, and calendar rollover. Cursors remain bound to database/tool/arguments
   and expire on app restart; an expired cursor requires an explicit restart of
   listing. Live pagination is not an immutable month snapshot.

4. **What proves useful answers and recovery?** Recommend the small acceptance set
   below, followed by a private operator check of the exact query in the intended
   development app. Confirm the app's code/database configuration using safe
   match/mismatch results. Keep future model and browser observations distinct
   from unit/probe results and distinguish model prose from deterministic output.
   Preserve separate homelab/service acceptance.

## Proposed implementation acceptance checks

These checks describe later authorized work; none is marked passed by this ticket.

| Scenario | Required observable result |
| --- | --- |
| Stop during tool-result return | Correct saved stopped/incomplete outcome, no unsaved Evidence, no stale terminal overwrite, and the next valid send succeeds without restart. |
| Either marker-only reply | No empty completed response; a saved failed/incomplete Response Attempt and a working subsequent send. |
| Open stale B while viewing A | Only B is removed; A's selection, stored history, and incoming subscription updates remain correct. |
| `hello world`, thanks, help, clarification, unsupported request | Relevant nonempty behavior without fabricated purchase links; no arbitrary factual bypass. A mixed purchase request uses fresh reads. |
| Delivery-fee/unit-price question and empty product history | Requested recorded fields are retained, or incompleteness is explicit; empty current history is stated rather than hidden by parent metadata. |
| Exact month question, if accepted | Correct item names, quantities, Purchase Dates, valid Evidence, displayed period, and wrong-month exclusions; September and January clocks, leap February, and timezone boundaries covered. |
| Larger month and continuation, if accepted | More than eight matching orders handled within unchanged budgets; current revisions only, repeated lines retained, bounded whole-row pages, honest partial notice, original month/limit preserved, and explicit expired-cursor recovery. |
| Empty month, unknown dates, malicious stored text | Scoped absence without invented facts/dates; escaped data cannot inject instructions, Evidence, or fake rows. |
| Save/reload, reconnect, Retry, and two-tab state | Final text/status/Evidence remain consistent, failed attempts stay historical, and reconnect does not generate duplicate work. |

Retain one active Response Attempt, 4 generation requests, 8 proposed tool calls,
180 seconds work plus 5 seconds cleanup, 6,912 input tokens, and 768 output tokens
per request. Preserve SQLite authority, append-only purchase facts, integer cents,
short transactions, protected Chat access, private permissions, loopback listeners,
and the existing deployment/backup/rollback path. No new framework, model, schema,
analytics feature, search expansion, or infrastructure is proposed here.

## Evidence limits and deferred questions

- The user's real-data query's exact answer and tool sequence have not been
  inspected. Structural gaps and synthetic probes do not prove that attempt's
  failure path, that the running app loaded the patch, or the normal-use frequency
  of the global faults. Do not blame the tunnel without transport evidence.
- The handoff's focused 92-pass suite and earlier 287-pass/1-skipped suite are
  historical. The three archived probes expose missing coverage; their deliberate
  failures are not newly introduced regressions. No tests were rerun to prepare
  this ticket, and no private database, logs, or model answers were inspected.
- Broader product search and candidate labels are capability limits, not proven
  causes of the month-query report. Older-click duplication was withdrawn as a
  finding; a token-fetch/handshake timeout remains unverified. Do not add them to
  the confirmed repair scope.

## Resolution criteria

- [ ] Record the operator's answers on repair order, response behavior, monthly
  retrieval scope, and the acceptance bar; recommendations are not acceptance.
- [ ] Record accepted/deferred boundaries and any required focused protocol probe.
  Split a newly necessary investigation into its own ticket rather than assume
  its result.
- [ ] Reconcile the earlier proposed plan with R1–R3 and the accepted decisions,
  preserving prior decision history and the existing partial patch.
- [ ] Append the answer under `## Answer`, set `Status: resolved`, and add a named
  context pointer to the map only after the live decision discussion is complete.

Resolving this planning ticket does not mean any defect is fixed. Implementation
still requires the operator to request it; retain the handoff's Luna/low preference
for that later implementation. Future code handoff must run proportional tests,
repository checks, and isolated built-wheel migration verification.

## Comments

- 20 September 2026 — Prepared from the investigation handoff at the operator's
  request. No decisions resolved and no fixes implemented. The existing seven-file
  patch is preserved; the handoff remains the source for its diff fingerprint and
  historical validation evidence.
