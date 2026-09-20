# Chat retrieval options: SQL, RAG and BM25

Date: 20 September 2026

Status: Research recommendation. The operator accepted the Chat remediation
planning decisions, including the future fifth month-item read tool. No
implementation is authorized. Search enhancements below are recommendations,
not operator acceptance.

**Recommendation: no additional RAG infrastructure or BM25 is needed for the
current remediation.** Prioritize lifecycle reliability, response/evidence
handling, Singapore date context, exact monthly retrieval, and preservation of
requested fields. These address the documented R1–R6 findings; adding a relevance
index would not repair those failures. The precise cause of the user's real-data
month-query attempt remains unverified. See the
[investigation handoff](chat-investigation-handoff.md).

## Exact facts and retrieval-augmented answers

The existing Chat already retrieves external facts through validated, bounded
SQLite tools before generating an answer. In the broad architectural sense, this
augments generation with retrieval. It does not require a separate vector store.
The original RAG paper describes a particular architecture combining a generator
with a neural retriever over a dense Wikipedia passage index; that design is not
a requirement for every grounded assistant. This comparison is an architectural
inference from [Lewis et al., RAG](https://arxiv.org/abs/2005.11401) and the
[local read implementation](../../../src/shopping/purchases/queries.py).

“What items did I buy last month?” asks for all qualifying recorded purchase
lines, not the most relevant text passages. The accepted future
`list_purchase_items(month="YYYY-MM", limit, cursor)` should use an exact UTC
interval derived from Singapore calendar boundaries, current revisions, and
`delivery_at` as Purchase Date. Return bounded pages with explicit continuation
and partial-result status; preserve repeated lines and acknowledge missing dates.
Do not claim a whole month was enumerated from one limited page. Existing pages
read live state, so cross-page snapshot consistency is also not guaranteed.
[Local query semantics](../../../src/shopping/purchases/queries.py),
[month-query findings](chat-investigation-handoff.md#r5--capability-gap-last-month-item-listing-lacks-date-context-and-retrieval).

## Where BM25 could help later

SQLite FTS5 provides full-text matching; its `bm25()` function ranks matching
rows using phrase frequency, rarity, and document length. It is lexical relevance
scoring, not semantic synonym understanding. SQLite documents synonym handling
as an additional custom-tokenizer capability. Consequently, BM25 alone neither
understands that differently worded products are equivalent nor guarantees
complete month enumeration.
[FTS5 BM25](https://www.sqlite.org/fts5.html#the_bm25_function),
[synonym support](https://www.sqlite.org/fts5.html#synonym_support).

Current `search_products` searches contiguous text only in canonical names,
ordered by exact/prefix/contains match. A later, measured search improvement
could first cover raw item names, retailer/SKU distinctions and curated aliases;
FTS5/BM25 becomes useful when multiword keyword discovery needs better matching
and ranking. Keep any index derived and rebuildable, then retrieve authoritative
SQLite rows for dates, quantities, prices and evidence. Evaluate semantic
retrieval only if realistic questions still fail because wording differs despite
those simpler measures. These are optional future directions, separate from the
accepted Chat repairs.
[Current product search](../../../src/shopping/purchases/queries.py).
