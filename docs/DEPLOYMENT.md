# Ubuntu Homelab Deployment

This deployment is intentionally small. It matches the actual workflow:

~~~mermaid
flowchart LR
    M["Develop on MacBook"] --> G["Push to public GitHub"]
    G --> C["GitHub-hosted CI passes"]
    C --> D["Run deploy-shopping with that commit SHA"]
    D --> U["Ubuntu app updated in place"]
    U --> T["Private access through Tailscale Serve"]
~~~

There is one application checkout, one virtual environment, one SQLite database,
and one running web service. This is **not** blue/green deployment. An update stops
the web service briefly while it backs up the database and updates the same checkout.
That trade-off is appropriate for a personal homelab with fewer than five users.

## Two environments

| Environment | Where it runs |
| --- | --- |
| `development` | MacBook development and isolated GitHub-hosted checks |
| `production` | Ubuntu homelab |

There is no staging or test application environment. Automated tests use temporary
directories under the development profile.

## What is automated

The repository contains two scripts:

- `deploy/bootstrap-ubuntu.sh` provisions the host once.
- `deploy/deploy-ubuntu.sh` is installed as `deploy-shopping` for every later update.

The scripts automate repeatable machine work. This document still explains what
they change, how private data is protected, and where to look when something fails.
Tailscale's first HTTPS-consent step and choosing a commit whose CI passed remain
deliberate human actions.

The operator now reports a working homelab deployment pipeline and Tailscale access
to the hosted application. The chatbot MVP will reuse that installation and access
path; it does not require repeating the bootstrap or Tailscale setup below. This
report does not independently verify every repository bootstrap/rollback procedure.

The operator-run [read-only inventory](../.scratch/shopping-assistant/issues/13-check-homelab-ollama-readiness.md)
reports Ubuntu 24.04.4 LTS, a responding RTX 3060 12 GB/NVIDIA driver, Ollama 0.30.10
already installed, and active Ollama/shopping services. The `shopping-app` account
successfully listed models through `http://127.0.0.1:11434`, and the observed model
listener is loopback-only. Reuse the existing installation; model fit, tool calling,
effective service settings, and eventual in-service application access still need
validation. Browsers continue using the existing Tailscale application URL, not the
model API. No Ollama setup or deployment change was performed during planning.

The accepted Chat operations plan reuses these independent services and loads the
selected model on demand with a five-minute keep-alive. Assistant availability will
be reported separately from core app/schema readiness so an Ollama outage alone
does not trigger app/database rollback. A successful bounded synthetic model/tool
check is still required for the first chatbot rollout. Ollama and model updates
are **manual only**: no updater timer, automatic downloads, or upgrade step in app
startup/deployment. These are planned behaviors, not installed changes; see
[ticket 12](../.scratch/shopping-assistant/issues/12-define-provider-operations.md).

### Incremental Chat rollout — planned

The operator wants frequent deployments to this experimental homelab, not a single
release after all Chat work is finished. Deploy coherent working increments after
the existing green-main CI/checks, including useful checkpoints within a ticket.
Brief restarts are acceptable; keep verified SQLite backup, migration, private
access and database-aware rollback. The host still uses `SHOPPING_ENV=production`;
experimental use does not turn off its runtime or data safeguards.

The [implementation sequence](../.scratch/shopping-assistant/implementation-plan.md)
is purchase history tools, Qwen backend, saved Conversations, Chat UI/recovery, then
final host verification. Early backend/schema increments can deploy without a Chat
navigation item. The last ticket verifies accumulated deployments rather than
blocking all earlier releases.

Before adding Chat environment keys in ticket 15, first deploy the backwards-
compatible helper/bootstrap-validator preparation with the original environment.
The existing helper checks exactly five keys before checkout; merely changing app
code cannot make that installed helper accept new settings. Verify the successfully
installed helper and compatible rollback/recovery behavior, then add settings and
deploy the backend. Record the actual origin locally; never use a wildcard to avoid
configuration. No helper or host changes have been performed by this planning work.

## Accounts and directories

Use the existing administrator login plus one non-login service account:

| Identity | Purpose |
| --- | --- |
| Existing administrator | SSH, choose a release, and run `sudo deploy-shopping` |
| `shopping-app` | Run migrations and the web process; own private runtime data |

There is no second non-login deployment account because the homelab is not a GitHub
Actions runner. GitHub-hosted runners perform CI; repository pull requests never run
inside the home network.

The bootstrap script creates:

~~~text
/opt/shopping-app/          application checkout and .venv, owned by the administrator
/var/lib/shopping-app/      private session key, database, and archived email, owned by shopping-app
/var/backups/shopping-app/  root-only pre-deployment SQLite backups
/etc/shopping-app/app.env   production configuration
~~~

To keep the first helper understandable, it supports these standard paths and port
8000 only. It fails clearly if path or port overrides are added; supporting custom
host layouts can be a later, deliberate change.

## Before the first installation

On the MacBook:

1. Commit and push the changes to `main`.
2. Wait for the GitHub check named **Python 3.14 checks** to pass.
3. Copy the full 40-character commit SHA. `git rev-parse HEAD` prints it locally.

The SHA is required so the Ubuntu machine deploys the exact code that passed CI,
not whichever commit happens to be newest a few seconds later.

## One-time Ubuntu setup

Connect using the normal administrator login. While at home, the fixed LAN address
can be used for SSH; Tailscale SSH is also fine.

If you want the compact setup path, replace the placeholder with the full 40-character
green SHA and run this from that administrator shell. It downloads the script pinned
to the reviewed commit, opens it for inspection, and runs it only after you quit
`less`; the script then clones the application repository itself:

~~~bash
RELEASE_SHA=REPLACE_WITH_40_CHARACTER_GREEN_MAIN_SHA; curl --fail --location --proto '=https' --tlsv1.2 "https://raw.githubusercontent.com/jichong-tay/jdsg-knowledge-graph-shopping/$RELEASE_SHA/deploy/bootstrap-ubuntu.sh" -o /tmp/bootstrap-ubuntu.sh && less /tmp/bootstrap-ubuntu.sh && sudo bash /tmp/bootstrap-ubuntu.sh "$RELEASE_SHA"
~~~

Do not pipe an unreviewed URL directly into `sudo bash`. If `curl` is not already
available, use the full clone-and-review procedure below (or install `curl` first).

Install Git, obtain the exact green revision, and run its bootstrap script:

~~~bash
set -euo pipefail

sudo apt update
sudo apt install -y git

if [[ ! -d $HOME/shopping-setup/.git ]]; then
  git clone https://github.com/jichong-tay/jdsg-knowledge-graph-shopping.git \
    "$HOME/shopping-setup"
fi
cd ~/shopping-setup
test "$(git remote get-url origin)" = \
  "https://github.com/jichong-tay/jdsg-knowledge-graph-shopping.git"
setup_status=$(git status --porcelain)
test -z "$setup_status"
RELEASE_SHA=REPLACE_WITH_40_CHARACTER_GREEN_MAIN_SHA
[[ $RELEASE_SHA =~ ^[0-9a-f]{40}$ ]]
git fetch origin main
git cat-file -e "$RELEASE_SHA^{commit}"
git merge-base --is-ancestor "$RELEASE_SHA" origin/main
git checkout --detach "$RELEASE_SHA"
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
setup_status=$(git status --porcelain)
test -z "$setup_status"
sudo bash deploy/bootstrap-ubuntu.sh "$RELEASE_SHA"
~~~

The script:

1. installs the small Ubuntu prerequisites;
2. creates the `shopping-app` service account and private directories;
3. installs pinned `uv` 0.12.3 and Python 3.14;
4. checks out the requested commit at `/opt/shopping-app`;
5. installs locked production dependencies;
6. installs the production environment file and systemd units;
7. migrates a temporary empty database and atomically promotes it, starts the web
   service, and waits for ready health;
8. installs `/usr/local/sbin/deploy-shopping` for later releases.

It is safe to inspect [the bootstrap script](../deploy/bootstrap-ubuntu.sh) before
running it. It uses `sudo` because package installation, Unix accounts, `/opt`,
`/etc`, and systemd are host-level changes. Application dependency builds run as the
normal administrator, while the application runs as `shopping-app`, not root.
If setup stops before creating the database, rerun the same command: the script can
resume its clean partial checkout. If it stops after creating the database, the
installed `deploy-shopping` helper can safely retry the same SHA. Never delete a
database merely to make setup run again.

### Enable private browser access

The application itself listens only on `127.0.0.1:8000`. With Tailscale already
connected, run once:

~~~bash
sudo tailscale serve --bg http://127.0.0.1:8000
sudo tailscale serve status
~~~

Open the HTTPS `.ts.net` address that Tailscale prints. The first invocation may
show a consent URL for enabling tailnet HTTPS certificates.

Do not bind the app to the fixed LAN address, open port 8000 in UFW, add a router
port-forward, or use Tailscale Funnel. The fixed LAN address is only an SSH/recovery
route. The app has no separate login yet, so every identity permitted by the
Tailscale policy to reach this endpoint can read the household data.

## Every later deployment

The MacBook flow is always the same:

~~~text
develop -> test locally -> commit -> push -> wait for GitHub CI -> copy the commit SHA
~~~

Then SSH to Ubuntu and run one command:

~~~bash
sudo deploy-shopping REPLACE_WITH_40_CHARACTER_GREEN_MAIN_SHA
~~~

The helper performs an **in-place** deployment:

1. refuses local changes and verifies that the SHA belongs to `origin/main`;
2. stops the web service, causing brief downtime;
3. creates and verifies a root-only SQLite backup;
4. checks out the requested commit and runs `uv sync --locked --no-dev`;
5. runs the packaged database migrations as `shopping-app`;
6. starts the web service and requires `/api/health` to report `ready: true`;
7. on an ordinary command failure or termination signal, restores the previous
   commit and database backup.

Backups are retained under `/var/backups/shopping-app`. Failed database files are
moved into a timestamped root-only diagnostic directory rather than deleted. A
small `deployment-in-progress` record remains until the update or rollback finishes;
after a power loss it makes the next deployment stop instead of backing up a possibly
half-migrated database. This initial helper does not yet back up the raw email archive
to another device; an encrypted off-machine backup remains a later hardening task.

There are no release directories, `current` symlinks, parallel services, load
balancers, containers, or self-hosted runners.

## Useful operations

~~~bash
# Current service state
sudo systemctl status shopping-web.service --no-pager

# Recent application logs
sudo journalctl -u shopping-web.service -n 100 --no-pager

# Migration logs
sudo journalctl -u shopping-migrate.service -n 100 --no-pager

# Local readiness from the Ubuntu host
curl --fail --silent http://127.0.0.1:8000/api/health | jq

# Tailscale publication state
sudo tailscale serve status

# Currently deployed commit
git -C /opt/shopping-app rev-parse HEAD
~~~

### If Ubuntu loses power during deployment

Do not delete `/var/backups/shopping-app/deployment-in-progress`. The next ordinary
deployment will deliberately refuse to run. Recover with one command:

~~~bash
sudo deploy-shopping --recover
~~~

Recovery validates the root-owned record and backup, stops both possible writers,
restores the recorded old commit, locked environment, systemd units, and SQLite
database, then starts the old version and requires ready health. It removes the
record only after that succeeds. You can then deploy the desired green SHA again.

If recovery fails, leave the record and backups untouched and inspect:

~~~bash
sudo journalctl -u shopping-migrate.service -n 100 --no-pager
sudo journalctl -u shopping-web.service -n 100 --no-pager
sudo cat /var/backups/shopping-app/deployment-in-progress
~~~

If an ordinary deployment and its automatic rollback both report failure, follow
the same rule: leave the retained backup and diagnostic files untouched and inspect
the two journals first.

## Public repository boundary

A public learning repository is fine. Public visibility does not expose the LAN or
tailnet, but anything committed is public and may persist in clones and forks.

Never commit real email, SQLite files or sidecars, backups, `.env` files, OAuth
credentials, Telegram tokens, names, addresses, phone numbers, real order IDs, or
chat logs. Secret scanners help with recognizable credentials but do not recognize
ordinary household data. If a credential is committed, rotate it; deleting it in a
later commit is insufficient.

Keep CI on GitHub-hosted runners. GitHub warns that public-repository forks can try
to execute dangerous workflow code on a persistent self-hosted runner, which is why
the Ubuntu homelab is deliberately not registered as one.

## Why Docker and blue/green are absent

The application currently needs one Python process, one SQLite file, systemd, and
later a host Ollama process. Native installation makes those pieces easier to learn
and inspect. Docker can be reconsidered only if it solves a demonstrated problem.

Blue/green or immutable-release deployment mainly helps larger services that need
near-zero downtime and coordinated traffic switching. It complicates virtual
environment paths and SQLite migrations here. A short maintenance window with a
verified backup is a clearer starting point.

## References

- [GitHub warning for public repositories and self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)
- [GitHub secret-scanning scope](https://docs.github.com/en/code-security/reference/secret-security/secret-scanning-scope)
- [Tailscale Serve command](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [uv installation](https://docs.astral.sh/uv/getting-started/installation/)

### Chat environment preparation (ticket 15)

The shared `deploy/validate_config.py` validator is now used by bootstrap and the
installed deployment helper, including recovery. It accepts the original five
required settings and optional `SHOPPING_OLLAMA_URL`, `SHOPPING_OLLAMA_MODEL`, and
`SHOPPING_APP_ORIGIN`; it rejects unknown or duplicate keys and never sources the
file. The endpoint remains `http://127.0.0.1:11434`. Production origins must be HTTPS
origins without credentials, a path, query, or fragment.

Deploy this preparation with the existing environment first. Confirm the installed
helper invokes the shared validator and that the validator accepts a temporary
copy containing the intended optional settings before editing `app.env`. Retain
this preparation commit as the oldest compatible rollback target once optional
settings are present. For rollback to an older helper, restore the original
five-key configuration first; do not leave expanded settings with an incompatible
helper. Keep the normal backup and `--recover` workflow. Backend deployment and
actual model acceptance are separate checkpoints.

### Qwen backend checkpoint — 8 September 2026

Use preparation commit `55b9b7a` (which includes `446a48c` and `58df2b3`) as the
compatible preparation target, after green-main CI. It also records reviewed
skill integrity hashes and the synthetic URL fixture so the normal secret scan passes. Do not deploy `446a48c` alone: the next
commit fixes the validator's Ubuntu system-Python syntax and adds a regression
check. The current local implementation is not yet deployed. Keep the host's
existing environment unchanged until preparation is deployed and validated.

A local Python loop with an isolated synthetic SQLite database was exercised
against the homelab's existing Ollama API through a temporary SSH relay. No host
application code, configuration, purchase data, or service was changed. Account
access worked, but passwordless sudo was unavailable; no privileged deployment or
service-context check was performed. The relay adds latency and buffers transport
output; separate fake-transport tests cover streaming fragmentation and cancellation.

- Server: Ollama 0.30.10; model: `qwen3.5:9b`, Q4_K_M.
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`. <!-- pragma: allowlist secret -->
- Thinking disabled, 8,192 context, 768 output, five-minute keep-alive.
- Cold first probe: 38.58 seconds, correct tool data but missing evidence marker;
  correctly marked incomplete. No automatic repair request was made.
- After stronger evidence instructions, fresh warm attempts completed in 7.25 and
  5.42 seconds, each with one read tool and two generation requests.
- Local/provider input counts matched exactly: 951 before the tool and 1,388 after.
- Ollama reported context 8,192 and `size_vram == size == 5,880,141,577` bytes,
  indicating full GPU placement for this check.

This verifies the selected model and current local backend on synthetic data, not
production readiness, cold performance of the final prompt, or full Chat behavior.
After the backend is deployed, repeat the opt-in test in the service's effective
context, verify boot/restart options and cancellation, and record the deployed SHA.
Do not change or restart Ollama automatically, install/update models, or seed the
production database. Core health remains independent of model availability.

Token accounting deliberately gates Ollama versions: 0.30.10's source-verified
`_debug_render_only` Chat option supplies the full prompt; the GGUF BPE tokenizer
counts it before generation. The public API has no assumed tokenize endpoint.
Render-only accounting requests do not generate tokens and are distinct from the
four generation-request limit; all network work still consumes the attempt deadline.
Before manually upgrading Ollama or replacing the model, revalidate this path and
provider count parity. The application fails closed for an unsupported version.

Primary implementation references:
[Ollama 0.30.10 Chat request and debug fields](https://github.com/ollama/ollama/blob/v0.30.10/api/types.go),
[Qwen35 renderer](https://github.com/ollama/ollama/blob/v0.30.10/model/renderers/qwen35.go), and
[Qwen tokenizer metadata](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/tokenizer.json).

### Saved Conversation migration checkpoint (ticket 16)

Migration `002_conversations.sql` is implemented and tested locally, without a new
Chat endpoint at that checkpoint. Deploy it only through the existing green-main, stop-writers,
verified-backup and migration path. The new code requires schema 2; the previous
code requires schema 1, so rollback must restore both the previous code and its
pre-migration database. Do not simply check out old code against schema 2.

A file-backed local check verifies that a failed additive migration leaves a dirty
marker, that the verified pre-migration backup restores schema 1 and purchase facts,
and that the restored database can subsequently migrate to schema 2. This is not
a completed homelab deployment/rollback drill. No host changes were made for this
ticket. Ticket 17 now wires startup interruption recovery into the application lifecycle.


### Protected Chat UI checkpoint (ticket 17)

The HTTP page, authenticated WebSocket, durable streaming, Stop/Retry, deletion,
and reconnect are implemented and verified locally. No homelab files or services
were changed. Continue using the existing green-main deployment, verified backup,
migration, health check, and rollback process; schema remains at version 2.

Configure `SHOPPING_APP_ORIGIN` as the exact HTTPS origin used through Tailscale
Serve. Preserve the original Host and Origin through the proxy; arbitrary forwarded
host headers are ignored. Production session cookies require HTTPS and WebSockets
use WSS. Keep the application and Ollama bound to loopback and use one worker.
Missing origin disables Chat while leaving Orders usable. Model unavailability is
reported in the response, separately from core `/api/health` readiness.

The optional `SHOPPING_CHAT_TOKEN_SECONDS` defaults to 43,200 and accepts 1–86,400.
The default needs no new environment entry. If customizing it, first deploy this
revision's compatible validation helper: the earlier ticket 15 preparation helper
does not accept this key. Then edit the protected environment file and restart via
the normal deployment process. Expired browser access requires reconnect/refresh;
tokens are sent in the initial WebSocket message, never URLs or logs.

Local checks cover synthetic send/tool/evidence/reload, desktop/mobile themes and
keyboard dialogs, draft recovery after lost acknowledgements, multi-tab updates,
slow readers, checkpoint failure, and shutdown/restart. The protected page still
needs a real Qwen round trip through the deployed Tailscale origin and a disposable
host rollback/recovery drill. These are pending checks, not evidence of deployment.
