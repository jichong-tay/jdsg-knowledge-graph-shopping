# Working Shopping Assistant

Label: wayfinder:map

## Destination

Reach an Ollama-only chatbot MVP on the existing homelab deployment: open the dedicated Chat page through the already working Tailscale access, ask about receipt items and purchase history, and receive answers backed by the four SQLite read tools and order/product evidence. Retain the agreed durable conversations, streaming, Stop, and reconnect behavior; verify the homelab model, application integration, and service restart behavior using the existing deployment pipeline.

## Notes

- Current phase: The original Wayfinder planning round is complete and tickets 14–17 have local implementations recorded in their issue files. The 20 September Chat investigation has reopened remediation decisions; the operator currently authorizes ticket preparation only, without fixes. Ticket 18 remains the host verification checkpoint; deployment and host verification are still pending. Treat this map as planning context and implementation evidence, not proof of deployment.
- Use one application-owned Python agent loop and local Ollama for this MVP. Cloud support and orchestration-library comparisons are deferred to a later phase.
- Learning-friendly MVP: prefer small Python functions and explicit state transitions in the existing application; no general-purpose messaging platform, extra infrastructure, or speculative abstractions. Retain the accepted data/privacy/recovery safeguards.
- Host privately on loopback with remote access only through existing Tailscale Serve; no public app endpoint, Funnel, or port forwarding. Browser origin/session protections do not introduce user accounts.
- The operator reports that the deployment pipeline and Tailscale access are already working and the hosted page is reachable. Reuse this baseline; do not plan another application bootstrap or Tailscale setup. Ticket 13 confirms the installed Ollama/GPU inventory and app-account loopback access through operator-run checks; actual inference and end-to-end chatbot operation still need verification.
- Every session should consult `grilling` and `domain-modeling`; use `research` for external API facts, `prototype` for interaction decisions, and the repository's testing, review, and browser-verification skills during implementation.
- SQLite remains authoritative. The model never executes SQL or arbitrary Python, and deterministic facts are returned only through bounded application-owned tools.
- The first release is read-only and covers existing products, orders, purchase history, quantities, and prices. It must refuse unavailable analytics rather than infer them.
- Raw private samples stay local; planning records contain only structural findings.
- Chat is a dedicated sidebar destination, not a global floating widget.
- Reuse the existing FastHTML/Stitchyard shell and components for Chat, using approved prototype A: desktop conversation history rail, mobile Conversations control, and receipt details on demand.
- Conversations use the configured homelab Ollama endpoint and model; existing conversations are not silently redirected when configuration changes. No cloud provider selector or cloud credentials are needed for this MVP.
- Ollama receives bounded context from the current conversation and structured tool results. Application-supplied context excludes raw emails, archive paths, credentials, and unrestricted database context. Ordinary typed messages are sent as entered.
- Conversations are durable and support create, list, resume, rename, and confirmed deletion.
- Responses stream with visible working state, compact tool activity, a Stop control, and reconnect recovery.
- Acceptance is a short checklist within ticket 09, using fixed synthetic examples covering facts/evidence, safe tool boundaries, lifecycle recovery, and homelab runtime limits; no separate evaluation-planning exercise.
- Deploy coherent checked increments frequently, including useful checkpoints within tickets. The homelab is experimental; brief restarts are acceptable. Do not wait for the entire MVP or ticket 18. Preserve existing CI, private access, backups, migrations and rollback; no automated Ollama/model updates or new deployment system.

## Plans and research

- [Chat MVP implementation plan](plans/chat-mvp.md) — implementation slices and host acceptance checks.
- [Source layout plan](plans/source-layout.md) — completed package and planning-folder reorganization, with verification results.
- [Local model selection](research/local-model-selection.md) — dated research background for the model choice.
- [Chat UI options](research/chat-ui-options.md) — dated research background for the interface choice.
- [Chat investigation handoff](research/chat-investigation-handoff.md) — recorded lifecycle and answer-quality findings, synthetic probes, and evidence limits; read before the remediation proposal.
- [Chat reliability and useful purchase answers — Implementation Plan](plans/chat-reliability-and-answer-quality.md) — unaccepted proposal that predates the broader lifecycle review; its fifth Read Tool and implementation remain pending decisions.

## Decisions so far

<!-- Resolved child tickets are indexed here. -->

- [Compare Ollama and OpenAI-compatible model protocols](issues/01-compare-model-protocols.md): Research completed; separate provider adapters can normalize streaming and tool calls, with optional usage and explicit failure/cancellation outcomes.

- [Define receipt-date extraction](issues/11-define-receipt-date-extraction.md): Use the already extracted delivery date as Purchase date by operator convention; no separate receipt-date extractor is required.

- [Define the read-tool and evidence contracts](issues/02-define-read-tools.md): Four bounded read tools include all current receipt items, use delivery date as Purchase date, ask about ambiguous products, and cite ordinary current records.

- [Define provider selection and cloud disclosure](issues/03-define-cloud-disclosure.md): Retain fixed endpoint/model identity and bounded current-conversation context; the previously agreed cloud flow is deferred from this MVP.

- [Define the durable conversation lifecycle](issues/04-define-conversation-lifecycle.md): Save on first message, retain until deletion, allow one active response per conversation, recover across disconnects, and preserve incomplete attempts on explicit retry.

- [Prototype the dedicated Chat experience](issues/05-prototype-chat-experience.md): Operator approved A — Conversation library, with visible desktop history and on-demand receipt details; the throwaway prototype is preserved separately and the local implementation is recorded in ticket 17.

- [Define the provider-neutral agent runtime](issues/06-define-agent-runtime.md): Accepted a single active Python/Ollama loop with a 180-second deadline, 4 model requests, 8 tool proposals, bounded 8K context/results, fresh evidence, one validation correction, and explicit failure/cleanup handling; hardware validation remains pending.

- [Define streaming, cancellation, and reconnect semantics](issues/07-define-streaming-protocol.md): Accepted deduplicated commands, saved-before-display streaming, snapshot reconnect, explicit Stop/delete race handling, and bounded private-Tailscale browser connections; implement simply within the existing app.

- [Define the assistant evaluation bar](issues/08-define-evaluation-bar.md): Merged into ticket 09 as a short implementation acceptance checklist; standalone planning is skipped, not verification.

- [Check homelab Ollama readiness](issues/13-check-homelab-ollama-readiness.md): Operator-run inventory confirms Ubuntu 24.04.4, RTX 3060 12 GB, existing Ollama 0.30.10 and models, active services, and app-account access to loopback Ollama; reuse the installation and test inference during implementation acceptance.

- [Define provider configuration and operational checks](issues/12-define-provider-operations.md): Select installed `qwen3.5:9b` with thinking disabled as the MVP default; no prerequisite model comparison. Verify it during normal implementation acceptance and revisit only for a concrete problem. Reuse independent services, on-demand loading/five-minute keep-alive, separate assistant availability, and manual-only server/model updates. No automatic updater is in scope.

- [Plan implementation and rollout slices](issues/09-plan-implementation-slices.md): Accepted tools → Qwen loop → persistence → Chat UI/recovery → final host verification, with frequent incremental deployments. Helper/config compatibility is prepared early in ticket 15; ticket 18 is verification, not the first deployment gate.

## Implementation queue

The [Chat MVP implementation plan](plans/chat-mvp.md) contains shared constraints,
coverage and release checkpoints. Each child task supplies file boundaries and checks.

1. [14 — Build purchase history tools and evidence](issues/14-build-purchase-history-tools.md) — implemented locally; evidence pages and bounded tools are recorded in the ticket.
2. [15 — Build the Qwen connection and Python agent loop](issues/15-build-qwen-agent-loop.md) — implemented locally; model/host verification remains pending.
3. [16 — Build saved Conversations and Response Attempts](issues/16-build-conversation-persistence.md) — implemented locally; migration/runtime verification remains pending.
4. [17 — Build the Chat UI, streaming and recovery](issues/17-build-chat-ui-and-streaming.md) — implemented locally; protected UI deployment verification remains pending.
5. [18 — Verify the homelab Shopping Assistant MVP](issues/18-verify-homelab-chat-mvp.md) — current verification checkpoint; do not claim completion until host checks pass.

Remediation planning is open again following the Chat investigation; find the
unclaimed decision ticket through the child issues' `Type:` and `Status:` fields.
The accepted four-Read-Tool scope remains unchanged. Actual model behavior and host
checks remain evidence to collect, not completed by resolving design tickets.

## Out of scope

- Cloud/OpenAI-compatible provider support and cloud consent UI for this MVP; preserve the agreed design for a later phase.
- [Explore agent orchestration libraries](issues/10-explore-agent-orchestration-libraries.md): Deferred to a later phase by the operator so this MVP focuses on the small Python loop and Ollama. Closed as out of scope, not completed research.
- Rebuilding the already working deployment pipeline, re-bootstrapping the application host, or setting up Tailscale again.

- Shopping-list or other write tools in the first release.
- Replenishment predictions, co-purchase analytics, graph traversal, or other not-yet-implemented analytical facts.
- Multiple named users, authentication, or per-user conversation ownership.
- A floating assistant available on every screen.
- Automatic failover from Ollama to a cloud provider.
- Automatically retrieving raw archived email content for any model or giving a model direct database access.
- Telegram or other chat surfaces outside the FastHTML application.
