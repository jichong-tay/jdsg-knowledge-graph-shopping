# Ticket 22 execution and review directions

Date: 20 September 2026
Authority: the operator explicitly requested implementation after the graph UI
redesign, with Luna/low coding and root review. This supersedes historical
planning-only statements in the accepted plan. No further operator gate is needed.

## Baseline

Preserve checkpoint b5e601863167824941f1f405ec57804cb2e32f15 and all ticket 21 work.
The root reproduced all three archived synthetic failures before changes:
Stop leaves saved status stopping and global generation faulted; marker-only
completion leaves saved status running and faults the next send; selecting stale
B clears still-valid A in the client. These are acceptance failures, not expected
behavior. The actual development DB is schema 3 and purchase facts match its
verified schema-2 backup; ticket 22 requires no migration.

## Responsibilities and sequence

1. Luna implementer A: R1/R2 lifecycle repairs, strict storage retained, deterministic
   integrated regressions. Then R3 client/server subscription preservation.
2. Luna implementer B: dates and bounded monthly read (tasks 5/6), isolated from
   A's runtime/chat files. Add precise boundary/cursor/whole-row tests.
3. Root reviews both increments before directing A to response contract, focused
   answer renderers, frozen runtime context and durable monthly continuation.
4. B handles independent browser/integration verification and corrections as
   directed. All application and test edits remain with Luna/low agents.
5. Root verifies real-model synthetic behavior, browser behavior, actual dev data
   with count/boolean-only output, full checks, installed wheel and documentation.

## Review requirements

- Keep storage validation strict. A cancelled attempt may reference only durable
  tool results. Preserve saved-before-display ordering and actual cleanup faults.
- Validate visible text after marker stripping. Empty mode output is incomplete,
  not complete and not a service-wide fault. Next send must succeed.
- Bind failed switching to the requested target and command ID. Keep both A's
  browser selection and server subscription if B cannot be loaded.
- Use typed conversation markers with fixed application-owned text. Discard
  arbitrary uncited model prose. A marker cannot authorize invented purchase
  facts. Mixed purchase requests need fresh reads or an honest incomplete result.
- Extract answer formatting from runtime. A useful record dump is not necessarily
  an answered question. Preserve requested fee/unit-price fields and explain
  existing products with no current history. Unsupported forecasts are explicit.
- Freeze aware Singapore date instructions once per attempt before token counting.
  Month bounds are UTC half-open intervals. No email-date substitution.
- Monthly rows retain repeated lines and current placed revisions, max 20/default
  10 rows, 4096 UTF-8 bytes including envelope/evidence, whole rows only.
- Echo resolved month and limit in results. Cursor scope binds DB/tool/month/limit.
  Use saved complete tool groups for continuation without schema changes. A
  continuation must retain its original month across reconnect/calendar rollover.
  Missing/expired cursors must explain restart, never silently restart at a new
  month's first page. Avoid depending only on model memory after context trimming.
- Preserve all runtime limits and numeric call IDs. No hidden repair loop, RAG,
  vector DB, framework, model swap, or unrelated deployment change.

## Protocol probe evidence

Root verified the installed Ollama endpoint reports 0.30.10 and probed Qwen3.5:9b
with thinking disabled, using synthetic text only. The extended existing marker
encoding worked for greeting and thanks. A mixed greeting/latest-order question
produced a fresh list_recent_orders tool call. Model greeting/thanks prose also
invented catalog/recommendation capabilities, so fixed application wording is
required; arbitrary prose is not accepted by this probe. Help, clarification and
unsupported probes and full application acceptance will be recorded separately.
These preliminary direct HTTP probes do not establish full token-accounting or
runtime acceptance.

## Review observations and compatibility ruling

Root review rejected early partial implementations: the Stop race initially still
failed, the first stale-target client patch broke new drafts, monthly tests lacked
calendar boundary cases, and the first renderer guessed fee field names. Each
finding was returned to Luna/low for correction rather than accepted from a report.

Extended marker and native JSON-schema probes were inconsistent on the installed
model. Keep plain markers, never accept arbitrary uncited prose, and use fixed
application wording for nonfactual modes. A narrow validated capability request
(for example, “what can you do?”) may select application help after a clean model
response even if the model omits its marker. This measured compatibility fallback
discards the entire model answer, permits no purchase suffix, and adds no repair
generation. Greetings use the response contract; the old greeting input shortcut
is removed. Marker-only clarification/unsupported output remains an incomplete
failure even for a capability question. Intent guards are conservative checks,
not a claim of complete natural-language understanding.

Fresh full-runtime synthetic checks against Qwen passed “hello world”, “thanks”
and capability help with one model request and zero tools each. Help failed before
the narrow fallback; those failures are retained as evidence for this decision.

Root independently compared the new monthly tool with all actual current item
rows, grouping aware delivery timestamps into Singapore months in Python. All 110
rows matched over 9 months and 20 pages; the largest envelope was 4,070 UTF-8 bytes.
This check made no database changes. It establishes retrieval agreement, not yet
Chat answer/continuation acceptance.

## Final model compatibility adjustment

Repeated real-runtime checks found two inconsistent choices: the model sometimes
requested limit 100 twice for monthly items, and sometimes selected greeting mode
for thanks. Strict validation correctly rejected the oversized proposal; the
ordinary reply still used fixed safe wording but was inappropriate for the input.
The page guidance now states default 10 and maximum 20, with exact returned cursors.
Explicit typed-mode instructions and temperature 0 passed a fresh four-case probe:
greeting, thanks, help and the exact previous-month item question. Apply that
combination and verify the permanent suite again. This changes neither the model
nor runtime budgets, and adds no repair generation or argument coercion. Legacy
generic conversation markers remain valid for compatibility.

Ollama documents temperature as a supported sampling option in its
[official Modelfile reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx).
Temperature 0 reduces sampling variation; it is not a guarantee of semantic
correctness. Exact factual rendering and strict tool validation remain necessary.

## Final integrated verification — 21 September 2026 (Singapore)

Ticket 22 is resolved locally. Luna/low performed all application and test coding;
the controller reviewed the source, returned corrections and ran independent final
checks. The [ticket completion answer](../issues/22-implement-chat-remediation.md#answer)
records the final scope and evidence.

- Ruff format/lint, Pyright, lockfile/sync, secret hook and diff checks passed.
  The complete suite passed 539 tests with five opt-in model tests skipped and one
  existing dependency deprecation warning. The opt-in installed-Qwen suite passed
  all five tests separately, including a real-model monthly first page followed by
  saved deterministic continuation across a calendar change.
- Protected browser checks passed stale-target switching, preserved selection and
  draft, initial stale restoration with a populated library, rename and new sends.
  The initial library fix was exercised with a browser session restored after the
  synthetic server restarted, not only with a fresh session.
- The actual dev database browser flow returned 15 monthly item lines in pages
  of 6, 6 and 3, including continuation after reload. Independent SQLite checks
  matched every row, rendered field, saved evidence reference and original cursor
  scope. The largest envelope in that flow was 3686 bytes. All 12 original
  non-Conversation purchase/source tables still match the verified backup.
- Actual-data graph browser checks and all 41 Product timeline SQL comparisons
  passed again. The redesigned overview remained readable, with no external
  browser resources; desktop/mobile, empty and renderer-unavailable states were
  also verified with synthetic data.
- The final wheel was installed outside the checkout into a read-only environment.
  All three migrations and six required browser assets, including the Cytoscape
  bundle/license, were present. CLI migration reached schema 3; Graph, the empty
  monthly tool and protected Chat's ready/library bootstrap passed.

The app remains running locally against the authorized dev database. Changes are
uncommitted; no push or homelab deployment occurred. Ticket 18 remains open. These
checks establish the recorded cases, not perfect language understanding. No RAG,
BM25, forecast engine, replacement model or additional infrastructure was added.

## Retained accepted contracts from interim review

Monthly continuation preserves the original month, nondefault limit, and signed
cursor from the latest complete tool group. It validates cursor scope before one
fresh deterministic read; invalid or expired cursors explain that the original
month must be restarted without silently reading a first page. Calendar rollover,
reload/reconnect, exhausted pages, later unrelated tools, and trimmed older
exchanges are covered by permanent continuation tests.

Stop and durable evidence remain one lifecycle contract: explicit Stop prevents
late model/tool output, durable tool results are saved before broadcast, and
unsettled cleanup faults preserve a recoverable availability fault rather than
freeing the slot while work may still run. Marker-only responses and
Conversation switching have permanent regression coverage; archived probes are
historical evidence only.
