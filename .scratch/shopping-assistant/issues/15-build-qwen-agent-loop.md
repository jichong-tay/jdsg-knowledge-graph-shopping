# Build the Qwen connection and Python agent loop

Parent: ../map.md
Type: task
Status: open
Blocked by: 14

## Goal and contracts

Produce one tool-grounded answer with installed `qwen3.5:9b`, thinking disabled,
through a small native Ollama adapter and explicit Python loop. No framework, model
comparison, permanent test CLI, production Chat route, or automatic updates. Read
the [shared plan](../implementation-plan.md) and final contracts in tickets
[03](03-define-cloud-disclosure.md), [06](06-define-agent-runtime.md), and
[12](12-define-provider-operations.md).

## Files and boundaries

- Create `app/assistant/ollama.py` for cancellable native HTTP streaming and complete
  correlated tool proposals, `app/assistant/runtime.py` for validation/budgets and
  sequential tool execution, and `app/assistant/context.py` for bounded context.
- Modify `app/config.py`, `.env.example`, `deploy/shopping.env.example` for explicit
  local endpoint, model and application origin settings. Keep safe defaults so the
  old environment can run the existing app; missing Chat origin disables Chat, not
  Orders. Reuse validated Settings, not a provider/settings dashboard.
- Modify `deploy/deploy-ubuntu.sh`, `deploy/bootstrap-ubuntu.sh` and
  `tests/test_deployment.py` for narrowly allowed optional settings before adding
  them to the host. Preserve required values, rejection of duplicates/unknown keys,
  standard paths, and rollback behavior; never source an untrusted env file.
- Create `tests/test_assistant_runtime.py`, `tests/test_ollama.py`,
  `tests/test_assistant_context.py`; extend `tests/test_config.py`. Use an existing
  suitable async HTTP client with an explicitly declared locked dependency if needed;
  no blocking network reads on the app event loop.
- Add an explicit opt-in `tests/integration/test_ollama_smoke.py` with a temporary
  synthetic database. Default CI must skip real-model calls and need no network.
- Update README and deployment/runtime sections in the existing docs.

## Inputs, outputs, and state

The adapter consumes model identity, bounded messages, and ticket 14 tool schemas;
it yields text, complete tool proposals, clean completion, or safe errors. The loop
consumes current question/completed exchanges and ticket 14 dispatch; it emits
bounded output/tool/status updates for a collector now and durable storage later.
Do not build a generic event bus. It holds one active response slot, never a DB
transaction while waiting. This ticket need not persist Conversations.

## Implementation steps and checks

- [ ] First implement/test a backwards-compatible helper change with the old
  five-key environment. Deploy this green-main preparation independently; confirm
  the installed helper accepts the intended optional keys before adding them.
  Check old-config/new-code and expanded-config/compatible-rollback combinations,
  including recovery. Keep the previous compatible helper/config path available.
- [ ] Add the adapter with native top-level `think: false`, 8K context, 768 output,
  and five-minute keep-alive. Test fragmented streaming/tool arguments, multiple
  proposals, safe errors, clean end versus EOF/truncation, and request cancellation.
- [ ] Verify actual Qwen template/token-accounting support before sending history.
  Count instructions, schemas, role/template overhead, messages, and full tool
  groups; compare against provider-reported counts where available. Drop only whole
  old completed exchanges. Oversized mandatory input fails visibly. Do not assume
  an undocumented tokenize API exists or use character counts as the proof.
- [ ] Implement the single-slot loop under all shared limits, whole-batch strict
  validation, sequential execution, same-attempt canonical-call reuse, and one
  validation correction. Fake-provider tests cover invalid/extra arguments,
  exhausted budgets, repeats, fresh reads on a new attempt, and no operational retry.
- [ ] Require fresh evidence for current purchase facts and validate references
  before completion. Test ambiguous/missing products, refusals without unnecessary
  tools, invented references, malicious tool text, and unsupported analytics.
  EOF, pending tools, invalid required evidence, or limits produce incomplete output.
- [ ] Test busy rejection, Stop/deadline, no further work after cancellation,
  five-second cleanup, and faulted availability if cleanup cannot settle. A model
  outage must not change core `/api/health` readiness or administer Ollama.
- [ ] After the backend is deployed, run one explicit synthetic tool round trip
  locally on the homelab using a temporary development DB and the installed endpoint.
  Run in the service's effective context when accessible, otherwise record that
  limitation. Do not populate real purchase data or require private samples.
  Record server/model digest, thinking mode, context, cold/warm time and GPU placement.
- [ ] Complete the shared checks/review/docs and deploy coherent backend increments.

```bash
uv run --locked pytest -q tests/test_ollama.py tests/test_assistant_runtime.py tests/test_assistant_context.py tests/test_config.py tests/test_deployment.py
```

## Deployable result

The model backend can answer the synthetic question without a browser; existing
Orders remain independent of Ollama. No separate comparison phase: investigate a
concrete failure if the selected model cannot complete the basic loop. Next: ticket
16 adds durable records; ticket 17 wires them into the live response lifecycle.
