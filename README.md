# Local Shopping Intelligence

A local-first learning project that turns retailer transaction emails into a private,
queryable shopping history. Groceries are the first useful dataset, but the
application boundary is shopping: future adapters can support other online or
in-store retailers without changing the archive, database, web UI, or analytics
layers.

## Implemented first slice

- Python 3.14 project managed by uv 0.12.3
- Generic ingestion pipeline with vendor-specific deterministic parser adapters
- Exact-byte, SHA-256-addressed raw email archive
- SQLite schema with append-only order revisions, products, retailer listings, and
  source provenance
- Idempotent manual .eml import with concurrency and rollback protection
- FastHTML dashboard, order detail page, and JSON health endpoint
- Loopback-only web binding
- GitHub-hosted CI, dependency updates, secret scanning, and wheel verification
- Ubuntu systemd units, one-time bootstrap script, and in-place deployment helper

The first adapter targets one retailer's direct HTML order acknowledgements. Its
committed fixtures are irreversibly sanitised structural examples using reserved
.invalid addresses. Private emails under data/ are never test fixtures and remain
untracked.

Gmail ingestion, analytics and replenishment predictions, Graphify projection,
Ollama/Gemma chat, Telegram alerts, and off-machine private-data backups are planned
but not implemented. The deployment scripts are included but have not yet been run
on the Ubuntu host.

## Architecture

~~~mermaid
flowchart TD
    E["Retailer email"] --> A["Exact-byte private archive"]
    A --> D["Parser dispatcher"]
    D --> F["Vendor adapter"]
    F --> S[("SQLite source of truth")]
    S --> W["FastHTML purchase-history UI"]
    S -. planned .-> P["Analytics and predictions"]
    S -. planned .-> G["Rebuildable graph projection"]
    P -. planned .-> C["Local Gemma chatbot"]
    G -. planned .-> C
    P -. planned .-> T["Telegram alerts"]
~~~

SQLite is authoritative. Graph and Markdown outputs will be rebuildable projections,
not a second source of truth.

## Quick start

Install the pinned toolchain and dependencies:

~~~bash
uv python install 3.14
uv sync --locked --all-groups
~~~

Create the local schema, import the sanitised example, and start the UI:

~~~bash
uv run --locked shopping migrate
uv run --locked shopping import-eml tests/fixtures/email/fairprice_order_minimal.eml --synthetic-fixture
uv run --locked shopping serve
~~~

Open http://127.0.0.1:8000. The application deliberately stays on loopback; the
Ubuntu design exposes it privately through Tailscale Serve. A non-loopback bind
requires the explicit SHOPPING_ALLOW_NON_LOOPBACK=true override.

## Commands

~~~bash
# Apply packaged migrations
uv run --locked shopping migrate

# Migrate an explicitly selected database
uv run --locked shopping migrate --database /absolute/path/shopping.sqlite3

# Archive and import an email selected by the local operator
uv run --locked shopping import-eml path/to/message.eml

# Run the local web interface
uv run --locked shopping serve --host 127.0.0.1 --port 8000
~~~

The synthetic-fixture switch only enables reserved test sender domains, and
production refuses it.

## Configuration

The application reads environment variables directly; it does not load .env files.
Examples live in .env.example.

| Variable | Development default | Production rule |
| --- | --- | --- |
| SHOPPING_ENV | development | Must be `development` or `production` |
| SHOPPING_DATA_DIR | ./data | Required and absolute |
| SHOPPING_DATABASE_PATH | data/shopping.sqlite3 | Absolute if overridden |
| SHOPPING_RAW_EMAIL_DIR | data/raw-email | Absolute if overridden |
| SHOPPING_HOST | 127.0.0.1 | Keep on loopback |
| SHOPPING_PORT | 8000 | Any valid local port |
| SHOPPING_ALLOW_NON_LOOPBACK | false | Leave false with Tailscale Serve |

There are only two application environments. Use `development` on the MacBook and
in automated checks, and `production` on the Ubuntu homelab. The value must use the
exact lowercase spelling; unknown values fail closed.

## Private data and a public repository

This repository is intentionally suitable for public learning. Source visibility is
not the risk; accidentally committed runtime data is.

- Keep real .eml files, SQLite files, OAuth material, bot tokens, .env files,
  addresses, order identifiers, and chat logs out of Git.
- Keep private samples under ignored data/ paths.
- Only commit synthetic or irreversibly sanitised fixtures with .invalid addresses.
- Review staged files even when the local secret scan passes; scanners do not
  recognise all personal shopping data.
- If a secret is committed, rotate it. Deleting a later copy does not erase Git
  history or forks.
- Never target the home Ubuntu machine from public pull-request workflows.

The five private source samples currently under data/ were used only to identify the
real HTML structure. They remain ignored and are not copied into this repository's
test suite.

## Local state

~~~text
data/
├── .sesskey                    # private FastHTML session-signing key
├── shopping.sqlite3
└── raw-email/
    ├── manual/
    │   └── <first-two-hash-characters>/<sha256>.eml
    └── gmail/                 # planned
~~~

Private directories are created with mode 0700 and the session key, archived
email, and database files with mode 0600 where the platform permits it.

## Runtime safety

The application uses WAL only with SQLite releases containing the required WAL-reset
fix. An affected development runtime falls back to the rollback journal and reports
degraded health. Production refuses to start with an affected runtime.

Supported production versions are SQLite 3.51.3+, 3.50.7+, or 3.44.6 within that
backport line.

## Checks

~~~bash
uv lock --check
uv sync --locked --all-groups
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest -q
git ls-files -co --exclude-standard -z |
  xargs -0 uv run --locked detect-secrets-hook --baseline .secrets.baseline
~~~

## Ubuntu homelab

The homelab deployment uses:

- the existing administrator login to run one bootstrap command and later updates;
- one non-login shopping-app account for the application;
- systemd for migration and web processes;
- 127.0.0.1:8000 behind Tailscale Serve;
- GitHub-hosted CI only, with no runner inside the home network.

After a commit passes CI, the Ubuntu command is `sudo deploy-shopping <full-sha>`.
It updates the single checkout in place; there is no blue/green release layout. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the one-time installation, public
repository concerns, and the `sudo deploy-shopping --recover` recovery command.

## Project plan

The complete schema, prediction design, chatbot/tool boundary, Graphify experiment,
notifications, milestones, and acceptance tests are in
[docs/MVP_PLAN.md](docs/MVP_PLAN.md).
