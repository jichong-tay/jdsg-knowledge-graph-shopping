# Prototype the dedicated Chat experience

Parent: ../map.md
Type: prototype
Status: resolved
Assignee: Codex
Blocked by: 02, 04

## Question

Which concrete dedicated-page interaction best communicates conversation navigation, the configured Ollama model, streamed messages, compact tool evidence, stopping, errors, empty states, and reconnect recovery within the existing Stitchyard-inspired responsive shell?

## Comments

- MVP narrowed to Ollama only. Omit provider selection and cloud consent UI; preserve the accepted conversation lifecycle. Use a design prototype for review while application implementation remains paused.
- The operator explicitly chose to reuse the existing FastHTML/Stitchyard interface after comparing existing chat UI solutions. Reuse the application shell, navigation, theme, forms, buttons, and other suitable components; design only the chat-specific message list, composer, conversation navigation, and response/tool states within that shell.
- Open WebUI, Chainlit, and React-based assistant-ui are not selected for this MVP. The [chat UI comparison](../chat-ui-options-research.md) records research context; this choice avoids adding a separate chat application or React frontend to the current design.
- Framework reuse is settled. This prototype ticket remains open until the operator reviews the concrete layout and interactions; choosing the UI stack does not complete that review or authorize application implementation.

## Prototype ready for review — 2026-09-08

- Primary source: throwaway branch `codex/chat-ui-prototype`, commit `f5d5a81`.
- Worktree: `/tmp/shopping-chat-prototype.qWAJV2/worktree`; run instructions and limitations are in `CHAT_PROTOTYPE.md` on that branch. From the worktree, run `uv run --locked python -m app.prototype_chat`.
- Local preview: <http://127.0.0.1:8015/prototype/chat?variant=A>. This is a local development preview, not a homelab deployment.
- A — Conversation library: visible history rail with receipt details on demand.
- B — Focused conversation: wider chat canvas with conversation history in a menu.
- C — Chat + receipt workspace: receipt evidence beside the answer on desktop, in a dialog on smaller screens.
- The bottom switcher changes variants; the top selector demonstrates empty, responding, stopped, unavailable, and reconnecting states. Send, Stop/Retry, receipt details, conversation navigation, Rename, and Delete are interactive simulations.
- Reuses the existing FastHTML/Stitchyard document shell, navigation, assets, and theme. No production application routes, database, raw emails, or Ollama connection are changed. All receipt data is synthetic and conversation state is in browser memory, reset by reload/variant changes. Durable persistence, actual cancellation/reconnect, complete conversation history, and model behavior are not implemented or validated here.
- Manual browser review covered desktop A/B/C, mobile A/C at 390 × 844, light/dark themes, receipt/conversation dialogs, rename, new/send/stop/retry, delete during simulated response, unavailable/reconnect states, and variant URL cycling.
- Recommendation for review: A. Visible history makes saved conversations discoverable; on-demand receipt details leave space for the conversation. This is not yet an accepted decision.
- Operator review completed below; application implementation remains paused.

## Answer

The operator approved **A — Conversation library** on 2026-09-08: “A look good”.

- Use the dedicated Chat page within the existing FastHTML/Stitchyard shell, with a visible conversation history rail on desktop and a Conversations control on mobile.
- Keep receipt evidence compact in the answer and open receipt details on demand, rather than adopting C's permanent evidence panel.
- Carry forward A's composer, compact tool activity, and response-state presentation, subject to the accepted read-tool and conversation-lifecycle contracts. No provider picker or cloud flow is added to this Ollama-only MVP.
- Preserve the reviewed variants as the primary design source on `codex/chat-ui-prototype` at `f5d5a81`. The prototype is not production-ready code and does not validate durable storage or real model/transport behavior.
- This resolves the layout question only. Rewrite the selected design during the later implementation slices after Wayfinder planning is complete; do not merge the throwaway route or switcher into the application now.
