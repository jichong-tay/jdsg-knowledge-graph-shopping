# Define receipt-date extraction

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex

## Question

Which explicit date in the supported receipt layouts represents the purchase, and how should the deterministic parser extract and store it so the Shopping Assistant can answer date-based questions accurately?

## Scope

- Inspect operator-provided private samples locally using privacy-preserving structural checks. Keep raw email, personal data, exact private dates, and private filenames out of prompts, tool output, documentation, and fixtures.
- Establish whether the source explicitly supplies a receipt, invoice, order, or delivery date. Do not silently substitute a delivery date or email timestamp for a purchase date.
- Decide the meaning of the stored date, whether an existing field is suitable, and whether date-only values can be represented without inventing a time or timezone.
- Specify deterministic extraction, conflicting/missing date behavior, and independent synthetic fixture coverage. If the supplied layout lacks an explicit receipt date, record that limitation rather than guessing.
- Plan any parser-version change and reparse of archived inputs while preserving exact raw bytes and append-only historical facts. A schema change, if needed, must be a new migration through `shopping migrate`.
- Describe implementation and verification work for the rollout plan; do not implement it during Wayfinder.

## Comments

- The operator approved adding receipt-date extraction to the plan and identified a local private sample collection for inspection.
- The existing parser currently leaves `ordered_at` null and separately extracts a delivery time and the original email's timestamp. Their meanings must remain distinct until this decision is resolved.

### Preliminary private-sample inspection

- A deterministic structural scan found five `.eml` samples, each with a single HTML MIME body and no attachments or nested messages.
- All five contain a delivery-slot label followed by a date-shaped value. The allowlisted label scan did not establish a separate receipt, invoice, or order date. This is a limited structural finding, not proof that no such date exists anywhere in the documents.
- This matches the existing adapter: `app/email/parsers/fairprice.py` extracts the delivery slot in `_parse_delivery_at` and leaves `ordered_at` null. The original message timestamp is separate metadata.
- Before specifying extraction, clarify whether the operator intends the delivery date for purchase-history display or expects a distinct receipt/purchase date. Do not change a field's meaning based on the informal description of these emails as receipts.

## Answer

The operator explicitly chose: “no need to differential delivery date. just use that as purchase date”. This resolves the earlier source-date question as an application convention: the Shopping Assistant and purchase-history tools use the already extracted delivery date and label it **Purchase date**, without a separate delivery-date explanation in normal answers.

Use the existing `delivery_at` value for the planned `purchase_date` tool field and purchase-date ordering. Retain UTC storage and display the calendar date in Asia/Singapore, consistent with the project's existing date presentation rules. This convention does not assert a distinct receipt-issue, order-placement, or payment timestamp.

No new parser field, schema migration, reparse, separate receipt-date extractor, or rewrite of historical facts is needed for these supported samples. Do not backfill `ordered_at` from `delivery_at`. The existing rule against inventing missing values still applies; do not silently fall back to the email timestamp.

The implementation plan and evaluation set should verify that tool outputs and date-based answers use the extracted delivery date, that source-email dates cannot override it, and that all current receipt items are included regardless of the parser's `placed` status. These are future implementation checks; no application code changed during this decision.
