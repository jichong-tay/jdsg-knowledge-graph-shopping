# Define provider selection and cloud disclosure

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex

## Question

How should a conversation select and display its fixed provider, obtain explicit cloud consent, communicate the identical bounded payload policy, record privacy-safe provider metadata, and behave when the selected provider is unavailable?

## Comments

- Subsequent MVP scope change: cloud support is deferred. This accepted design remains recorded for a later phase; fixed local endpoint/model identity and bounded current-conversation context still apply. No cloud selector, adapter, or consent UI is required for the Ollama-only MVP.

- The operator accepted the proposed provider-selection flow in conversation.

- Reopened after the process audit. The accepted flow below stands; configuration changes, renewed consent, and the scope of disclosed context still need grilling. No assignee until this ticket is selected.

## Previously accepted flow

- New conversations default to Ollama. The cloud option is available when configured.
- Selecting cloud displays: “Recent messages and retrieved shopping facts will be sent to [provider].” The operator confirms with a **Start cloud conversation** button before any conversation content is sent.
- Cloud receives the same bounded recent conversation context and structured tool results as local generation, subject to the map's existing exclusions for raw email, archive paths, credentials, and unrestricted database context.
- The conversation header shows the selected provider and model. Provider selection is fixed for that conversation; switching requires a new conversation.
- When the provider is unavailable, preserve the conversation and show an error with Retry. Never fall back automatically to another provider.
- Store the provider identifier, model, and consent timestamp with conversation metadata. Credentials remain outside conversation records.

The prototype ticket will implement this interaction for review; runtime and lifecycle tickets define the remaining technical behavior.

## Grilling round one — accepted

The operator explicitly accepted all four recommendations below. Together with the previously accepted flow, these resolve this ticket. Exact context-size budgets remain in the runtime ticket; credential provisioning and configuration validation belong to operational planning.

1. Configuration changes: recommend binding a conversation to its configured endpoint and model. If that combination is no longer configured, keep the conversation readable but require a new conversation to use the replacement. Routine credential rotation for the same destination need not create a new conversation. This concerns application configuration, not unverifiable changes behind a provider's model alias.
2. Disclosed context: recommend only the current conversation's latest complete exchanges, its bounded tool results, and the current turn's tool results, alongside application instructions and tool schemas. Do not include other conversations or automatically generated long-term summaries. Exact size limits belong to the runtime ticket.
3. Typed text: recommend sending ordinary user messages as entered, and stating this in the cloud notice. Archive/raw-email and credential exclusions govern application-supplied context; the UI must not promise automatic removal of sensitive text the operator types. No archive attachment/upload feature is planned.
4. Consent on resume: recommend that consent remains valid when reopening the same conversation with the same configured destination, model, and disclosure scope. Reconfirmation is needed before expanding the disclosure scope; provider/model replacement follows the configuration-change decision. No periodic confirmation for unchanged conversations.

## Answer

New conversations default to Ollama. The operator can explicitly choose the configured cloud option and confirm **Start cloud conversation** before any conversation content is sent. The header displays the provider and model throughout the conversation. There is no automatic provider fallback.

Each conversation is bound to its configured endpoint and model. Replacing the configured combination does not redirect an existing conversation: it remains readable, but using the replacement requires a new conversation. Credential rotation for the same destination does not require a new conversation. Application configuration identifies the model; the app does not claim to pin a vendor's internal implementation behind a mutable model alias.

Both local and cloud generation receive the current message, bounded recent complete exchanges and tool results from that conversation, current-turn tool results, application instructions, and tool definitions. Other conversations and automatic long-term summaries are excluded. Exact size limits and complete tool-call/result grouping are resolved in the runtime ticket.

Ordinary typed messages are sent as entered. The app does not promise automatic removal of sensitive text typed by the operator. The exclusions for archived emails, archive paths, credentials, and unrestricted database context apply to application-supplied context; no archive upload feature is planned.

Cloud notice copy:

> Your messages are sent as entered. Recent messages and retrieved shopping facts from this conversation will be sent to [provider] using [model]. The app does not retrieve archived emails or credentials for the model.

Consent remains valid when the same conversation is resumed with the same configured destination, model, and disclosure scope. An expanded disclosure scope requires renewed consent before sending under the expanded scope. Endpoint/model replacement instead requires a new conversation. There is no periodic reconfirmation for unchanged conversations.

Persist privacy-safe provider/model identity and consent metadata sufficient to identify the accepted disclosure scope and when it was accepted; credentials stay outside conversation records. Provider outages preserve the conversation and offer Retry against its existing selection. Configuration removal preserves read access and explains that a new conversation is needed to use a replacement.

Verification must cover local defaults, no cloud transmission before confirmation, no silent destination changes, unchanged resume without repeated prompts, renewed consent for expanded scope, current-conversation-only context, credential rotation, and unavailable providers. Runtime, prototype, lifecycle, and operational tickets own the remaining implementation details. No application code changes are part of this resolution.
