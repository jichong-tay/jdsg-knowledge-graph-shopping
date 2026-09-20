# Verify the homelab Shopping Assistant MVP

Parent: ../map.md
Type: task
Status: open
Blocked by: 17

## Goal and contracts

Verify the already incrementally deployed Assistant through the actual application
service and private Tailscale route. This is not the first allowed deployment or a
model benchmark. Read the [shared plan](../plans/chat-mvp.md), ticket
[09](09-plan-implementation-slices.md) acceptance checklist, ticket
[12](12-define-provider-operations.md), and `docs/DEPLOYMENT.md`.

## Files and boundaries

- Extend `tests/integration/test_ollama_smoke.py` only for the small final synthetic
  flow; retain fake-provider/isolated CI coverage from earlier tickets.
- Extend `tests/test_deployment.py` for any missing compatible-helper, rollback and
  health regression checks. Do not create another deployment architecture.
- Update `docs/DEPLOYMENT.md`, README, and current-behavior sections of
  `docs/MVP_PLAN.md`. Record content-free results in
  `.scratch/shopping-assistant/homelab-acceptance.md`.
- Change service/runtime code only for observed defects, with proportional tests.
  No model installation, auto-updater, public listener, or infrastructure expansion.

## Verification steps

- [ ] Record deployed green-main SHA, Ollama version/model digest, configured bounds,
  and effective app/Ollama service settings. Verify loopback model listener, private
  app origin, boot/restart policies, one worker/model/request, and access from the
  actual application service context. Do not infer these from `ollama list` alone.
- [ ] Use an isolated temporary development database containing synthetic purchase
  facts, not production synthetic-fixture mode or fake rows in the household DB.
  Verify model → tool → result → grounded answer through the deployed code path.
  Keep any separate temporary test process loopback-only and do not disrupt Tailscale
  publication or other services to make it accessible.
- [ ] Exercise a small fixed set: latest order/details, product history with Purchase
  Date and cents, ambiguity, missing product, pagination/partial completeness,
  unsupported analytics and malicious product text. Require no invented facts or
  evidence in those checks. Do not require a 30–50-case tournament or repeated models.
- [ ] Check cold and warm requests separately, near-8K input accounting, output/work
  limits, peak GPU use and `ollama ps` placement. Require no OOM and respect the
  180-second ceiling; report actual responsiveness, not an assumed tokens/sec rate.
  Use the agreed 4K fallback only if measured offload/instability warrants it.
- [ ] Through the normal Tailscale UI, verify an operator-selected purchase-history
  question, evidence navigation, reload/saved Conversation, Stop/Retry, reconnect,
  and two-tab state. Keep private answers out of logs, committed screenshots and
  reports. Do not copy raw email into prompts or public services.
- [ ] Verify service restart leaves active work interrupted without replay; Ollama
  outage leaves Orders/saved Conversations usable and core readiness independent.
  Use scoped fault injection or an isolated instance where shared Ollama users could
  be affected. Never kill host processes or alter unrelated workloads casually.
- [ ] Verify a disposable failed-deployment rollback drill with isolated data, then
  record which real helper/service behaviors were checked versus simulated. Preserve
  verified backups and recovery records; do not claim a destructive rollback drill
  on real household data is necessary. Keep schema/config/helper compatibility intact.
- [ ] Deploy small fixes through the normal checks/green-main/backup pipeline as
  they become ready. No batch-release gate. Finish shared wheel, test, secret and
  review checks for any code changes, and update documentation to actual results.

## Completion evidence

Record pass/fail/not-run for each check plus safe version/timing/GPU/error metadata.
If host access or an operator-only action is unavailable, state the exact remaining
check and leave this ticket open; unit tests do not prove host readiness. Resolve
only when the integrated MVP is usable and required checks have actually run.
