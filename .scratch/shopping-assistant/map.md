# Working Shopping Assistant

Label: wayfinder:map

## Destination

Deliver a trustworthy working Shopping Assistant in the existing FastHTML application: a dedicated Chat page for one trusted household operator, durable conversations, streamed and cancellable answers with reconnect recovery, and read-only tools over currently implemented SQLite shopping facts. It supports local Ollama and one explicitly selected OpenAI-compatible endpoint, exposes compact tool evidence, and passes a fixed safety and correctness evaluation.

## Notes

- This map carries execution and verification through the destination; it does not stop at a specification.
- Every session should consult `grilling` and `domain-modeling`; use `research` for external API facts, `prototype` for interaction decisions, and the repository's testing, review, and browser-verification skills during implementation.
- SQLite remains authoritative. The model never executes SQL or arbitrary Python, and deterministic facts are returned only through bounded application-owned tools.
- The first release is read-only and covers existing products, orders, purchase history, quantities, and prices. It must refuse unavailable analytics rather than infer them.
- Chat is a dedicated sidebar destination, not a global floating widget.
- Provider selection is explicit and fixed per conversation. Ollama is the local option; the cloud option is one configured OpenAI-compatible endpoint. There is no automatic cloud fallback.
- Once a cloud endpoint is selected, it receives the same bounded conversation context and structured tool results as Ollama. Raw emails, archive paths, credentials, and unrestricted database context are never model inputs.
- Conversations are durable and support create, list, resume, rename, and confirmed deletion.
- Responses stream with visible working state, compact tool activity, a Stop control, and reconnect recovery.
- Acceptance uses a fixed evaluation set covering factual selection, schema-valid tools, ambiguity, unsupported requests, prompt injection, timeout, cancellation, and reconnect.

## Decisions so far

<!-- Resolved child tickets are indexed here. -->

- [Define the read-tool and evidence contracts](issues/02-define-read-tools.md): Use four bounded read-only tools over current product and order facts, with deterministic ambiguity handling and claim-level local evidence links.

## Not yet specified

- Concrete implementation tickets and file boundaries will emerge after the provider, tool, lifecycle, interaction, transport, and evaluation decisions converge.
- Deployment configuration, credential provisioning, and operational checks will become precise after the provider contract and cloud-disclosure experience are resolved.

## Out of scope

- Shopping-list or other write tools in the first release.
- Replenishment predictions, co-purchase analytics, graph traversal, or other not-yet-implemented analytical facts.
- Multiple named users, authentication, or per-user conversation ownership.
- A floating assistant available on every screen.
- Automatic failover from Ollama to a cloud provider.
- Giving any model raw archived email content or direct database access.
- Telegram or other chat surfaces outside the FastHTML application.
