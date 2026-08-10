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

Nothing has been run on the Ubuntu machine yet. The scripts and CI workflow must be
committed, pushed, and observed green before following this runbook.

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
