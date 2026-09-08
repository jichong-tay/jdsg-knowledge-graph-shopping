# Build saved Conversations and Response Attempts

Parent: ../map.md
Type: task
Status: open
Blocked by: 15

## Goal and contracts

Persist the approved lifecycle using a small SQLite repository, independent of
browser or real-model tests. Read the [shared plan](../implementation-plan.md),
tickets [03](03-define-cloud-disclosure.md), [04](04-define-conversation-lifecycle.md),
[06](06-define-agent-runtime.md), and [07](07-define-streaming-protocol.md).

## Files and boundaries

- Add `app/migrations/002_conversations.sql` if 002 remains the next available number
  when work starts. Never change 001 or execute schema DDL from app startup.
- Create `app/assistant/conversations.py` for short lifecycle/command/checkpoint
  operations, reusing `app/db/connection.py`. Avoid a generic repository framework.
- Create `tests/test_conversations.py`; extend `tests/test_migrations.py` and package
  checks. Update README and the chat schema section of `docs/MVP_PLAN.md` to match
  the actual migration, not the broader historical roadmap.

## Inputs, outputs, and state

Persist Conversations, immutable submitted messages, Response Attempts, bounded
tool records, monotonic versions, and mutation deduplication needed by ticket 07.
Expose repository operations for accepting submission/Retry, checkpointing,
terminal transitions, paginated reads, rename, delete fencing/finalization, and
restart interruption. Each returns the saved state needed for acknowledgement or
snapshot; no operation performs model/network work inside its transaction.

## Implementation steps and checks

- [ ] Write file-backed migration tests for fresh/current databases, preserved
  ingestion facts, checksums/dirty state, and schema verification failures. Apply
  only through `shopping migrate`; verify the built wheel includes both migrations.
- [ ] Implement atomic first-message acceptance: create the Conversation only on
  accepted submission, derive title locally, save message and attempt before any
  future acknowledgement/generation. Fix endpoint/model identity on creation.
- [ ] Persist command IDs with canonical command content and outcomes. Test duplicate
  submit and Retry return the existing result, conflicting reuse fails, and stale
  commands cannot recreate deleted Conversations. Keep only the minimal creation/
  deduplication fencing needed; no token event-replay table.
- [ ] Implement paginated history and bounded context selection. Retain failed
  attempts for display but exclude their text/orphaned tool results from model input.
  Retry is only for the latest unsuccessful attempt before a later user message;
  keep its original submitted message once and use fresh tool reads.
- [ ] Implement monotonic saved checkpoints and terminal transitions. Test
  persistence failure rolls back a checkpoint, accepted Stop fences late completion,
  completed-first stays complete, and wrong/stale attempt targets cannot affect a
  newer attempt. Local Stopping and interrupted/failure outcomes stay distinguishable.
- [ ] Implement deletion fencing before local cleanup, followed by confirmed
  removal of only Conversation-owned records. Late writes cannot resurrect data;
  failed cleanup/deletion must remain recoverable. Shopping facts and raw emails
  are untouched; do not promise removal from existing backups.
- [ ] Add startup recovery operation marking unfinished attempts interrupted before
  new work; wire it into app lifecycle in ticket 17, never rerun questions. Test
  simultaneous requests using separate same-thread connections and short transactions.
- [ ] Complete focused/shared checks and deploy the additive migration through the
  verified backup path. Check rollback to the previous application/database state.

```bash
uv run --locked pytest -q tests/test_conversations.py tests/test_migrations.py tests/test_repository.py
```

## Deployable result

The schema and lifecycle operations are deployed and tested; no unprotected Chat
mutation endpoint is exposed yet. Ticket 17 consumes saved-state operations and
ticket 15 runtime updates, committing before broadcasting them.
