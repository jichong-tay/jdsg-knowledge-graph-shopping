# Define the shopping knowledge graph model

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex

## Question

What entities, relationships, identity rules, and evidence should form the shopping
knowledge graph, before adding more Shopping Assistant tools?

## Operator direction

The operator clarified that building a knowledge graph is the original goal and
asked to investigate how to structure the existing data before building more tools.
The first use is now clarified: track how frequently particular items are purchased
and support predictions of future purchases. The operator chose delivery date as
Purchase Date for this purpose. Preserve order-placement and evidence timestamps
separately; current delivery timestamps represent scheduled slots.
In model round one the operator requested Product Family in the initial scope and
accepted the recommended purchase eligibility and occurrence-counting rules.
This changes the immediate priority to graph modeling. The accepted Chat repair
scope remains recorded in
[Define Chat remediation scope and acceptance](19-define-chat-remediation-scope-and-acceptance.md),
but its execution and additional tools are deferred during this exploration.
The operator has now explicitly authorized using the actual data under `data/`
for this investigation and stated that it contains nothing sensitive. Read-only
inspection of those records is in scope; do not limit model validation to synthetic
examples. Keep the originals unchanged and derived artifacts under the existing
ignored data/artifact paths.

This ticket defines the model before implementation. The operator's request to
implement Product Family establishes it as initial scope rather than deferred
enrichment. The operator subsequently accepted product-type families across
brands/sizes and reviewed membership suggestions. No schema
migration, dependency installation, service change, or deployment has been
performed during this discussion.

## Current progress

- [x] Inspect the implemented schema, ingestion identity rules, revision handling,
  and existing graph roadmap.
- [x] Research graph representations and draft the entity/relationship proposal.
- [x] Record the operator's permission to use the actual data under `data/`.
- [x] Inspect actual database date coverage and repeated-product order counts
  read-only: 15 current orders, no explicit `ordered_at`, 15 scheduled delivery
  timestamps, and 15 source-event timestamps. All 15 are `placed`.
- [x] Inspect the actual dataset and validate the proposal against representative
  records: available entities, listing/product identity, repeated item lines,
  revision/source associations, statuses, dates, and missing enrichment.
- [x] Update the proposal with observed data shapes, exceptions, and a concrete
  representative graph example. Keep observed findings separate from assumptions.
- [x] Settle the first graph use and Purchase Date basis with the operator:
  item frequency/future purchases, using delivery date.
- [x] Record Product Family in the initial scope and accept the recommended
  purchase eligibility and occurrence-counting rules (Q2/Q3).
- [x] Settle family membership semantics and assignment, record the accepted model,
  and translate the initial Product Family scope into the first implementation ticket.

Status is **resolved for model definition**. Source/schema research, actual-data
validation, family meaning/review, and date/eligibility/counting decisions are
complete. The accepted model is consolidated in the
[specification](../specs/shopping-knowledge-graph-model.md). Implementation continues
under [ticket 21](21-build-product-family-foundation.md); no graph or family feature
is implemented by resolving this planning ticket.

## Evidence and proposal

- [Accepted shopping knowledge graph model](../specs/shopping-knowledge-graph-model.md)
  is the consolidated model contract for implementation. It separates settled
  semantics from later forecasting and interface choices.
- [Shopping knowledge graph: model investigation](../research/shopping-knowledge-graph-model.md)
  maps implemented SQLite tables to a proposed graph, with an actual-data profile,
  an observed representative neighborhood using anonymized labels, a synthetic
  JSON example, provenance rules, date/frequency semantics, current schema
  limitations, and a proposed first milestone.
- [Knowledge graph representation options](../research/knowledge-graph-representation-options.md)
  compares an application-owned property graph, optional NetworkX traversal, and
  RDF using primary documentation.
- Existing graph tables/predicates in `docs/MVP_PLAN.md` are roadmap sketches,
  not implemented migrations or an accepted detailed graph model.

## Accepted decisions

1. **First use:** track item purchase frequency and support predictions of future
   purchases before expanding Chat tools.
2. **Date basis:** the operator said “Can use delivery date.” Use delivery date as
   Purchase Date, including frequency analysis and predictions. Current values
   are scheduled delivery slots, not confirmed arrival. Keep Order Date and email
   times separate; missing delivery dates stay unknown, with no email/order fallback.
   The earlier original-confirmation-time proxy question is superseded.
3. **Investigation inputs:** read-only actual data under `data/` is authorized.
   The originals remain unchanged; no import repair or forecast generation has
   been performed during this investigation.
4. **Product Family in initial scope:** the operator answered Q1 with “implement
   product family.” Add a grouping above Product while preserving exact Products,
   Listings, Items, revisions, and source evidence. Do not defer families to an
   unspecified later enrichment phase. Family breadth and assignment policy were
   settled in the subsequent round recorded below.
5. **Eligible recorded purchases (Q2 accepted):** use current `placed` and
   `completed` revisions with known Purchase Dates at or before the analysis date.
   Exclude cancelled/refunded/unknown and future scheduled deliveries from the
   historical analytic view. Keep their factual records and show upcoming orders
   separately; a past scheduled slot does not certify fulfillment.
6. **Occurrence counting (Q3 accepted):** preserve all Item lines and quantities;
   count one Product occurrence per logical Order, then distinct Singapore
   delivery days for day-gap calculations. Keep order count, purchase-day count,
   and quantities separate. The family equivalent unions contributing
   Products before counting, rather than adding member-product counts.
7. **Family meaning:** group the same product type across brands and package
   sizes; materially different types remain separate. Define each Family's
   inclusion/exclusion criteria rather than inferring membership from a broad
   category, similar prefix, or unreliable package metadata.
8. **Family assignment:** suggest memberships, then review them before they affect
   frequency. Preserve suggestion origin separately from review decisions and
   retain membership history. Unassigned Products keep their individual history.

The forecast target therefore concerns the next likely delivery-based Purchase
Date. Predicting order-placement timing or inventory depletion requires additional
lead-time or consumption information; it is not implied by this date decision.

## Model resolution and downstream work

The model decision frontier is settled. The first implementation deliverable is
persisted, reviewable Product Families/memberships, a deterministic graph projection,
and an inspectable family purchase timeline with unique orders/delivery days and
contributing Products, Items, and Sources. Keep quantities per exact Product when
package/unit compatibility is unknown. SQLite remains authoritative.

Ticket 21 owns the concrete implementation plan. The operator subsequently added
an interactive Graph UI with family review/timelines in the existing app. SQL
names, indexes, serialization mechanics, and renderer/interface
details are implementation choices, not reasons to reopen the settled model.
Concrete household memberships still need review before activation.

Forecast formula, minimum history, uncertainty evaluation, and alert behavior are
later work. Five purchase days and a median-gap forecast remain candidate rules,
not accepted accuracy guarantees. Existing Product counts cannot be relabeled as
Family counts. These downstream choices do not keep the model-definition ticket open.

## Comments

- Initial inspection used repository source, migrations, synthetic examples, and
  primary documentation only. No household records were inspected or exported.
- The existing `purchase_history` view filters to `completed` and uses a date
  fallback; current ingestion emits `placed`, and the accepted Purchase Date is
  delivery date. The new graph must select its semantics deliberately.
- Brands/categories exist in the schema but their population is not implemented
  in the current ingestion path. At this initial stage, private database row counts
  had not been inspected; the later actual-data audit is recorded below.
- The operator subsequently said: “Can use the actual data in the data folder.
  There is nothing sensitive.” Actual-data inspection is now authorized for graph
  modeling. This permission changes the investigation inputs, not the ticket's
  completion status; record-level validation was still pending at that point.
- The operator then clarified the purpose: “keep track of how frequent is certain
  item being purchase and make predictions in to the future.” A read-only SQLite
  profile found 41 products in current orders, 20 appearing in at least two distinct
  orders, and 7 in at least five. These are recorded-order counts, not proof of
  forecast eligibility, fulfilled delivery, complete history, or resolved product
  identities. No data or code was changed.
- The operator subsequently said “Can use delivery date,” accepting it as Purchase
  Date for frequency and predictions. All 15 current orders have this value; it is
  the scheduled slot start. `ordered_at` remains unknown, and the earlier proposed
  email-time estimate is unnecessary for the chosen series.
- Actual-data validation is complete: 1 retailer, 41 provisional listings/products,
  110 item lines, no brands/categories/aliases, and 2 same-product repeated-line
  groups. An observed order has 9 Item nodes but 8 Listings/Products, illustrating
  why line facts must be retained while analytic occurrences are grouped.
- Archive comparison found 17 unique source orders, 15 matching SQLite and 2
  archive-only. SQLite has 17 source rows: 15 parsed/linked and 2 failed/unlinked.
  No failed messages were repaired or imported. All 15 orders fall on distinct
  Singapore delivery days, so 20 products have at least 2 days and 7 at least 5.
  The partial history and provisional identities must be visible in later
  analysis; these observations do not certify prediction accuracy.

### Model decision round one — answered

The operator asked to work through ticket 20. Delivery date, read-only actual-data
use, and the frequency/prediction purpose remain settled; do not reopen them.
The next independent decisions are:

1. **Core model and item identity.** Recommend Order → Order Revision → Order Item
   → Retailer Listing → Product, with Retailer and Source Message connections.
   Product means an exact variant/package: for example, 1 L and 2 L remain
   separate. Current listing mappings remain provisional; no automatic merging
   based on similar names. A later Product Family can connect related products
   without erasing their distinct histories. Decide whether that exact-product
   baseline fits the operator's intended meaning of “certain item,” or whether
   family-level frequency must be designed now.
2. **Eligible recorded purchases.** Recommend current `placed` and `completed`
   revisions with a known delivery date at or before the analysis date. Exclude
   cancelled/refunded/unknown from this analytic view, preserve them in the factual
   graph, and show future scheduled deliveries separately. All 15 existing orders
   are `placed`; a completed-only view currently has no eligible orders. Do not
   relabel confirmations as confirmed fulfillment.
3. **Occurrence counting.** Recommend preserving every Item line and quantity,
   counting one Product occurrence per logical Order, and using distinct Singapore
   delivery days for day-gap calculations. Keep order count, purchase-day count,
   and quantities separately available. The observed 9-line/8-product order
   illustrates the distinction. Multiple orders on one day would remain separate
   orders but provide one date in the daily interval series; this does not change
   today's data because all 15 orders have different delivery dates.

The operator answered: “Q1 implement product family / Q2 recommended / Q3
recommended.” Product Family therefore moves into the initial scope, and the
recommended eligibility and occurrence-counting rules are accepted. The earlier
proposal to defer Product Family is superseded. Forecast algorithm, minimum
history, calibrated uncertainty, and graph-rendering/library choices remain
downstream; no five-day threshold or median-gap formula is accepted by this round.
No source code, data, or runtime changes accompany this recorded decision.

### Family decision round two — accepted

The family scope change introduces two independent questions, presented to the
operator with recommendations:

1. Group the same product type across brands and package sizes (recommended),
   combine only package sizes within one brand/variant, or use broad groups such
   as all milk and milk alternatives?
2. Suggest families then review before use (recommended), assign every family
   manually, or automatically use inferred families with corrections later?

These questions refine what a family means and which assignments can affect
frequency. They do not ask again whether families belong in the initial scope.

The operator replied “Ok” to both recommendations. Product-type families across
brands/sizes and review-before-use membership assignment are therefore accepted.
No further model clarification is needed before preparing the implementation.

Read-only name-pattern inspection found possible cross-prefix dairy groupings,
same-prefix dairy flavor differences, and infant-care names sharing fit ranges.
These are candidate relationships, not confirmed Families or brand identities.
No exact size-only candidate groups appeared after removing quantity/unit wording.
The only two populated package quantities match fit-weight-range endpoints, so
they must not be used as verified package mass for family quantity normalization.
No family assignments, parser fixes, data corrections, or migrations were made.

### Subsequent UI scope addition

The operator requested a UI to visualize the knowledge graph. This is recorded
as required Graph-page, review, and timeline scope in ticket 21 and the specification.
It does not reopen the resolved entity/date/counting decisions in this ticket.

## Answer

The initial knowledge graph model is settled:

1. Preserve Order → Revision → Item → Listing → Product → Product Family, with
   Retailer and Source Message evidence. Family grouping never merges exact
   Products or rewrites historical Items.
2. Families group the same product type across brands/sizes, with explicit
   boundaries. Suggestions become active only after review; preserve origin,
   decisions, and membership history. Current analysis uses the selected accepted
   membership snapshot over historical purchases, and records that interpretation.
3. Use delivery date as Purchase Date in Singapore. Include current placed/completed
   past/current dated orders, preserving excluded factual records and future orders.
   Scheduled delivery does not certify arrival; missing dates receive no fallback.
4. Preserve line facts; count unique Product/Family occurrences per logical Order
   and distinct delivery days for intervals. Retain quantities by exact Product
   unless validated conversions support aggregation.
5. Keep SQLite authoritative and graphs/timelines rebuildable. Expose unassigned
   Products, provisional identities, and known data gaps. Predictions remain a
   later derived feature with separate algorithm/accuracy decisions.

The [accepted specification](../specs/shopping-knowledge-graph-model.md) records the
model and acceptance scenarios; [ticket 21](21-build-product-family-foundation.md)
defines the first implementation deliverable. Ticket 19's Chat remediation remains
deferred. No application code, schema, database contents, or running service was
changed to resolve this ticket.
