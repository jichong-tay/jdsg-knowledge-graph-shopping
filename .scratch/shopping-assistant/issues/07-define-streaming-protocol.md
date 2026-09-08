# Define streaming, cancellation, and reconnect semantics

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: 01, 04, 06

## Question

What server and browser protocol should govern WebSocket protection, message identifiers, streamed text and tool events, Stop behavior, continued generation across disconnects, durable completion, duplicate submission, and reconnect resumption?

## Comments

- [Define the durable conversation lifecycle](04-define-conversation-lifecycle.md) now fixes the observable policy: browser disconnect does not cancel generation, explicit Stop does, retries create fresh response attempts, and confirmed active deletion must prevent late writes or resurrection. The transport design must implement these choices rather than reopen them. The protocol research's suggested disconnect cancellation is superseded by this operator-approved lifecycle policy.

## Grilling round one — accepted

The operator explicitly accepted all five recommendations below.

The accepted global single-attempt limit, work/output/context limits, explicit Retry,
no queue, continued generation on browser disconnect, and cleanup fault handling
from tickets 04/06 remain fixed. This round proposes observable delivery guarantees,
not production code.

1. **Uncertain send acknowledgement:** recommend a browser-generated submission ID. Save the accepted message and Response Attempt together before acknowledging or starting generation. If acknowledgement is lost, a deliberate resend using that same ID returns the existing accepted result, never starts another attempt; changed content under the same ID is rejected. An unknown/unaccepted ID is still subject to current validation and busy limits. Do not automatically replay pending submissions on reconnect: check their status first and leave unaccepted drafts for the operator to send. Explicit Retry is a distinct command/new attempt, not a duplicate send.
2. **Durable streamed output:** recommend batching text into short checkpoints (initially about 250 ms while text arrives, with immediate terminal flushes), committing each checkpoint before broadcasting it. The browser sees saved text rather than speculative unsaved tokens. Tool outcomes and terminal state are also durable before their corresponding broadcasts. No transaction is held across model waits. On persistence failure, stop the attempt safely and show a connection/runtime error; do not claim a terminal result was saved if it was not. This prioritizes recoverability over token-by-token immediacy.
3. **Reconnect:** recommend loading the current saved conversation/attempt snapshot and replacing the visible attempt with that authoritative text/status, then following newer updates. Use attempt IDs and monotonic update versions to discard duplicate/stale updates and detect gaps; a gap requests another snapshot instead of guessing missing text. Do not rerun the question or replay the entire token history. Restore the selected conversation across page reloads; keep older conversation history paginated. Initial subscription and snapshot handoff must not lose concurrent updates.
4. **Multiple tabs/devices:** recommend showing the same active attempt and status in every tab viewing that Conversation. Any of these trusted household tabs can Stop it; rename/deletion updates propagate. All commands identify their Conversation and, where applicable, the exact Response Attempt so an old tab cannot stop a newer retry. A disconnected tab visibly shows stale/reconnecting state and does not pretend a command succeeded offline.
5. **Stop versus completion:** recommend the first valid terminal transition committed by the server wins. If completion commits first, Stop returns already finished; if Stop is accepted first, later completion cannot overwrite it. While cancellation is in progress, show Stopping rather than Stopped. Confirmed deletion first fences off new/late writes, then follows the accepted local-cleanup policy before removing the Conversation; do not show deletion success early. Missing/deleted records in other tabs show a clear gone state and never get recreated by stale updates or duplicate commands. Precise storage coordination belongs to the implementation slice.

## Existing implementation findings

Read-only inspection found HTTP GET pages/HTMX fragments, a protected FastHTML
session-key file, and the loopback guard. There is no production Chat/WebSocket
route, application session authorization, origin allowlist, or CSRF protection yet.
Session-cookie infrastructure alone is not access control. The selected architecture
already uses WebSockets and trusts household devices admitted by Tailscale; no
per-person account/ownership feature is in scope.

## Grilling round two — accepted

The operator accepted Q6 with the clarification that the application is locally
hosted and remotely reachable only through the private Tailscale path, and accepted
the Q7–Q9 recommendations. They explicitly require a learning-friendly MVP without
over-engineering.

6. **Connection and command protection:** recommend retaining Tailscale as the household access boundary, without adding a login system. Accept production browser connections only from the explicitly configured application HTTPS origin/host, using secure WebSockets externally and the existing loopback upstream. Reject missing/null/unlisted Origin values; never derive the allowlist from an arbitrary forwarded host or use wildcard matching. Explicit loopback development origins are separate. Add an HttpOnly, SameSite session cookie (Secure in production) and a short-lived session-bound page token, validated in the initial WebSocket message before any subscription/data/commands. Keep tokens out of URLs and logs; close uninitialized sockets after 5 seconds. Use a configurable initial 12-hour token lifetime, enforce expiry for live connections, and reacquire page/session context on reconnect rather than weakening checks. Protect any HTTP mutation with same-origin/CSRF checks as well; GET is non-mutating. These defenses prevent cross-site misuse of the browser, not access by another device already allowed through Tailscale. Every command still validates its schema, record existence, and target state.
7. **Bounded wire protocol and slow tabs:** recommend a versioned JSON command/event envelope carrying a command ID and relevant Conversation/Response Attempt IDs; saved updates include a monotonic version. Accept only explicit commands (initialize/subscribe/snapshot/status, submit, retry, stop, rename, confirmed delete). Deduplicate accepted mutations by command ID and content, including Retry, so retransmission cannot create another attempt; reject conflicting reuse. Deleted or missing Conversations cannot be recreated by old commands, and new-draft creation requires a fresh explicit creation/submission context. Start with 64 KiB maximum encoded messages, 10 application-wide live sockets, and per-socket outbound buffers capped at 16 updates or 256 KiB, whichever is reached first. Page large snapshots/history rather than emit unbounded frames. Disconnect only a slow subscriber and recover it from a snapshot; never stall model execution or hold a SQLite transaction waiting for that tab. Start with 60 client application commands/minute per session and a burst allowance of 10; protocol heartbeat traffic is separate. Oversize/malformed/flooding clients receive safe rejection or closure without payload logging. Exact DTO field names and deduplication storage layout belong to implementation.
8. **Reconnect attempts and restart:** recommend an automatic reconnect backoff of roughly 1, 2, 4, 8, 16, then 30 seconds with jitter, stopping after about 2 minutes to offer a manual Reconnect button. Pause attempts while the browser reports offline; never resend generation/mutation commands automatically. After reconnection, query pending command status and obtain a fresh authoritative snapshot. Authentication/origin/protocol errors require refresh/configuration correction, not endless network retry. Use a heartbeat around every 20 seconds and consider an unanswered connection stale after about 40 seconds, without cancelling generation. A server restart marks previously active attempts interrupted before admitting new work and never reruns their questions; explicit Retry follows ticket 04. New user action can initiate another bounded reconnect cycle.
9. **Rendered content and diagnostics:** recommend escaped model/user/tool text, with application-owned formatting for evidence and structured facts; no raw model HTML, embedded remote images, or arbitrary model-generated clickable URLs. Display compact tool status and validated local receipt/product links, not internal prompts or private reasoning. Store the bounded conversation/tool records under the accepted private retention policy, but log only operational event types, error codes, timing, and non-content correlation identifiers—not messages, receipts, tool payloads, session IDs, or tokens. Surface safe connection/runtime failures without exception internals.

The security mechanisms follow the relevant controls in the
[OWASP WebSocket Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html).
The numerical limits/backoff/token lifetime above are accepted starting defaults,
not externally prescribed values or measured host limits. Application implementation
is still paused.

## Answer

Both grilling rounds are accepted, with private-only access and implementation
simplicity as explicit constraints:

- **Private access:** reuse Tailscale Serve and existing tailnet access policy, with the application and Ollama bound to loopback. No public application endpoint, Tailscale Funnel, router port forwarding, or new publicly listening service. Tailscale is the remote-access boundary; origin/session/CSRF checks protect against cross-site browser commands without introducing user accounts. This is the desired deployment boundary, not a claim that host settings were independently audited.
- **Reliable commands:** save accepted submissions before acknowledgement/generation. Use command IDs to deduplicate accepted mutations, including explicit Retry; validate target Conversation/Response Attempt and reject conflicting or stale commands. Do not silently queue or automatically replay mutations on reconnect.
- **Saved streaming:** checkpoint text about every 250 ms while it arrives and persist before broadcast, with immediate terminal flushes. Reconnect restores a versioned saved snapshot and follows newer updates, rather than replaying tokens or rerunning generation. Tabs share the same saved state. Keep SQLite operations short and outside external waits.
- **Stop/delete races:** serialize valid state transitions; accepted Stop prevents later completion from winning, while already committed completion remains finished. Show Stopping during cleanup. Confirmed deletion blocks new/late writes before cleanup and removal, with no stale-message resurrection or premature success. Preserve the accepted five-second local cleanup and failure policy.
- **Bounded recovery and rendering:** apply the accepted message/socket/buffer limits, disconnect slow tabs rather than blocking generation, and reconnect with backoff for about two minutes before manual recovery. Restarts leave interrupted attempts, never automatic generation. Escape untrusted text, render only validated application-owned evidence links, and keep logs content-free.
- **Keep the code understandable:** implement these rules with the existing FastHTML application, SQLite, a small WebSocket handler, ordinary Python functions, and the single active async response task. Use existing session/validation facilities where suitable. A small JSON schema and a few bounds do not require a reusable messaging framework. No broker, distributed locks, event-sourcing/token-replay store, authentication service, generic RPC layer, or speculative provider/plugin architecture. Persist only what is needed for conversations, attempts, deduplication, and recovery. Explain the state transitions and reasons for safeguards in the implementation handoff; do not create extra features from this checklist.

No additional glossary term or account-ownership model is introduced. Ticket 09
turns this contract into small, testable implementation slices with the merged
acceptance checklist. Ticket 12 records the exact deployed origin and service
configuration after ticket 13's read-only host inventory. No application code,
network configuration, migrations, or deployment were changed by this resolution.
