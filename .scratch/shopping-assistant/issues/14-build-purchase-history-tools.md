# Build purchase history tools and evidence

Parent: ../map.md
Type: task
Status: open
Blocked by: 09

## Goal and contracts

Implement the four purchase history Read Tools and real evidence destinations,
without a model, new ingestion logic, or shopping writes. Read the shared
[implementation plan](../implementation-plan.md), glossary, and final contracts in
tickets [02](02-define-read-tools.md), [06](06-define-agent-runtime.md), and
[11](11-define-receipt-date-extraction.md).

## Files and boundaries

- Create `app/assistant/__init__.py`, `app/assistant/tools.py` for strict arguments,
  the four-tool dispatch boundary, result envelope, and application-owned evidence.
- Create `app/assistant/queries.py` for bounded read queries; reuse patterns from
  `app/db/repository.py` and `app/web_queries.py`, not their broader date fallback or
  unbounded order detail responses unchanged. Do not refactor ingestion.
- Modify `app/web_app.py` and `app/web_ui.py` for a minimal `/products/{product_id}`
  page backed by the same current purchase facts. Reuse existing `/orders/{order_id}`.
- Create `tests/test_assistant_tools.py`; extend `tests/test_web.py` for evidence
  links/escaping. Update README with only the newly implemented capabilities.

## Inputs, outputs, and state

Inputs are the fixed tool name and strictly validated query/IDs/limit/cursor. Output
is the accepted `status`, `data`, `evidence`, `next_cursor`, `truncated` envelope.
Expose schemas for the later Ollama adapter and one dispatch entry point accepting
Settings, a tool name, and argument mapping. Reject unknown names before querying.
No shopping facts or raw archives change. Database connections open and close in
the query's thread; tool results contain no archive paths or email internals.

## Implementation steps and checks

- [ ] Add synthetic current and historical revisions with different source and
  delivery dates, `placed` status, missing values, and multiple matching products.
  Verify each logical current order contributes once and Purchase Date is exclusively
  its recorded `delivery_at`; no completed-only filter or invented missing date.
- [ ] Implement `search_products` and `get_product_history` with strict IDs/limits,
  deterministic ordering and validated cursors bound to the query. Verify ambiguity
  returns candidates, not an inferred identity; invalid/foreign cursors fail safely.
- [ ] Implement `list_recent_orders` and paged `get_order`, with deterministic
  tie-breaking and a documented consistent position for absent Purchase Dates.
  Verify unknown IDs versus valid empty results are distinct.
- [ ] Apply both row ceilings and the 4 KiB UTF-8 envelope cap. Test multibyte names,
  a page that fits fewer rows, truthful continuation, and a single oversized row
  producing a safe size-limit error rather than cut JSON or omitted fields.
- [ ] Verify money/currency/quantity/date fields retain recorded values. Never report
  a partial-page sum as an entire-history total. Reject extra fields and coercions.
- [ ] Generate stable order/product evidence IDs and local URLs. Add the product
  page and test known/missing IDs, pagination, HTML escaping, and navigable links.
  Malicious product text must remain text; no remote resources or raw HTML.
- [ ] Run focused checks, then the shared full check/wheel/review workflow.

```bash
uv run pytest -q tests/test_assistant_tools.py tests/test_web.py tests/test_repository.py
```

## Deployable result

Deploy after its green-main checkpoint. The existing UI remains usable and product
evidence is inspectable; Chat is not yet exposed. No Ollama configuration or schema
change is needed solely for these read tools. Record the checkpoint without claiming
the Shopping Assistant is complete. Next: ticket 15 consumes these schemas/results.
