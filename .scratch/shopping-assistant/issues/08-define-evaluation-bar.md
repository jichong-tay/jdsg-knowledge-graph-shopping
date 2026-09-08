# Define the assistant evaluation bar

Parent: ../map.md
Type: grilling
Status: resolved
Resolution: merged-into-09
Blocked by: 02, 06, 07, 11

## Question

Which fixed cases, fixtures, scoring rules, latency and token limits, and zero-tolerance safety failures must the selected homelab Ollama model and application pass before the Shopping Assistant MVP is considered trustworthy?

## Comments

- Evaluate one selected local model through the four receipt-data tools, plus the existing Tailscale-hosted Chat page. Cloud-provider conformance is deferred. Include persistence/restart, Stop/retry/reconnect, and evidence checks; reuse the working deployment pipeline.

## Answer

The operator agreed to skip a separate evaluation-planning exercise and carry a
short acceptance checklist into [ticket 09](09-plan-implementation-slices.md).
This closes the standalone ticket as merged, not as completed evaluation or a waiver
of factual, security, lifecycle, or homelab verification. No separate grilling round
or elaborate scoring framework is required. Implementation remains paused.
