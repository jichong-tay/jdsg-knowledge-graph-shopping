# Build the Chat UI, streaming and recovery

Parent: ../map.md
Type: task
Status: claimed
Blocked by: 16

## Goal and contracts

Ship a usable dedicated Chat page using approved prototype A and the actual saved
Python/Qwen loop. Read the [shared plan](../implementation-plan.md) and final
tickets [03](03-define-cloud-disclosure.md), [04](04-define-conversation-lifecycle.md),
[05](05-prototype-chat-experience.md), [06](06-define-agent-runtime.md), and
[07](07-define-streaming-protocol.md). Their accepted security/lifecycle requirements
apply to the first exposed Chat surface, not a later hardening project.

## Files and boundaries

- Create `app/assistant/web.py` for chat HTTP/WebSocket handlers and active-attempt
  coordination, `app/assistant/ui.py` for compositions, and `app/static/chat.js`
  for the bounded browser protocol and page interaction.
- Modify `app/web_app.py` to register routes/startup/shutdown, `app/web_ui.py` for
  navigation/assets, and `app/static/shopping.css` for the reused chat layout/theme.
  Use existing asset delivery; do not add a frontend build system or external CDN.
- Consume `conversations.py`, `runtime.py`, and ticket 14 evidence destinations;
  one active async task and bounded per-subscriber queues suffice.
- Create `tests/test_chat_web.py` and `tests/test_chat_streaming.py`; extend
  `tests/test_web.py`. Update README with actual usage and `docs/DEPLOYMENT.md` with
  the real configuration process and separate assistant-availability behavior.

## Inputs, outputs, and state

Browser commands identify the Conversation, exact Response Attempt, and command ID
where applicable. Handlers validate access/schema/state, use the repository to
accept mutations, then schedule the loop. Saved versioned updates—not speculative
tokens—feed bounded subscriptions. Reconnection retrieves a paginated authoritative
snapshot and pending command status, never replays generation.

## Implementation steps and checks

- [x] Wire startup recovery before admission and orderly bounded shutdown. Admit
  one attempt globally; busy preserves the draft. Fix the snapshot/subscription
  handoff so a concurrent checkpoint cannot be missed.
- [x] Implement production HTTPS-origin/host allowlisting and explicit development
  loopback origins, secure HttpOnly/SameSite session cookie, session-bound page token,
  initial-message authentication, and live expiry. Reject missing/null/unlisted
  Origin; do not trust arbitrary forwarded hosts. Tokens stay out of URLs/logs.
  HTTP mutations, if any, get equivalent same-origin/CSRF protection; GET is read-only.
- [x] Define only ticket 07's commands and validate their bounded envelopes. Test
  expired/uninitialized sockets, oversize/malformed frames, floods, stale targets,
  deduplication, rejected conflicting IDs, and unauthorized snapshot access.
- [x] Consume runtime updates, checkpoint approximately every 250 ms, flush terminal
  state immediately, and broadcast only after commit. Test persistence failure,
  slow subscribers, socket/queue limits, version gaps, disconnect continuation,
  and reconciliation without duplicate generation. Never hold a DB transaction over
  socket writes or stop the global attempt because one subscriber is slow.
- [x] Connect Stop/Retry/delete to exact saved state. Test both orderings of races,
  Stopping display during cleanup, delete failure, stale tabs, no resurrection,
  all-tab rename/deletion updates, and explicit Retry after server restart.
- [x] Rebuild A's desktop history rail/mobile Conversations control, composer,
  local title/rename, history pagination, pending/incomplete/error states, and
  on-demand evidence details in the existing shell. No mock responses, variant
  switcher, cloud picker, reasoning trace, or raw model HTML. Preserve typed drafts.
- [x] Implement bounded reconnect/backoff/heartbeat from ticket 07, manual recovery
  after exhaustion, offline pause, page-token refresh, and honest stale/error state.
  Do not automatically resend mutations, even when their acknowledgement was lost.
- [ ] Test escaped user/model/tool text, only application-owned evidence links, no
  remote resources, content-free diagnostics, and an Ollama outage leaving Orders
  and saved Conversations readable with core health unchanged.
- [ ] Verify desktop/mobile, keyboard/focus behavior, light/dark themes and the full
  send → tool → evidence answer → reload flow with synthetic data using the repository
  browser/UI skills. Use fake-provider integration tests for races; run the actual
  Qwen path on the homelab after the protected slice deploys.
- [ ] Review/run shared checks and deploy working protected UI increments promptly;
  do not wait for ticket 18 merely to begin homelab use.

```bash
uv run pytest -q tests/test_chat_web.py tests/test_chat_streaming.py tests/test_web.py tests/test_conversations.py tests/test_assistant_runtime.py
```

## Deployable result

The private Tailscale Chat page is usable with Qwen, saved Conversations, Stop/Retry,
reconnect and evidence. Record actual checks separately from untested behavior.
Ticket 18 verifies the full host/service/recovery flow, not deferred command security.

## Local implementation

Continuing locally by operator request. Ticket 16 provides the saved-state
operations; host deployment remains pending. Tests use the specified HTTP/WebSocket
and saved-state boundaries, with synthetic data and fake-provider integration.


## Implementation result — 8 September 2026

Implemented locally with functions in `app/assistant/web.py` and existing runtime,
conversation repository, shell, theme, and evidence destinations. No new runtime
classes, dependencies, frontend build system, or migrations were introduced.
The page protects admission, streams committed updates, coordinates one response,
and reconciles uncertain commands without replay. Review fixes cover shutdown
admission, browser Back restoration, and newer drafts before the first saved update.

Validation: 272 tests passed, one opt-in real-model test skipped. Ruff formatting,
lint, Pyright, secret scanning, and both code-review axes passed. The wheel installs
with locked production dependencies, includes migrations 001/002 and Chat assets,
and runs `shopping migrate` to schema 2 outside the checkout; dependency checks pass.

Browser checks used synthetic purchases and the actual runtime with a fake provider:
send → tool → evidence answer → drawer → reload, desktop/mobile, light/dark,
keyboard dialog dismissal, escaped titles, draft preservation, and Back reconnect.
`tests/browser/chat_draft_recovery.js` also passes both received/lost acknowledgement
cases before the first update, preserving newer drafts without replaying mutations.
Transport tests cover slow subscribers, token expiry, conflicting commands,
multi-tab changes, persistence failure, and shutdown/restart recovery.

Status remains claimed because local implementation was requested. No homelab
changes were made; deployment and real Qwen checks through the protected Tailscale
page remain pending, including service-context outage and rollback verification.
