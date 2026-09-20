# Define Chat remediation scope and acceptance

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex
Prepared: 20 September 2026

## Question

Which repair sequence, response contract, and retrieval scope should guide the
Shopping Assistant's Chat remediation, and what evidence will establish that
ordinary Conversation and “what are the items i bought last month” work correctly?

## Work boundary

**Later priority change:** The operator has requested
[knowledge graph modeling](20-define-shopping-knowledge-graph-model.md) before more
tools. The decisions below remain accepted planning history; their execution is
queued after the graph foundation. The defects are not fixed by deferring them.
[Ticket 22](22-implement-chat-remediation.md) now tracks implementation immediately
after ticket 21; this resolved ticket remains the accepted decision record.

**Delivery-date clarification:** The operator's subsequent delivery-date decision
in ticket 20 agrees with this ticket's accepted monthly retrieval contract. Use
`delivery_at` as Purchase Date in `Asia/Singapore`; current records contain the
start of a scheduled delivery slot, not confirmation of arrival. Missing dates
remain unknown. The monthly listing preserves individual item lines; grouping
purchase occasions for frequency/predictions belongs to ticket 20's separate
analytic design and does not change this listing's scope.

The operator first requested **ticket preparation without implementing fixes**, then
worked through the planning discussion and explicitly said **“Accept all four.”**
The planning decisions are resolved below. This accepts the remediation scope and
acceptance bar; it does not authorize implementation, commits, service restarts,
model changes, or deployment.

The accepted target now contains five Read Tools; only four are implemented.
Preserve the earlier partial patch and assess its parts;
neither revert it wholesale nor describe it as a complete fix.

## Read first

- [Chat investigation handoff](../research/chat-investigation-handoff.md) is the
  primary evidence record, including the synthetic probes and known limitations.
- [Chat reliability and useful purchase answers — Implementation Plan](../plans/chat-reliability-and-answer-quality.md)
  has been reconciled with this decision: address R1–R3 before response behavior
  and monthly retrieval. The handoff preserves the earlier proposal's history.
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

## Decision proposal — accepted in round one

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

## Accepted implementation acceptance checks

These checks describe later authorized work; none is marked passed by this ticket.

| Scenario | Required observable result |
| --- | --- |
| Stop during tool-result return | Correct saved stopped/incomplete outcome, no unsaved Evidence, no stale terminal overwrite, and the next valid send succeeds without restart. |
| Either marker-only reply | No empty completed response; a saved failed/incomplete Response Attempt and a working subsequent send. |
| Open stale B while viewing A | Only B is removed; A's selection, stored history, and incoming subscription updates remain correct. |
| `hello world`, thanks, help, clarification, unsupported request | Relevant nonempty behavior without fabricated purchase links; no arbitrary factual bypass. A mixed purchase request uses fresh reads. |
| Delivery-fee/unit-price question and empty product history | Requested recorded fields are retained, or incompleteness is explicit; empty current history is stated rather than hidden by parent metadata. |
| Exact month question | Correct item names, quantities, Purchase Dates, valid Evidence, displayed period, and wrong-month exclusions; September and January clocks, leap February, and timezone boundaries covered. |
| Larger month and continuation | More than eight matching orders handled within unchanged budgets; current revisions only, repeated lines retained, bounded whole-row pages, honest partial notice, original month/limit preserved, and explicit expired-cursor recovery. |
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
  this ticket initially, and no private database, logs, or model answers were
  inspected at that stage. The later authorized read-only data audit in
  [ticket 20](20-define-shopping-knowledge-graph-model.md) establishes structural
  and date coverage; it does not reproduce the original Chat failure or validate
  any remediation.
- Broader product search and candidate labels are capability limits, not proven
  causes of the month-query report. Older-click duplication was withdrawn as a
  finding; a token-fetch/handshake timeout remains unverified. Do not add them to
  the confirmed repair scope.

## Resolution criteria

- [x] Record the operator's answers on repair order, response behavior, monthly
  retrieval scope, and the acceptance bar; recommendations are not acceptance.
- [x] Record accepted/deferred boundaries and any required focused protocol probe.
  Split a newly necessary investigation into its own ticket rather than assume
  its result.
- [x] Reconcile the earlier proposed plan with R1–R3 and the accepted decisions,
  preserving prior decision history and the existing partial patch.
- [x] Append the answer under `## Answer`, set `Status: resolved`, and add a named
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
- The operator subsequently selected this ticket for the planning discussion.
  Claimed by Codex; implementation remains out of scope for this discussion.
  The worktree is clean at the start of this session, so the handoff's description
  of the partial patch as uncommitted is historical, not the current Git status.
  Current HEAD is `b5e6018` (`chore: checkpoint partial chat fixes and investigation`).
- The operator subsequently requested the graph implementation ticket and asked
  whether these repairs would still be worked on. Added
  [ticket 22](22-implement-chat-remediation.md) as the explicit next implementation
  priority after [ticket 21](21-build-product-family-foundation.md). This resolved
  ticket remains the decision record; R1–R6 remain unfixed. No execution occurred.

### Decision round one — accepted

1. **Repair scope and order:** Address all six findings, starting with R1/R2,
   then R3, response/fallback behavior, and any accepted monthly retrieval work?
   Recommendation: yes; preserve the valid tool-call ID correction. Scope could
   instead stop at lifecycle reliability, leaving answer-quality gaps explicit.
2. **Ordinary replies and incomplete answers:** Allow greetings, thanks, help,
   clarification, and unsupported-request explanations without purchase links,
   while requiring fresh reads and Evidence for purchase claims?
   Recommendation: yes; use application-owned wording for nonfactual response
   modes where practical. A mixed purchase question still needs retrieval. If the
   requested facts cannot be answered, mark the result incomplete rather than
   present an unrelated record summary as success. The exact protocol still needs
   a focused synthetic compatibility check before implementation relies on it.
3. **Monthly item scope:** Accept the fifth bounded month-item Read Tool and
   frozen Singapore calendar context, or defer this capability?
   Recommendation: accept, retaining delivery date as Purchase Date, current
   revisions, repeated lines, and explicit empty/partial coverage. Show a useful
   first page and continue the original month/limit on request; do not increase
   global budgets to enumerate individual orders.
4. **Acceptance bar:** Use the ticket's small synthetic regression set, then a
   real-model/browser check and the operator's private check of the exact query?
   Recommendation: yes; assert requested facts and recovery of the next send,
   not only successful status or a link. Report model prose versus deterministic
   output separately, and leave homelab service/rollback verification separate.

The operator answered **“Accept all four.”** No implementation was started while
preparing or resolving this round. The operator also asked whether RAG or BM25 is
needed; that is an architecture question, not authorization to add either.
The [retrieval research note](../research/chat-retrieval-options.md) recommends
exact SQLite retrieval for the current month query and defers relevance-search
enhancements until measured product-search gaps justify them. This recommendation
does not add another accepted feature or block the resolved remediation scope.

### Subsequent graph and date decisions

The operator prioritized knowledge graph modeling, then chose delivery date for
item frequency and future purchase predictions. Ticket 19 remains **resolved for
planning**, with all four decisions accepted and repair execution deferred behind
ticket 20. Its existing delivery-date monthly listing is consistent with that
choice. Predictions, product-frequency aggregation, and graph tools are not added
to the Chat remediation scope. No repair, test run, or deployment is completed by
this clarification.

## Answer

All four recommendations are accepted. This resolves planning only:

1. **Repair all six findings in order:** R1/R2 global faults, R3 Conversation
   switching, R4/R6 response and fallback correctness, then R5 monthly retrieval.
   Preserve the valid numeric tool-call ID correction and its regression coverage.
2. **Separate ordinary replies from purchase claims.** Greetings, thanks, help,
   clarification, and unsupported-request explanations can complete without
   purchase links. Purchase claims still require fresh reads and valid Evidence;
   mixed requests cannot bypass retrieval. Prefer application-owned nonfactual
   wording where practical. Preserve empty/partial meanings and requested fields;
   an unrelated record dump is not a successful answer.
3. **Accept the fifth bounded Read Tool and application-owned date context.**
   `list_purchase_items(month="YYYY-MM", limit=10, cursor=...)` uses a maximum of
   20 whole rows within 4 KiB. Freeze Singapore calendar context per Response
   Attempt; use delivery date as Purchase Date, current revisions including
   `placed`, and distinct repeated purchase lines. Unknown dates stay unknown.
   Deterministically render validated monthly rows with honest pagination;
   continuation preserves the month and original limit. Existing runtime budgets,
   cursor expiry, and live-pagination limitations remain unchanged.
4. **Require meaningful acceptance evidence.** Use the small regression set above,
   real-model/browser verification, and the operator's private check of the exact
   query. Assert requested facts and subsequent-send recovery. Distinguish model
   prose from deterministic rendering and leave homelab verification separate.

The [remediation plan](../plans/chat-reliability-and-answer-quality.md) now records
this sequence and the lifecycle regressions. The fifth tool and all six repairs
remain unimplemented by this planning work. The accepted scope supersedes the
original four-tool count, while retaining the existing read-only/privacy contracts.

**Pending execution evidence:** Before changing the response protocol, run the
small synthetic compatibility probe against the installed Qwen/Ollama combination.
No marker/structured-output reliability result is assumed. If the probe rules out
the accepted behavior within current limits, surface the conflict as a new decision
instead of silently widening the Evidence bypass or generation budget. This pending
check does not reopen the operator's accepted product scope.

No new domain term, schema migration, runtime dependency, model, retrieval index,
or infrastructure is part of these accepted decisions. Implementation awaits the
operator's request; no tests or host checks are claimed by this resolution.

## Subsequent execution — 21 September 2026 (Singapore)

The operator later authorized implementation after the graph UI redesign, with
Luna/low coding and controller review. [Ticket 22](22-implement-chat-remediation.md)
records the six local repairs, the fifth read tool, response/calendar decisions,
actual-database verification and final checks. This supersedes the historical
pending-implementation statements above. Ticket 19 remains the accepted decision
record; ticket 18's homelab deployment and rollback verification remain separate.
