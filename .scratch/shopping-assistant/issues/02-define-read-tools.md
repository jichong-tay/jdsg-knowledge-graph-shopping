# Define the read-tool and evidence contracts

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex

## Question

Which exact application-owned read tools, validated arguments, bounded results, ambiguity behavior, and order/product evidence links let the Shopping Assistant answer questions about currently implemented facts without direct SQL, raw email access, or unsupported inference?

## Comments

- The operator accepted the recommended four-tool boundary and evidence rules on 2026-09-08.

## Answer

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
