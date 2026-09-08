# Define the read-tool and evidence contracts

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex

## Question

Which exact application-owned read tools, validated arguments, bounded results, ambiguity behavior, and order/product evidence links let the Shopping Assistant answer questions about currently implemented facts without direct SQL, raw email access, or unsupported inference?

## Comments

- The operator accepted the recommended four-tool boundary and evidence rules on 2026-09-08.

- Reopened and claimed by Codex after the process audit: the four tools, structured facts, evidence links, and privacy rules remain approved. The detailed proposal below was recorded prematurely; limits, pagination, ambiguity, revision/date semantics, and evidence stability need a live grilling round before resolution.

## Prior proposal — pending detailed agreement

This is retained as discussion history only. The final Answer below incorporates the operator's grilling answers and supersedes conflicting parts of this proposal.

The first release exposes exactly four application-owned read tools. Tool handlers own the SQL and return facts from the authoritative current SQLite state; the model receives neither SQL access nor database, archive, or email internals.

| Tool | Validated arguments | Bounded result |
|---|---|---|
| `search_products` | `query`: trimmed string, 1–200 characters; `limit`: integer, default 10, range 1–20 | Deterministically ordered product candidates with stable product ID, canonical name, match kind, purchase count, last purchase time, and product evidence link |
| `get_product_history` | `product_id`: positive integer; `limit`: integer, default 20, range 1–50; optional opaque cursor | Current completed-order purchase rows containing order ID, purchase time, quantity/unit, currency, unit price when recorded, net line amount, and order evidence link |
| `list_recent_orders` | `limit`: integer, default 10, range 1–25; optional opaque cursor | Current logical orders ordered by purchase-event time, with stable ID, retailer, order reference, status, currency, total cents, item count, and order evidence link |
| `get_order` | `order_id`: positive integer | One current logical order and its current-revision items, quantities, prices, totals, dates, status, and evidence links |

All tools use one result envelope: `status`, structured `data`, `evidence`, optional `next_cursor`, and `truncated`. Money remains integer cents with an explicit currency; timestamps remain timezone-aware UTC strings. Results never contain raw email content, sender details, archive paths, credentials, parser internals, or unrestricted database context.

Search is deterministic rather than inferential. Each candidate reports `exact`, `prefix`, or `contains` match kind. When multiple plausible products remain, the assistant lists the candidates or asks the operator to choose; it must not silently select one. Unknown IDs return `not_found`. Invalid inputs, timeouts, and unavailable storage return stable typed errors without internal exception text. An empty valid search is a successful empty result, not permission to improvise.

Every quantitative, dated, product-specific, order-specific, or status claim must cite at least one evidence entry returned by the tool. Evidence entries contain a stable reference ID, entity type and ID, human label, canonical local URL (`/orders/{order_id}` or `/products/{product_id}`), and the fact fields that entry supports. The Chat page renders compact tool activity and these references as links. Unsupported or missing facts are stated as unavailable; they are never estimated or inferred.

Tool output is untrusted content. Product names, retailer labels, and other stored text are displayed as data and can never alter system instructions or authorize additional tools.

## Grilling round one — operator answers

- Purchase inclusion: “all items. what you see is receipts”. Do not restrict the assistant's item history to `completed` status. Read items from each logical order's existing current revision without counting historical copies as additional purchases. Retain recorded status without asserting that every stored record proves completion.
- Changing evidence: “no need to handle this. it is receipts”. Do not add citation snapshots or a historical-revision browsing feature for this assistant release; evidence links use the current order/product pages. Existing append-only storage and revision selection remain unchanged.
- Dates: “receipts will contain the dates, no need to handle”. The desired behavior is to use the actual recorded receipt date, without the previously proposed delivery/order/source-message fallback policy.
- Ambiguity: accepted recommendation to ask which product is intended when several distinct products match a product-specific question.
- Result limits: accepted search default 10/max 20; history default 20/max 50; recent orders default 10/max 25; order items 50/page. Support additional pages and identify partial results; partial-page totals must not be presented as complete-history totals.

## Date question — resolved by operator convention

Current code does not yet supply a receipt/purchase date: `app/email/parsers/fairprice.py` sets `revision_kind="confirmation"`, `status="placed"`, and `ordered_at=None`, while extracting `delivery_at` and the original message timestamp. `tests/test_parser.py::test_parses_direct_html_order` explicitly verifies this. The operator's description of the inputs as receipts does not by itself change these stored meanings.

Recommend reporting a purchase date as unavailable when it has not been extracted, rather than relabelling a delivery or email date. The operator approved planning explicit receipt-date extraction and offered local private samples. The source/date representation and parser work are now tracked in [Define receipt-date extraction](11-define-receipt-date-extraction.md). Implementation remains paused.

After the sample inspection, the operator explicitly chose to use the delivery date as the purchase date. This supersedes the earlier requirement for a separate receipt date: tools use `delivery_at` as `purchase_date`, and normal assistant output calls it **Purchase date**. No separate date extractor is required; see the resolved date ticket for the implementation implications.

## Answer

Resolved from the operator's five grilling answers and subsequent explicit purchase-date decision. The initial proposal's completed-only filter and separate receipt-date requirement are superseded.

### Read tools

| Tool | Inputs | Returned facts |
|---|---|---|
| `search_products` | Product query, bounded limit, pagination when more matches exist | Stable product IDs and names, matching candidates, evidence links, and completeness information |
| `get_product_history` | Product ID, bounded limit, pagination | Matching receipt items with order/product IDs, purchase date, quantity/unit, recorded prices in cents with currency, and order evidence |
| `list_recent_orders` | Bounded limit, pagination | Current logical orders with ID, retailer/reference, purchase date, recorded status, currency, total cents, item count, and evidence link |
| `get_order` | Order ID, item pagination | Current receipt facts and a bounded page of its items, including product IDs/names, quantities, recorded prices/totals, and evidence |

- Include all items from current logical orders without filtering on `completed`; historical copies are not additional purchases. Preserve stored status as data.
- Use the extracted delivery date as **Purchase date**, as resolved in [Define receipt-date extraction](11-define-receipt-date-extraction.md). Date-based ordering uses that date, not the source-email timestamp. Do not invent absent values.
- Search defaults to 10 results, maximum 20; product history defaults to 20, maximum 50; recent orders default to 10, maximum 25; order items are paged at 50. Additional pages are accessible through validated application-owned pagination.
- Clearly identify partial results. Never describe a partial-page sum as a complete-history total. Per-turn limits on following pages belong to the runtime ticket.
- When several distinct products match a product-specific question, ask the operator which product is intended. Do not silently pick the latest match.

### Evidence and validation

- Return structured facts, stable IDs, application-generated local evidence links, and explicit completeness/pagination metadata.
- Use ordinary current order/product links. Do not add citation snapshots or revision-specific evidence browsing. This does not change append-only storage or current-revision selection.
- Factual claims must be supported by returned evidence. Missing facts remain unknown; unavailable analytics cannot be inferred.
- Validate tool names and argument schemas before execution. Unknown IDs, invalid input, and execution failures have explicit safe errors; a valid empty search is an empty result.
- Raw email content, archive paths, credentials, and arbitrary database access are excluded. Stored names and other tool text are untrusted data and cannot authorize operations or override instructions.

Implementation and the fixed evaluation set must cover inclusion of parser-labelled `placed` records, no duplicate historical purchases, purchase-date mapping, ambiguity, pagination completeness, missing records, and malicious product text. Application code remains unchanged during Wayfinder planning.
