# Shopping Assistant MVP Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement one ticket
> at a time with review checkpoints. Keep changes small and explain their inputs,
> state changes, failures, and checks. Do not start implementation merely by reading
> this plan; pick up the user-requested task. Subagent execution is optional, not a
> new prerequisite.

**Goal:** Deliver a private, tool-grounded Shopping Assistant on the existing homelab.

**Architecture:** One explicit Python loop connects Qwen3.5 9B to four bounded
purchase history Read Tools. SQLite owns facts and durable Conversations; FastHTML
and the existing Stitchyard shell provide the Chat UI and protected WebSocket.

**Tech Stack:** Python 3.14, uv 0.12.3, SQLite, Pydantic, FastHTML/Stitchyard, native
Ollama, systemd, and the existing Tailscale Serve/deployment pipeline.

**Spec:** [Map](map.md), [planning resolution](issues/09-plan-implementation-slices.md),
and the final Answer sections of tickets [02](issues/02-define-read-tools.md),
[03](issues/03-define-cloud-disclosure.md), [04](issues/04-define-conversation-lifecycle.md),
[05](issues/05-prototype-chat-experience.md), [06](issues/06-define-agent-runtime.md),
[07](issues/07-define-streaming-protocol.md), [11](issues/11-define-receipt-date-extraction.md),
and [12](issues/12-define-provider-operations.md). Later accepted decisions supersede
historical proposals. Read the repository AGENTS.md, README, MVP plan, deployment
guide, and glossary before implementation.

## Global constraints

- Keep the learning-friendly implementation within the existing app. No agent
  framework, broker, separate UI application, cloud provider, or model comparison.
- Select installed `qwen3.5:9b`, native request `think: false`, five-minute keep-alive;
  no automatic Ollama/model updates, downloads, failover, or host-process management.
- One active Response Attempt globally, no queue; one loaded model/parallel request.
  Deadline 180 seconds including loading; at most 4 model requests, 8 tool proposals,
  one invalid-batch correction, 768 generated tokens per model request, 5 seconds
  local cleanup. Invalid/repeated proposals consume the same budget.
- 8,192 total context: 6,912 input + 768 output + 512 headroom. The accepted 4,096
  fallback uses 2,816 input. Validate model-aware accounting; do not replace it with
  a character heuristic. User messages max 4,000 characters. Tool envelopes max
  4 KiB UTF-8, containing whole rows and honest pagination, not cut JSON.
- Preserve all current-order items, including `placed`; historical revisions do not
  duplicate purchases. Purchase Date is `delivery_at`, not a source-date fallback.
  Money stays integer cents with currency. Missing facts remain missing.
- Search defaults/max 10/20, history 20/50, recent orders 10/25, order items 50/page.
  Ask about ambiguous products and refuse unavailable analytics. Four tools only:
  `search_products`, `get_product_history`, `list_recent_orders`, `get_order`.
- Evidence uses application-generated current order/product links, never model URLs
  or new evidence snapshots. Reference validity is not proof of factual prose.
- Keep exact raw archives and append-only shopping facts unchanged. No private
  samples in fixtures, model research, logs, Git, or documentation. Use synthetic
  development databases for model checks, never seed fake purchases into homelab data.
- Only `shopping migrate` changes schema. Add the next numbered packaged migration;
  never edit released migration 001. Short-lived same-thread SQLite connections,
  short transactions, no database connection held over model/socket waits.
- Keep 0700 private directories/0600 raw and database files. Keep production SQLite
  safety: 3.51.3+, 3.50.7+, or 3.44.6 within that backport line. Homelab deployments
  still use `SHOPPING_ENV=production`; the operator's experimental use is not a new
  environment or permission to disable safeguards.
- App and Ollama remain loopback-only, reached privately through Tailscale Serve.
  No accounts, Funnel, public listener, or weakening of Origin/session/CSRF checks.
- Ticket 07 owns exact wire limits: 64 KiB frames, 10 sockets, outbound max 16
  updates/256 KiB, 60 commands/minute/session with burst 10; 5-second initialization,
  initial 12-hour token lifetime, ~250 ms durable checkpoints, 20-second heartbeat,
  ~40-second stale detection, reconnect 1/2/4/8/16/30 seconds with jitter for ~2 minutes.
  No automatic mutation replay or token-event replay store.
- Preserve backup, green-main CI, migration, health, and database-aware rollback on
  every deployment. Core readiness stays independent of model availability.

## Sequence and ownership

| Ticket | Independently testable result | Main new files | Deployment checkpoint |
| --- | --- | --- | --- |
| [14](issues/14-build-purchase-history-tools.md) | Bounded purchase history and working evidence pages | `app/assistant/tools.py`, `app/assistant/queries.py` | Ship tools and the product evidence page; existing Orders continue working. |
| [15](issues/15-build-qwen-agent-loop.md) | Real Qwen tool round trip plus fake-provider error checks | `app/assistant/ollama.py`, `runtime.py`, `context.py` | Ship compatible helper preparation, then configured backend; no unfinished Chat route. |
| [16](issues/16-build-conversation-persistence.md) | Durable lifecycle and command recovery | `app/assistant/conversations.py`, next chat migration | Ship the additive schema and repository through the existing migration/backup path. |
| [17](issues/17-build-chat-ui-and-streaming.md) | Usable approved Chat UI and protected live recovery | `app/assistant/web.py`, `ui.py`, `app/static/chat.js` | Expose Chat as soon as the integrated slice passes its checks. |
| [18](issues/18-verify-homelab-chat-mvp.md) | Complete private application flow and operations verified | Test/runbook additions only as needed | Verify the already-deployed increments; deploy any small corrections promptly. |

These are responsibility boundaries, not a request to pre-create empty modules.
Keep transport events and persistence records small; do not turn their interfaces
into a generic plugin framework. Each task supplies the tests and documentation for
its own behavior, not a handoff of unfinished quality work to ticket 18.

## Frequent deployment, not a final-release gate

Deploy every coherent working increment after review and green-main CI, including
smaller checkpoints within a ticket when useful. The homelab is experimental and
brief restarts are acceptable; do not hold everything until all five tickets finish.
Use the existing operator-driven pipeline, not a new automatic scheduler or runner.

The current installed helper validates five environment keys before checkout.
Ticket 15 therefore first ships a compatible helper/bootstrap-validator change
while retaining the old environment. After that successful deployment has installed
the new helper, add the accepted optional Chat settings and deploy the backend.
Test old-config/new-code and rollback compatibility before changing the host's env.
Do not roll back to an incompatible helper with expanded config. No new release
directory architecture or feature-flag platform is needed.

Tickets 14–16 can be deployed without a Chat navigation item. Ticket 17 exposes the
page only with its required command/privacy safeguards and truthful response states.
A deployed intermediate capability is not a declaration that the whole MVP works.

## Check and handoff loop for each ticket

- [ ] Write a focused failing behavior test using the existing synthetic fixtures or
  a fake provider; verify the intended failure before implementation.
- [ ] Implement the smallest change, run the ticket's focused tests, and review the
  diff against its acceptance requirements and the linked final contracts.
- [ ] Run the standard repository checks below; update README and relevant operation
  or target-architecture documentation with implemented versus planned behavior.
- [ ] Verify the built wheel contains migration 001 and all new migrations and can
  execute `shopping migrate` in an isolated environment, following existing CI.
- [ ] Make a reviewable commit containing only the task's work; do not sweep in
  unrelated staged edits. Follow the existing GitHub CI/deployment workflow.
- [ ] Deploy the working increment when that workflow and access are available.
  Record the deployed SHA and the scoped smoke-check outcome; if access is blocked,
  report implementation complete/deployment pending rather than claiming deployment.

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest -q
git ls-files -co --exclude-standard -z | xargs -0 uv run --locked detect-secrets-hook --baseline .secrets.baseline
```

Public CI remains read-only, secret-free, and GitHub-hosted. Real Ollama checks are
explicit operator/local runs against synthetic data, not required homelab access
from public CI. Keep recorded evidence content-free: version/digest, checks, timing,
GPU placement, safe failure categories; no private questions or returned facts.

## Coverage and completion

Ticket 14 owns exact facts, date convention, bounded read access, and evidence
destinations. Ticket 15 owns model protocol, context, tool validation, budgets,
grounding, failure and local cancellation. Ticket 16 owns durable lifecycle,
idempotency, restart recovery and state transitions. Ticket 17 owns application
wiring, security, streaming, browser recovery, and visual behavior. Ticket 18 owns
actual service/Tailscale integration and operational verification, not deferred unit
tests or a model tournament. The scoped checklist in ticket 09 remains the MVP bar.

Planning is complete when these tasks are recorded. Application completion requires
their implementation and verification; nothing in this document reports a model
test, migration, deployment, or completed Chat feature.
