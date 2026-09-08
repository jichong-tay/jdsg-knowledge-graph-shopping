# Define the provider-neutral agent runtime

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: 01, 02

## Question

What is the smallest explicit Python agent-loop and Ollama-adapter contract that preserves tool-call state, bounds context and generation, prevents model-authored execution, and keeps SQLite operations outside model waits?

## Comments

- The operator chose a small application-owned Python loop for the initial Shopping Assistant, with no orchestration framework. This is a design choice only: implementation is paused until Wayfinder planning is finished.
- The agreed high-level flow is bounded context plus tool definitions → model request → validate complete tool proposals → execute approved Python read tools → return structured results and evidence → repeat until a final answer, cancellation, timeout, or loop limit.
- Context budgets, loop limits, error recovery, and the provider interface are resolved below. Conversation persistence and browser-stream mechanics remain in their dedicated tickets.
- [Explore agent orchestration libraries](10-explore-agent-orchestration-libraries.md) is now deferred outside this MVP. Keep a small application interface around Ollama, but do not implement a cloud adapter or a speculative framework abstraction.

## Original grilling round one — superseded, not accepted

These are proposals, not accepted decisions. The small Python loop, four read tools,
fixed Ollama destination, one active Response Attempt per Conversation, and explicit
Retry lifecycle are already settled and are not being reopened.

1. **Work limits:** may a Response Attempt stop before fully answering an unusually broad question? Recommend starting with a 120-second total deadline, at most 6 model requests and 12 proposed tool calls (including pagination and invalid proposals). All corrective requests count toward the same budgets. On exhaustion, mark the attempt incomplete and explain the limit; never present partial coverage as complete. These are provisional configurable defaults to validate against tickets 08/13, not measured homelab capacity.
2. **Tool mistakes:** what should happen if the model proposes an unknown tool or malformed arguments? Recommend validating the entire proposed batch before executing any of it, running accepted calls sequentially, and allowing one corrective model request per attempt with a safe validation error. A second invalid batch ends the attempt. Model text never becomes executable code or SQL.
3. **Context overflow:** what should give way when a Conversation grows too large? Recommend dropping the oldest complete exchanges first, retaining instructions, tool definitions, the current question, and complete current-attempt call/result groups. Never cut a tool result in half or silently truncate the current question. If required content cannot fit, explain the limit rather than send malformed context. Exact context/output and payload budgets follow this policy decision.
4. **Operational failures:** should the loop automatically repeat failed model requests or database reads? Recommend no automatic operational retries in the MVP: preserve available partial output, show a safe failure, and offer the accepted explicit Retry action. Empty results and not-found responses are normal tool outcomes, not infrastructure failures. The one model-correction opportunity in question 2 is distinct from replay after an outage.
5. **Fresh evidence:** can the assistant answer a new receipt-fact question solely from earlier conversation text? Recommend fresh read-tool evidence in each Response Attempt for claims about current shopping records. Earlier exchanges may resolve conversational references, but do not substitute for fresh facts. Clarifications and unsupported-request explanations do not require a pointless tool call. The application generates evidence links from returned references; citation presence alone is not proof that prose is accurate.
6. **Homelab contention:** what should happen when another Conversation is already generating? Recommend initially allowing one active Response Attempt across the application, with a visible busy response and no hidden queue. Reject a competing submission before saving it as an accepted message, and preserve the browser draft. Keep the existing stricter per-Conversation rules across tabs; revisit the global cap after measuring the host.

Next dependent decisions: precise context/output/payload budgets, response/tool event
boundary and safe completion checks, and cancellation/cleanup ownership. Browser
stream sequencing and replay mechanics remain in ticket 07; model installation and
host-specific tuning remain in tickets 12/13. Application implementation is paused.

## Hardware-aware grilling round one — accepted

The operator requested revised questions accounting for the homelab hardware.
`docs/MVP_PLAN.md` records Ubuntu, i5-3570K, 16 GB system RAM, and RTX 3060 with
12 GB VRAM. These remain the planning baseline, not a verified inventory; ticket
13 has not established available VRAM, competing workloads, model version, or actual
latency. Its existing provisional runtime settings are one loaded model, one model
request at a time, 8,192-token context, and 768 generated tokens per model request.

Ollama's [FAQ](https://docs.ollama.com/faq) explains that parallel requests increase
context-memory requirements and that `ollama ps` reports CPU/GPU placement. Its
[context guidance](https://docs.ollama.com/context-length) recommends avoiding CPU
offload for performance. Accordingly, prioritize one GPU-resident model and bounded
context; do not infer a guaranteed model fit or tokens-per-second rate from VRAM alone.

The operator explicitly accepted all six revised recommendations. They supersede
the original round; numerical settings remain provisional defaults to benchmark,
not measured hardware capacity.

1. **Work limits:** start with a 180-second total Response Attempt deadline including model loading, at most 4 model requests and 8 proposed tool calls, including pagination and invalid proposals. Cap generation at 768 tokens per model request as the existing plan proposes. This trades fewer repeated model passes for some cold-start headroom; it is a provisional safety limit, not an expected answer time. Corrections consume the same budgets. Exhaustion is an incomplete outcome, never a claim of complete coverage.
2. **Tool mistakes:** retain whole-batch validation before any execution, sequential valid tool execution, and one corrective model request per attempt. A second invalid batch stops the attempt. Strict validation remains necessary regardless of GPU size; the repair allowance cannot bypass the model-request cap.
3. **Context size and overflow:** start evaluation at 8,192 total context tokens, reserving room within that window for output, instructions, schemas, and current-attempt tool results. Remove oldest complete exchanges first, without cutting the current question or splitting call/result groups. If measured GPU placement or memory stability is poor, test 4,096 before accepting CPU offload. If required content cannot fit, fail clearly. Exact input accounting and bounded result encoding still require the next dependent round; never assume 8K input plus extra output fits an 8K window.
4. **Operational failures:** retain no automatic model/database retries. Show a safe failure and preserve partial text for explicit Retry; avoid hidden repeated generation on the single GPU. Empty/not-found results remain normal tool outcomes. A cold start within the deadline is not itself a failure.
5. **Fresh evidence:** retain fresh reads for each new answer about current shopping facts. Earlier conversation text provides context, not replacement evidence. Keep returned pages bounded rather than sending all history. This is an accuracy boundary, not a hardware-dependent relaxation; clarification/refusal needs no pointless read.
6. **Concurrency:** permit one active Response Attempt across the application, consistent with the existing plan's one loaded model and `OLLAMA_NUM_PARALLEL=1`. Show busy and retain the competing draft rather than queue it. This limits context-memory multiplication and leaves the existing CPU/RAM available for the application and other host work; no claim is made about presently available resources.

This records design decisions only: no host configuration, application code, or
glossary term is changed. Validate model fit and tune these settings through tickets
08/12/13 before deployment. The existing bounded SQLite busy wait is not an
application retry; the accepted policy forbids replaying a failed database operation.
Older MVP_PLAN text proposing application retries must be reconciled when this
runtime ticket is resolved.

## Grilling round two — accepted

The operator explicitly accepted all four recommendations below with “accept all”.

7. **Input and context guardrails:** recommend a 4,000-character maximum per submitted message, validated before acceptance while preserving an oversized draft. At 8,192 context, budget at most 6,912 input tokens, 768 generated tokens, and 512 tokens of safety headroom. At the 4,096 evaluation fallback, use 2,816 input tokens with the same output/headroom. Input accounting includes instructions, tool schemas, role/template overhead, history, and tool content—not just visible message text. Old exchanges are removed whole, never replaced with generated summaries. Model-aware accounting must be validated for the selected model; character limits or a characters-divided-by-four heuristic are not proof of token fit. If fit cannot be established, fail clearly rather than rely on provider truncation. Oversized submitted text is not silently shortened.
8. **Bounded tool results and loop progress:** recommend a 4 KiB UTF-8 encoded envelope limit per tool result, including evidence and pagination metadata, in addition to the approved row-count ceilings and whole-request context check. Return fewer whole rows with truthful pagination when needed; never cut JSON, fact strings, or money values. If even one record cannot fit, return a bounded safe size-limit error. A full batch must fit the remaining tool-call budget before execution. Repeated identical calls (same canonical arguments/cursor) within an attempt count toward the call budget but reuse that attempt's result rather than querying again; a fresh Response Attempt always reads afresh. Subsequent pages are distinct calls. Validate strict allowlisted schemas and reject extra arguments/coercions; invalid proposals follow the accepted single correction allowance. Database failures stop the attempt rather than being disguised as empty results.
9. **Adapter boundary and completion:** recommend one small Ollama adapter emitting text deltas, complete correlated tool proposals, and explicit provider-end/failure outcomes, with optional usage metadata. The Python loop—not the adapter or model—owns tool execution, budgets, evidence references, and the terminal outcome. Mixed text/tool output is provisional until the tool sequence finishes. A response is complete only after a clean provider end, no pending tools, and successful reference validation; premature EOF, output-cap exhaustion, unknown evidence references, or missing required evidence leave it incomplete. Evidence URLs are generated from application-owned references, never arbitrary model URLs. These mechanical checks cannot prove every sentence is factually supported; instructions and the fixed evaluation set must test semantic grounding. No extra generation is silently added to repair a failed final answer. Exact browser event sequencing/persistence belongs to ticket 07.
10. **Stop and cleanup:** recommend checking cancellation/deadline before each model request and tool execution, and discarding late results once an attempt is terminal. Close the model stream on Stop or deadline, stop scheduling tools, and retain available text as incomplete. Allow up to 5 seconds of local cleanup beyond the 180-second work deadline; this is not extra generation time. Release the application slot only when local work can no longer append output or schedule calls. If local cleanup cannot settle, keep generation unavailable and report a recoverable runtime fault instead of admitting overlapping work or claiming success. Closing an HTTP stream is best-effort provider cancellation, not proof that GPU computation stopped. Do not automatically restart Ollama or kill host processes. Browser disconnect still does not cancel; deletion coordination and completion/Stop races are specified in ticket 07 under the accepted lifecycle.

## Answer

The accepted hardware-aware first round and second round define the runtime
contract. The original first round is superseded. Application implementation remains
paused; these are configurable starting limits for the recorded i5-3570K / 16 GB RAM /
RTX 3060 12 GB host, not verified capacity or latency guarantees.

| Boundary | Accepted starting limit |
|---|---|
| Active Response Attempts | One across the application; busy rejection retains the competing draft, no queue |
| Work deadline | 180 seconds including model loading |
| Model requests | At most 4 per attempt, including corrections |
| Proposed tool calls | At most 8 per attempt, including invalid/repeated calls and pagination |
| Generation | At most 768 tokens per model request |
| Context | 8,192 total: at most 6,912 input, 768 output, 512 safety headroom |
| Smaller context evaluation | 4,096 total: at most 2,816 input, 768 output, 512 safety headroom |
| User message | At most 4,000 characters; reject oversize before acceptance without truncating the draft |
| Tool result | At most 4 KiB UTF-8 envelope including evidence/pagination, plus the approved row ceilings |
| Tool correction | One corrective model request for an invalid batch, within all other budgets |
| Cleanup | Up to 5 seconds after work stops; no extra generation allowance |

- **Loop and adapter:** use a small application-owned Python loop and one Ollama adapter. The adapter normalizes text deltas, complete correlated tool proposals, provider end/failure, and optional usage. The loop owns validation, execution, context, budgets, evidence, and terminal outcomes. No orchestration framework, speculative cloud adapter, model-authored SQL, or arbitrary execution.
- **Read tools:** use only the four tools from ticket 02. Strictly validate the whole proposed batch and its remaining call budget before execution; reject unknown names, extra arguments, and coercions. Execute accepted calls sequentially. Reuse identical canonical calls within an attempt while charging the call budget; new attempts read afresh. Return whole rows with truthful pagination under the byte cap, or a safe size-limit error if one row cannot fit. Never split serialized results or silently omit facts from a returned row.
- **Context:** count the complete model input, including instructions, schemas, template overhead, history, and current tool groups. Validate model-aware accounting against the selected model; a character heuristic is not a fit guarantee. Drop oldest completed exchanges whole. Do not send generated summaries, other conversations, failed assistant text, orphaned results, raw emails, archive paths, or credentials. Required content that cannot fit fails visibly rather than being silently truncated.
- **Evidence and completion:** require fresh tool evidence for claims about current shopping records, without pointless calls for clarifications/refusals. Earlier conversation text may resolve references, not replace authoritative reads. Generate local links from application-owned evidence references. Mark complete only after clean provider completion, no pending tools, and successful reference checks. EOF, output/work limits, or missing/invalid required references leave an incomplete attempt. Reference validity is not semantic proof; the evaluation set must test grounded claims.
- **Failures and cancellation:** no automatic replay after model/database failures, and no hidden final-answer repair generation. Preserve available partial output and offer explicit Retry under ticket 04. The existing SQLite busy wait is allowed, but a failed operation is not replayed. Check Stop/deadline before new work, close the stream, and reject late output after termination. Release the slot only after local work can no longer append or schedule; unsettled cleanup leaves generation unavailable with a recoverable fault. Do not restart Ollama or kill host processes automatically. Provider cancellation remains best effort, not proof of GPU termination.
- **Handoffs:** ticket 07 owns browser event sequencing, durable completion, Stop/completion races, deletion coordination, and reconnect without replay. Tickets 08/12/13 validate context accounting, cancellation, model fit, host configuration, and latency. Preserve short, same-thread SQLite operations outside model waits. No new domain term is needed; Response Attempt, Read Tool, and Evidence retain their existing glossary meanings.
