# Check homelab Ollama readiness

Parent: ../map.md
Type: task
Status: resolved
Assignee: Codex

## Question

What is already installed and usable on the existing homelab, and which concrete gaps must the Ollama setup plan address?

## Scope

Perform a read-only inventory through an operator-identified host/access method. Check Ubuntu version, RAM and available disk, NVIDIA GPU/driver availability, Ollama version/service status if installed, installed model names, and the shopping service's ability to reach a host-local model endpoint. Record only the minimal non-sensitive capability findings.

The operator reports the application deployment pipeline and Tailscale page access are working; these are the starting baseline. Do not bootstrap the host, change Tailscale, install drivers/Ollama, download a model, restart services, read private receipts/database contents, or send household prompts during this ticket. If host access is unavailable, provide a short read-only inventory for the operator to run.

## Comments

- This task unblocks the model/service configuration decision. It does not constitute authorization for implementation or deployment while Wayfinder planning is active.
- Claimed for read-only inventory. The scoped repository documentation contains no concrete homelab SSH destination/access command. Awaiting the operator's host/access method before attempting a connection; no remote checks have run. Do not infer the host from unrelated SSH configuration or inspect private application data.
- The operator supplied an SSH destination. The host was reachable with strict host-key checking, but non-interactive SSH authentication failed (`Permission denied (publickey,password)`). No inventory commands executed remotely and no readiness facts are verified. Continue after the operator enables an existing SSH key or supplies the output of read-only inventory commands run in their own SSH session; do not request passwords/private keys or change host authentication automatically.

## Inventory — operator-provided command output

The following observations come from output the operator pasted from the requested
read-only commands. They were not independently collected through agent SSH.

| Check | Observed result |
|---|---|
| OS | Ubuntu 24.04.4 LTS |
| CPU | Intel Core i5-3570K @ 3.40 GHz |
| System memory | 15 GiB total reported; 10 GiB available, 5.0 GiB used |
| Swap | 4.0 GiB total; 388 KiB used |
| Disk | Root filesystem 233 GB, 182 GB available; `/opt` and `/var/lib` use the same filesystem |
| GPU | NVIDIA GeForce RTX 3060, 12,288 MiB total, 11,579 MiB free at inspection |
| NVIDIA driver | 595.84; `nvidia-smi` responded successfully |
| Ollama | Installed, version 0.30.10 |
| Ollama service | `ollama.service`: active/running as `ollama` |
| Shopping service | `shopping-web.service`: active/running as `shopping-app` |
| Loaded models | `ollama ps` returned only its header: none loaded at inspection |
| App account connectivity | `shopping-app` successfully listed installed models using explicit `http://127.0.0.1:11434` |
| Ollama listener | `ss` reports `127.0.0.1:11434`; loopback-only at inspection |

Installed models reported by `ollama list`:

- `gemma4:12b-hermes` — 7.6 GB
- `qwen3.5:9b` — 6.6 GB
- `gemma4:12b` — 7.6 GB
- `qwen3.6:27b` — 17 GB
- `qwen3:4b` — 2.5 GB

Use the actual installed tags above in ticket 12; do not assume the older plan's
quantization-suffixed tags exist or infer exact quantization/template from size.
No model has been loaded, benchmarked, or tested for tool calling in this ticket.
Free VRAM and on-disk model sizes alone do not establish full-GPU fit at 8K context.
The reported 722 MiB free system RAM is not the available-memory figure: the output
reports 10 GiB available including reclaimable cache.

## Answer

The operator supplied the remaining read-only results: Ubuntu 24.04.4 LTS,
successful model listing as `shopping-app` against the explicit loopback endpoint,
and an Ollama listener at `127.0.0.1:11434`. The `0.0.0.0:*` peer column in `ss`
does not mean the service is bound to all local interfaces. The optional LSB-module
warning did not prevent the Ubuntu release from being reported.

The inventory is sufficient to resolve this ticket and unblock ticket 12. Reuse the
existing Ollama 0.30.10 installation, NVIDIA driver, installed model candidates, and
running services; no initial Ollama installation/download is shown to be necessary.
The configured endpoint for planning is `http://127.0.0.1:11434`. Browser access
continues through the existing private Tailscale application path, not the model API.

This verifies the inventory through operator-provided output, not end-to-end chatbot
readiness. Model selection, actual GPU residency with context, generation/tool-call
quality, latency, and restart behavior remain acceptance work. The account-level
probe does not prove connectivity inside a differently sandboxed systemd unit;
verify the eventual application integration there. Exact Ollama service options,
boot enablement, and restart policy remain configuration checks for ticket 12.

No host software, model, service, network configuration, or application data was
changed. No inference or private-data request was performed. Implementation remains
paused while the remaining planning tickets are resolved.
