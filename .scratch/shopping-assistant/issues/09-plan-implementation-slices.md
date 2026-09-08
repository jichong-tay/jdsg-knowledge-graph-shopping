# Plan the implementation and rollout slices

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: 05, 06, 07, 11, 12

## Question

How should the resolved persistence, tool, provider, agent, transport, UI, security, evaluation, documentation, and deployment work be divided into reviewable implementation tickets that preserve the repository invariants and reach the working destination?

## Comments

- The operator reports the hosted app, Tailscale access, and deployment pipeline are already working. Reuse these; plan the incremental Chat UI, Python/Ollama integration, explicit chat migration, homelab model/service setup as needed, and end-to-end verification. Do not recreate the bootstrap/network pipeline.
- Cloud support and agent-framework research are outside the Ollama-only MVP. The previously agreed read-tool and conversation behaviors remain required.
- Use the operator-selected installed `qwen3.5:9b` with thinking disabled. Do not gate implementation on comparing models or the research report's proposed repeated benchmark. Keep normal synthetic tool/evidence and runtime checks; revisit the model only if a concrete problem occurs.

## Implementation simplicity — explicit operator requirement

The operator is learning Python and systems thinking and wants an MVP, not a
general-purpose platform. Plan short, understandable vertical slices in the existing
FastHTML/SQLite application. Prefer ordinary functions, explicit state transitions,
one active async response task, and existing library facilities over abstraction
layers. Explain each slice's inputs, state changes, failure behavior, and checks.

Keep the accepted safeguards for facts, privacy, duplicate commands, and recovery,
but do not add brokers, distributed coordination, a generic event/RPC framework,
token event-replay storage, separate authentication services, or speculative provider
extensibility. Keep protocol bounds as simple defaults, not a configuration product.
Private remote access is only through the existing Tailscale Serve path; no public
endpoint or fresh network/deployment architecture is in scope.

## Acceptance checklist — merged from ticket 08

Deployment compatibility prerequisite: the current `deploy-ubuntu.sh` validates
exactly five `SHOPPING_*` environment entries before checkout. Adding Chat settings
to the existing environment file requires a compatible helper rollout before those
keys are introduced, with old-code/config rollback compatibility checked. Keep the
existing in-place deployment; do not create a second deployment architecture to
avoid this small migration. Core readiness currently gates code/database rollback;
ticket 12 already requires separate assistant availability so a model outage alone
does not trigger core application/database rollback.

The operator agreed to fold evaluation into this implementation plan instead of
running a separate ticket 08 grilling exercise. Attach proportional checks to the
implementation slices and the final end-to-end verification:

- Receipt answers match authoritative facts and link valid evidence. Include current-revision selection, Purchase date, ambiguity, missing facts, and partial-page completeness.
- Unsupported requests do not produce invented answers; malformed tool calls and prompt injection cannot bypass the four read-tool boundary or disclose excluded data.
- Save/resume, restart recovery, Stop/Retry, reconnect without duplicate generation, and confirmed deletion work under the agreed lifecycle.
- Ollama runs reliably on the actual homelab within the accepted runtime limits; verify GPU/model fit, failures, context/output bounds, and responsiveness through the existing Tailscale application route.

Use a small fixed set of synthetic examples plus the scoped operator acceptance
check, not a separate benchmarking/scoring project. Merging ticket 08 removes a
planning ceremony, not the implementation verification requirement.

## Grilling round one — original proposal

The final Answer below records the accepted build order and the operator's changed
rollout choice. In particular, the original Q2 batch-rollout recommendation is not
the selected policy.

All feature, model, privacy, and runtime decisions remain settled. This round only
decides the implementation sequence and rollout grouping. No application code,
migration, model execution, or homelab change is authorized by this planning work.

### Q1 — Build order

Recommend five implementation tickets, with a small testable result from each:

1. **Purchase history tools and evidence:** implement the four accepted read tools, bounded
   pages, Purchase Date mapping, and inspectable product/order evidence. Check
   current revisions, `placed` records, missing values, ambiguity, and malicious
   stored text with synthetic fixtures.
2. **Qwen connection and Python loop:** configure the selected installed
   `qwen3.5:9b` with thinking disabled; implement strict tool dispatch, input/output
   budgets, evidence checks, and cancellation. Use one focused synthetic live
   question/tool/result/answer check during implementation, not a model comparison
   or an additional permanent CLI. Broader deterministic error cases use a fake
   provider. Verify model-aware context accounting here before UI integration.
3. **Saved Conversations and Response Attempts:** add the next migration and short
   repository operations for messages, attempts, bounded tool records, command
   deduplication, update versions, and restart recovery. Check Retry, state races,
   and deletion fences without a browser or real model.
4. **Approved Chat UI and live recovery:** connect prototype A's design to real
   storage and the loop using the existing shell. Implement the protected
   WebSocket, saved-before-display streaming, Stop/Retry, snapshot reconnect,
   cross-tab state, confirmed deletion, and bounded safe rendering together. Test
   lifecycle/security paths and desktop/mobile behavior; no new UI framework.
5. **Homelab rollout:** prepare compatible deployment-helper/config handling, then
   deploy the integrated Chat change through the existing pipeline. Check the
   actual service/Tailscale path, GPU/context fit, a small synthetic receipt flow,
   outage behavior, and rollback compatibility. No automatic updates or new host
   infrastructure.

The first two tickets provide an early real-model answer path; they do not require
exposing an incomplete Chat page. Each eventual implementation ticket will include
its own tests and documentation, rather than leaving quality checks to ticket five.

### Q2 — Rollout grouping

Recommend developing and checking these increments before exposing Chat on the
homelab. Keep the existing Orders UI available during development. At rollout,
apply the small backwards-compatible deployment-helper preparation while keeping
the old environment valid; only then introduce the new Chat configuration and
integrated application release. Do not add settings ahead of a helper that accepts
them. Preserve verified SQLite backup and rollback; collect the real private
application origin during setup rather than inventing it now. Each host change
remains a deliberate operator deployment, not an unattended action from this plan.

### Read-only code findings supporting this proposal

- `app/web_queries.py` and `app/db/repository.py` provide receipt-query patterns,
  but are not unchanged tool contracts: current-order listing has a broader date
  fallback, current-order details are unbounded, and product search/history need
  dedicated bounded queries. Existing `app/web_app.py` and `app/web_ui.py` supply
  the shell and page integration points; product evidence must have a real route.
- `app/config.py` has no Ollama settings. Add only the accepted endpoint/model/origin
  and necessary limits through its existing validated Settings pattern.
- `app/migrations/001_ingestion.sql` is currently the only migration; reserve the
  next available number at implementation time rather than editing migration 001.
- `deploy/deploy-ubuntu.sh` checks the five-key environment before checkout, so the
  helper/config preparation is a rollout dependency, not a new deployment system.
- `CONTEXT.md` defines Purchase History, Purchase Date, Read Tool, Evidence,
  Conversation, and Response Attempt. No ADR is needed for this naming refinement.

The proposal above was held for operator confirmation before implementation tasks
were finalized. The Answer below records that confirmation and its Q2 amendment.

### Terminology refinement

The operator asked not to call these "receipt tools". Use **purchase history
tools** for this implementation slice, while retaining **Read Tool** as the
individual operation's canonical term. A receipt is an input document; these tools
retrieve recorded shopping facts. This is a wording change, not a new payment or
transaction ledger, schema rename, or change to the four approved tool names.
The naming refinement does not change the build order or tool behavior.

## Answer

The operator accepted Q1's build order and replaced Q2 with: "just deploy as frequent
as possible. homelab is not running anything production level yet". The resulting
plan favors frequent coherent, checked deployments rather than waiting for a fully
integrated Chat release. Brief restarts are acceptable; the existing privacy,
green-main CI, verified backup, migration and rollback safeguards remain in force.
Keep the deployed `SHOPPING_ENV=production`; no new environment or automatic Ollama
updater follows from the homelab being experimental.

The [implementation plan](../implementation-plan.md) records shared constraints,
coverage and deployment checkpoints. The five task files are:

1. [14 — Purchase history tools and evidence](14-build-purchase-history-tools.md).
2. [15 — Qwen connection and Python agent loop](15-build-qwen-agent-loop.md).
3. [16 — Saved Conversations and Response Attempts](16-build-conversation-persistence.md).
4. [17 — Chat UI, streaming and recovery](17-build-chat-ui-and-streaming.md).
5. [18 — Homelab MVP verification](18-verify-homelab-chat-mvp.md).

Deploy working checkpoints during every ticket, not just ticket 18. The helper/
configuration compatibility preparation moves into ticket 15, before its first new
host settings. Deploy that preparation with the old environment first, verify the
installed helper and rollback path, then introduce the new settings/backend. Early
tools/backend/schema increments can ship before Chat navigation exists; do not
expose an unprotected or misleading Chat surface to make a checkpoint visible.

One synthetic real-Qwen tool round trip belongs in ticket 15; normal unit/integration
and browser checks accompany each slice. Ticket 18 finishes actual service/Tailscale
and recovery checks on the accumulated increments. No model-comparison exercise,
new infrastructure, or separate evaluation-planning ticket is required.

No planning decision remains open. Wayfinder planning is complete; ticket 14 is the
next implementation task. This resolution creates planning documents only and does
not claim application work, model tests, migrations or deployments have occurred.
