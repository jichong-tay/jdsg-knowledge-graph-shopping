# Define the durable conversation lifecycle

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex

## Question

What are the precise create, title, resume, ordering, retention, deletion, interrupted-turn, and reconnect semantics for durable single-operator Conversations and their tool audit records?

## Comments

## Grilling round one — accepted

The operator explicitly accepted all six recommendations below. Previously agreed create/list/resume/rename/confirmed-delete support, fixed provider selection, bounded model context, and no automatic provider fallback remain settled. The dependent retry and active-deletion choices were subsequently accepted in round two.

1. Creation and naming: keep an empty new conversation as a draft until its first message is submitted. Save that message before generation. Derive a short initial title locally from its text, allow manual rename, and list conversations by most recent message activity. Cloud confirmation is still required before sending any conversation content externally.
2. Retention: retain conversation messages and bounded tool activity/results locally until the operator deletes the conversation. Reopening loads saved history; only bounded recent complete exchanges go back to the model. Viewing older history is paginated.
3. Concurrent submissions: permit one active assistant response per conversation, including across browser tabs. Show the active response and require it to finish or be stopped before accepting another message; do not silently queue messages.
4. Interruptions: let generation continue within its existing deadline if a browser briefly disconnects, so reconnect can recover its current state. Explicit Stop cancels. A server restart or failed generation retains available partial text marked incomplete and never automatically resubmits the question. Precise transport and persistence mechanics belong to the streaming ticket.
5. Changes to earlier messages: keep submitted messages unchanged in the first release; corrections are new messages. No editing or branching earlier exchanges. Explicit retry after failure is addressed in the next round if the interruption policy is accepted.
6. Deletion: after confirmation, delete the conversation, its messages, and its tool records from the active database, while preserving shopping records and archived emails. No trash/undo feature in the first release. Existing backups follow their retention policy; conversation deletion does not claim to erase backup copies or provider-held data. Deletion during an active response will be settled after the concurrency/interruption choices.

## Grilling round two — accepted

The operator explicitly accepted both recommendations below. No lifecycle decision remains unanswered; runtime limits and transport mechanics remain in their own tickets.

7. Retry: offer explicit Retry for the latest failed, stopped, or interrupted response, provided no later user message has been submitted. Keep the original user message once and retain previous partial attempts as incomplete; create a new response attempt with the same provider/model and fresh tool reads. Do not resume execution from halfway through the failed attempt. Earlier corrections remain new messages. Only completed exchanges and the current question enter the next attempt's bounded model context, not failed assistant text or orphaned tool results.
8. Active deletion: the existing deletion confirmation should say it also stops the active response. On confirmation, stop generation and remove the conversation once its active work can no longer write to it. Late output must never recreate the conversation. If cancellation/deletion cannot complete, preserve a recoverable state and show failure instead of claiming deletion succeeded; exact coordination belongs to the streaming/runtime implementation plan.

## Answer

The two accepted grilling rounds define the first-release conversation lifecycle:

- **Create and name:** an empty conversation is a draft until the first submission. Save the first user message before generation. Produce its initial short title locally, support manual rename, and list conversations by latest message activity. The previously resolved cloud confirmation still precedes any external disclosure.
- **Retain and resume:** keep submitted messages and bounded tool records until explicit deletion. Load saved history on resume, with pagination for older messages. Model context remains the bounded recent complete exchanges selected by the runtime; retained history and transmitted context are distinct.
- **Order and concurrency:** permit one active response per conversation across tabs. Do not queue another submitted message while it runs. Corrections are new messages; earlier messages are not editable or branchable in this release.
- **Interruptions:** browser disconnection does not cancel the response; generation continues within its existing deadline, and reconnect reads its current state. Explicit Stop cancels. Server restart or generation failure leaves available partial text marked incomplete and never automatically replays a request.
- **Retry:** only the latest failed, stopped, or interrupted response is retryable, before a later user message exists. A retry keeps the original user message once, preserves previous incomplete attempts, and creates a fresh response attempt with the same provider/model and fresh tool reads. It does not resume mid-execution or feed failed output/orphaned tool results back as completed history.
- **Delete:** one confirmation removes the conversation and its messages/tool records from the active database. If a response is active, that confirmation also stops generation; delete once active work can no longer write to the conversation. Late output must not recreate it. Failure remains visible and recoverable. Shopping facts and archived emails remain intact. There is no first-release undo; existing backups and provider-held data are outside this deletion operation.

The streaming ticket must enforce these observable lifecycle rules, including reconnect without duplicate generation, recoverable partial output, and deletion races. In particular, the earlier protocol report's suggested disconnect cancellation is not the selected browser-disconnect policy: the operator explicitly chose continued generation within the deadline. The runtime ticket defines generation limits and cleanup; the implementation plan adds schema and persistence work through future numbered migrations. This resolution changes planning documents only.
