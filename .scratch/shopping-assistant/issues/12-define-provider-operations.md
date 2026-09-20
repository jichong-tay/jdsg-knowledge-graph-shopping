# Define provider configuration and operational checks

Parent: ../map.md
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: 06, 13

## Question

How should the operator install or reuse Ollama on the already deployed homelab, choose and validate a model, connect the shopping app to it, and diagnose availability while preserving fixed conversation selections?

## Scope

- Use verified host/GPU/driver/memory and existing Ollama inventory to choose a model, context size, concurrency, and installation steps. Existing hardware notes are planning context, not a fresh machine audit.
- Specify native Ollama service startup and restart behavior, and use its existing installation when suitable. Keep the model API private on host loopback; browsers access the shopping app through the operator's working Tailscale route.
- Specify app-to-Ollama endpoint/model configuration, timeouts, availability errors, and configuration-change behavior for existing conversations.
- Define privacy-safe health output and a synthetic tool-calling smoke test before any operator-run private-data acceptance check.
- Produce incremental setup and verification requirements for the existing deployment pipeline. Do not install software, download models, modify services, or deploy during this planning ticket.
- Cloud setup and credentials are outside this MVP. Do not repeat the completed app deployment or Tailscale setup.

## Comments

- Graduated from the map's operational fog after the provider-selection and cloud-disclosure decision was resolved.
- Follow [Define provider selection and cloud disclosure](03-define-cloud-disclosure.md); this ticket must not silently broaden its permissions or reopen its settled choices.

- Scope narrowed to Ollama-only homelab operations after the operator confirmed that the hosted page and Tailscale/deployment pipeline are already working.

- [Ticket 13](13-check-homelab-ollama-readiness.md) is resolved from operator-run inventory: Ubuntu 24.04.4, RTX 3060 12 GB with responding NVIDIA driver, Ollama 0.30.10 active as `ollama`, shopping service active as `shopping-app`, and successful app-account access to `http://127.0.0.1:11434`. The model listener is loopback-only. Reuse this installation; do not plan a reinstall or assume the older quantization-suffixed model tags exist. Actual installed candidates and available resources are recorded in ticket 13. No model was loaded or benchmarked. Verify effective service options/boot/restart policy and eventual in-service connectivity without confusing the inventory with completed inference acceptance.

## Grilling round one — accepted

The operator accepted Q1–Q4, briefly requested automatic Ollama updates, then
explicitly reversed that choice: “no automatic ollama updates at all”. The original
manual-only Q5 policy is therefore selected. Implementation remains paused.

Keep this a small native deployment with the existing environment file, services,
and Tailscale route. No configuration dashboard, provider registry, installation
wizard, model manager, or new infrastructure is proposed. The runtime limits and
private-only access boundary are already accepted.

1. **First model to validate:** recommend the already installed `gemma4:12b`, using the accepted 8K context/768 output/single-attempt limits. Start with the standard installed tag rather than assuming the custom `gemma4:12b-hermes` template is compatible. This is a first test candidate, not a claim of measured accuracy or fit. If context causes offload/instability, test the agreed 4K setting; if still unsuitable, manually evaluate the already installed `qwen3.5:9b`. Never silently switch models for an existing Conversation. Do not use the larger 27B model for this MVP or delete any installed models.
2. **Ollama outage:** recommend leaving Orders, saved Conversations, and the rest of the core app usable when Ollama is unavailable. Show a separate assistant-unavailable state with safe diagnostics; prohibit new generation until usable again, without losing drafts. Keep core application/schema health separate from model availability, so an Ollama outage alone does not trigger database/application rollback. The first chatbot rollout still requires an explicit successful synthetic model/tool smoke check, not merely a green core health endpoint. Routine health checks must not load a model or generate text.
3. **Boot and crash recovery:** recommend reusing the two existing native systemd services, ensuring they start at boot and have bounded restart-on-failure behavior. Inspect effective units/options before changing anything during implementation. Keep their lifecycles independent: the Python app does not install, start, or restart Ollama, and Ollama failure does not stop the whole shopping app. A service manager restarting a crashed process must not replay an interrupted Response Attempt. No new supervisor or daemon.
4. **Model loading:** recommend on-demand loading on the first real request and keeping the model warm for 5 minutes after use, then allowing it to unload. Show working/loading feedback; the accepted 180-second attempt budget includes loading. Do not add startup prewarming, scheduled pings, or always-resident loading. This favors leaving GPU resources available when Chat is idle over eliminating the first-request delay.
5. **Updates:** recommend deliberate operator-managed Ollama/model updates, not automatic upgrades/downloads on app startup, request, health check, or deployment. Reuse the installed server version for the first validation unless a measured incompatibility/security issue requires a separately reviewed change. Record the tested server version, model tag/digest, context, and small synthetic check results. Retest after an update; do not claim an alias guarantees immutable model contents. App deployment and rollback do not change Ollama binaries or model files.

Source check: Ollama's [Gemma 4 tags](https://ollama.com/library/gemma4/tags)
list `gemma4:12b` at 7.6 GB with the same displayed digest as the operator inventory;
the [model page](https://ollama.com/library/gemma4) lists tool support. This does not
validate the actual host's tool-calling quality or the custom Hermes variant.
Ollama's [FAQ](https://docs.ollama.com/faq) documents the configurable keep-alive
behavior. All five recommendations above are accepted under the operator's latest answer.

## Model decision — supersedes round-one Q1

After reviewing [local model research](../research/local-model-selection.md), the
operator selected the already installed `qwen3.5:9b` as the MVP default, with
thinking disabled (`think: false` in the native Ollama request). Keep the accepted
8K context, 768 output-token limit, and single active attempt. Do not require a
Gemma comparison, repeated model tournament, or new downloads before implementation.
Use the small synthetic integration checks already required by ticket 09; revisit
model choice only after a concrete compatibility, correctness, memory, or latency
problem. The selection is a decision, not a claim that inference has passed.

## Automatic-update proposal — withdrawn

The operator withdrew automatic updates before accepting the proposed schedule or
recovery workflow. Remove that work from scope: no update timer, recurring task,
automatic installer, maintenance coordinator, or automatic version-rollback system
is required. None was created or run. Ollama and model updates are deliberate
operator actions only.

## Existing configuration/deployment constraints

Read-only inspection confirms that `Settings` loads validated `SHOPPING_*` environment
values and the web service already uses `/etc/shopping-app/app.env`; reuse those
patterns. Core `/api/health` does no external inference and its `ready` flag gates
code/database rollback. The currently installed deployment helper's repository
version permits exactly five `SHOPPING_*` entries and validates them before checkout.
Adding new configuration keys first would block that deployment path. Ticket 09
must sequence a backwards-compatible helper/configuration change and preserve
rollback compatibility; do not simply append new keys during setup. No changes
were made to the deployed helper or environment.

## Answer

- Reuse the inventoried Ollama installation and private `http://127.0.0.1:11434` endpoint. Select installed `qwen3.5:9b` with thinking disabled as the MVP default under ticket 06's accepted limits. No prerequisite model comparison; verify it as part of normal implementation acceptance. Try the accepted 4K context only if memory/offload problems require it, and revisit model choice only for a concrete failure. No automatic model switching, downloads, or removal of other installed models.
- Keep configuration small and environment-based, using the existing Settings pattern and environment file. Configure the explicit app origin, local endpoint, selected model, and accepted limits; do not add a settings dashboard/provider registry. Deployment origin values are collected from the actual installation, not guessed or committed with private host details. Preserve fixed endpoint/model identity for Conversations under ticket 03.
- Reuse independently running native services with boot startup and bounded crash recovery; inspect their effective configuration during implementation. Keep one loaded model/one parallel request, loopback binding, and local-only inference. The web app does not administer Ollama, and service restart never replays interrupted questions.
- Load on demand with a five-minute keep-alive. Cold loading consumes the existing response deadline. Routine health checks do not warm the model, generate text, or download anything.
- Report assistant availability separately from core app/schema health. An Ollama outage leaves Orders and saved Conversations readable and does not alone cause app/database deployment rollback. Show safe availability/configuration failures, preserve drafts, and use the accepted explicit Retry behavior. Diagnostic output contains version/model identity, availability, and safe error categories—not private prompts, results, credentials, or exception internals.
- Before the first chatbot rollout, run a small bounded synthetic tool-calling/evidence check through the actual application service context, alongside GPU/context-fit, latency, and restart/reconnect checks in ticket 09. Record tested Ollama version, model tag/digest, and context. Model metadata or core health alone is not inference acceptance. This defines future verification; no model test ran during planning.
- Ollama server and model updates are manual only. Do not update on a schedule, startup, request, health check, or app deployment. Retest deliberately updated versions; app rollback does not replace Ollama or model files.
- Ticket 09 must handle the existing deployment helper's strict environment validation before adding Chat settings, retaining in-place deployment and database-aware rollback. Keep the implementation understandable with existing libraries and small functions; no updater infrastructure or separate operational platform.

The operational design is resolved; actual configuration, service checks, model
validation, and implementation remain work for ticket 09's slices. No application
code, host configuration, or deployment has changed, and no new glossary term is needed.
