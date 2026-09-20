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
- Responsive FastHTML interface built from pinned Stitchyard primitives, plus the JSON
  health endpoint
- Loopback-only web binding
- GitHub-hosted CI, dependency updates, secret scanning, and wheel verification
- Ubuntu systemd units, one-time bootstrap script, and in-place deployment helper

The first adapter targets one retailer's direct HTML order acknowledgements. Its
committed fixtures are irreversibly sanitised structural examples using reserved
.invalid addresses. Private emails under data/ are never test fixtures and remain
untracked.

Gmail authorization, client, provenance, and sync code live in the ingestion
package. Automatic scheduled Gmail ingestion, analytics and replenishment
predictions, Graphify projection, Telegram alerts and off-machine private-data
backups remain planned or operator-configured capabilities. The operator reports that the homelab deployment pipeline and
Tailscale access to the hosted page are already working. The repository's specific
bootstrap/rollback procedures have not been independently verified in this session.

The immediate MVP is an Ollama-backed Chat page on that existing deployment, with
four read-only purchase history tools and saved conversations. The selected MVP model is the
already installed `qwen3.5:9b`, with thinking disabled. Actual model/tool operation
still needs an integration check, not a prerequisite model comparison; cloud
providers and agent-framework comparisons are deferred.
Wayfinder planning is complete; the five [implementation tasks](.scratch/shopping-assistant/plans/chat-mvp.md)
are underway: purchase-history tools, the local Qwen backend, conversation persistence, and the protected Chat UI are implemented locally. Deploy working,
checked increments frequently to the experimental homelab rather than waiting for
the whole Chat feature. Homelab deployment and verification of the protected Chat page remain pending.

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
    S --> C["Implemented locally: Ollama Shopping Assistant"]
    P -. planned .-> T["Telegram alerts"]
~~~

SQLite is authoritative. Graph and Markdown outputs will be rebuildable projections,
not a second source of truth.

The installed package is `shopping` under `src/`. `shopping.ingestion` owns email
archive, parsers, Gmail sync, and import persistence; `shopping.purchases` owns
purchase-history queries and normalization; `shopping.assistant` owns the local
Ollama loop, conversations, context, and bounded tools; `shopping.web` owns the
FastHTML pages, protected Chat transport, and local static assets; and
`shopping.storage` owns SQLite connections, runtime checks, and migrations.
The public command targets `shopping.main:main`.

## Quick start

Install **uv 0.12.3**, then prepare the project from this checkout:

```bash
uv python install 3.14
uv sync --all-groups
uv run shopping migrate
```

Optionally import the synthetic sample order:

```bash
uv run shopping import-eml tests/fixtures/email/fairprice_order_minimal.eml --synthetic-fixture
```

The `shopping` command is registered in `pyproject.toml` and calls
`shopping.main:main`. It handles migration, import, and server commands.

For everyday startup, run:

```bash
SHOPPING_APP_ORIGIN=http://127.0.0.1:8000 uv run shopping serve
```

Open **http://127.0.0.1:8000** using that exact address so Chat's origin checks
match. Stop with Ctrl-C and rerun after code edits. Orders and the other pages work
without Ollama. Run `shopping migrate` again when application updates add migrations.

By default, these commands use the development profile, `data/shopping.sqlite3`,
and the `data/raw-email/` archive. They honor any `SHOPPING_*` settings already in
your terminal. Existing input emails under `data/raw-email/sample/` stay in place
and are not automatically imported. State persists between runs; repeated sample
imports do not duplicate the order. uv may update `uv.lock` when requirements change.
The application binds to loopback by default; Ubuntu exposes it privately through
Tailscale Serve.

### Real Chat responses using homelab Ollama

In a second terminal, start a tunnel using your existing SSH login or host alias:

```bash
bash scripts/ollama-tunnel.sh your-homelab-ssh-alias
```

Replace the example alias with the host you normally SSH into. Keep both terminals
open, then use **Chat** in the local app. Application code, conversations, and the
sample database stay on your Mac; prompts and tool results go to homelab Ollama.
No application deployment is needed. The tunnel uses ordinary SSH authentication
and host verification and binds only to local `127.0.0.1:11434`. Ctrl-C closes it.
If that port is already occupied, stop the existing local Ollama/tunnel first.

The backend requires the existing supported Ollama/model setup described below
(Ollama 0.30.10 and `qwen3.5:9b`). These commands do not install or modify the remote
model. Without Ollama, saved conversations remain readable but generation fails
visibly; this workflow does not provide simulated Chat responses.

To check the tunnel, keep it running and run this in another terminal **on your Mac**:

```bash
curl --fail --show-error http://127.0.0.1:11434/api/tags
```

The response should list the homelab's installed models, including `qwen3.5:9b`.
Then open http://127.0.0.1:8000/chat and ask “What is my latest order?” to check
the full flow using the synthetic order and its evidence link. The first response
may take longer while the model loads.

To watch GPU usage, run either command **on the homelab**, in a separate SSH session:

```bash
# Refresh GPU statistics every second using watch.
watch -n 1 nvidia-smi

# Alternatively, use NVIDIA's built-in one-second refresh.
nvidia-smi -l 1
```

Press Ctrl-C to stop GPU monitoring; the tunnel in its separate terminal stays open.

### Automated checks

```bash
uv run pytest -q
```

Tests use temporary development databases and synthetic fixtures; ordinary runs
skip real inference. With the tunnel running, optionally check the real model:

```bash
SHOPPING_OLLAMA_SMOKE=1 uv run pytest -q -s tests/integration/test_ollama_smoke.py
```

That check uses a separate temporary synthetic database. Local app tests do not
replace Ubuntu service, permissions, backup, and rollback verification; see
[the deployment runbook](docs/DEPLOYMENT.md).

## Web interface

The read-only interface has three live destinations:

- **Overview** surfaces high-confidence ingestion/runtime attention, complete current
  order and item counts, recorded order value by currency, scheduled delivery facts,
  recent privacy-minimised ingestion activity, and the latest orders.
- **Orders** provides server-side product/order/SKU search, retailer and status
  filters, explicit sorting, pagination, responsive rows, contextual order drawers,
  and canonical full pages with source-event-ordered revision history.
- **System** shows current runtime, SQLite/schema safety, ingestion states, privacy-
  minimised Gmail sync state, and product-normalisation backlog.

Navigation and volatile health regions use progressively enhanced HTMX requests;
ordinary links and forms remain valid without JavaScript. The shell follows the
system light/dark preference initially and remembers a local manual override. All
browser assets are served locally; the UI does not load fonts, scripts, or styles
from public CDNs.

## Purchase history read tools

`shopping.assistant.tools` now exposes `tool_schemas()`, strict `validate_arguments()`,
and `dispatch_tool(settings, name, arguments)` for `search_products`,
`get_product_history`, `list_recent_orders`, and `get_order`. These functions are
used by the local Qwen backend and Chat page.

Tools read each order's current revision, including `placed` records. Purchase date
uses only recorded `delivery_at`, with missing dates last; dated rows sort newest
first, breaking order ties by descending order ID and item ties by line number.
The product evidence page at `/products/{product_id}` displays calendar dates in
Asia/Singapore and links to existing order pages. Search returns candidates without
selecting an identity on the caller's behalf.

Results contain `status`, `data`, `evidence`, `next_cursor`, and `truncated`.
Search defaults/max are 10/20 rows, product history 20/50, recent orders 10/25;
order items use 50 rows per page. The complete `encode_result()` UTF-8 envelope is
also capped at 4 KiB, so pages may contain fewer whole rows. Oversized individual
records return `size_limit`; no fields or strings are silently shortened. Recorded
order totals stay distinct from item pages; the tools do not compute history totals.

Pass `next_cursor` with the same tool and arguments to continue. Signed cursors are
bound to the database, query/ID, and limit, and expire on application restart.
Pagination reads live state; restart from the first page if purchases change during
browsing. Unknown IDs return `not_found`, valid empty reads return `ok`, and invalid
arguments/cursors or storage failures return safe error codes. No archives or email
internals are returned, and no shopping data or schema changes are made.

## Local Qwen backend

`shopping.assistant.runtime.run_attempt()` now runs the native Ollama tool loop and
returns a complete, incomplete, or rejected result. Optional asynchronous callbacks
receive provisional text, correlated tool activity/results, and a terminal event.
`availability()` reports only the local response slot; it never loads a model.
The Chat page uses this loop; there is no model-management command.

The backend uses installed `qwen3.5:9b`, `think: false`, 8,192 context tokens, 768
output tokens, and a five-minute keep-alive. It allows one active attempt, at most
four generation requests/eight proposed tool calls, one invalid-batch correction,
180 seconds of work, and five seconds for cleanup. Tool calls run sequentially;
identical canonical calls reuse results only within the current attempt. Stop and
limits leave partial output incomplete. Unsettled cleanup faults generation until
process restart. No operational retries or silent model fallback occur.

Context accounting supports verified Ollama 0.30.10 and the Qwen35 GGUF tokenizer.
It reconstructs BPE from the installed model's vocabulary/merges and counts Ollama's
actual render-only prompt, including instructions, schemas and tool groups. It
reserves 768 output tokens and 512 safety tokens, allowing at most 6,912 input tokens.
Only whole old completed exchanges are removed. Unsupported accounting and provider
count mismatches fail visibly. No tokenizer/model downloads occur at runtime.

Factual answers require fresh tool evidence markers such as `[[order:1]]`, checked
against application-owned references. Clarifications and unsupported-request
explanations use explicit modes without a needless tool call. These mechanical
checks cannot prove the truth of every sentence; text and tool data remain untrusted.
The caller supplies completed exchanges from one conversation and its saved
endpoint/model identity; changed identity is rejected.

Optional settings are `SHOPPING_OLLAMA_URL` (fixed loopback URL),
`SHOPPING_OLLAMA_MODEL` (default `qwen3.5:9b`), and `SHOPPING_APP_ORIGIN`.
Missing origin disables browser Chat access while Orders remains usable.
An Ollama outage does not alter core `/api/health` readiness.

The default test suite skips real inference. To run the explicit synthetic check
against the installed local endpoint, using only a temporary development database:

```bash
SHOPPING_OLLAMA_SMOKE=1 uv run pytest -q -s tests/integration/test_ollama_smoke.py
```

The local loop passed a synthetic tool round trip against the homelab model through
an SSH relay. Backend deployment and verification inside the effective systemd
service context remain pending; see the deployment guide for the checkpoint record.

## Using Chat

Set `SHOPPING_APP_ORIGIN=http://127.0.0.1:8000` for local development, matching
exactly the address you open, then run the existing migrate/start commands. Open
**Chat** in the navigation. Production requires the exact HTTPS Tailscale origin.
The installed local Ollama service and selected model must be available to answer;
saved conversations and Orders remain readable during an inference outage.

Send a question, expand purchase-history activity, and open an evidence link to
inspect the recorded order or product. One response runs globally. Stop preserves
an incomplete answer; Retry explicitly starts a new attempt. Rename and delete
are available from the conversation header. Deletion waits for active cleanup.
Simple greeting-only messages are answered locally without invoking Ollama.
If the model returns prose without a verified evidence marker after a successful
fresh read, Chat discards that prose and shows a clearly labelled recorded-results
summary built from the tool fields and application-owned evidence links. It never
turns ungrounded prose into a factual answer. Context preparation failures are
shown separately from provider outages.
Empty lookups report that no rows were returned; partial results stay labelled
partial, and multiple product candidates remain a choice for the user.
The history rail becomes a Conversations dialog on small screens.
Chat fills the viewport below the application header, keeping the composer at the
bottom without scrolling the outer page. Message history and the conversation list
scroll independently; the input's resize limit adapts to short screens.

Committed text updates stream approximately every 250 ms. Disconnecting a tab
leaves generation running; reconnect retrieves saved state and checks an uncertain
command's status without resending it. Restart marks unfinished attempts interrupted.
Drafts, selection, and one pending command are kept in the tab's session storage,
so reload preserves unsent text. Closing the tab ends that browser storage lifetime.

`/chat` and `/chat/token` validate the configured host. `/chat/ws` additionally
requires an exact Origin and a session-bound page token in its first message.
Cookies are HttpOnly/SameSite Strict and Secure in production. Optional
`SHOPPING_CHAT_TOKEN_SECONDS` is 43,200 by default (allowed range 1–86,400);
expired connections require renewed access. Tokens never enter URLs. Connections,
commands, frames, outgoing queues, and snapshot pages are bounded; a slow tab is
disconnected independently. Assistant faults are separate from `/api/health`.

Local browser verification uses synthetic purchases and the actual runtime with a
fake provider. `tests/browser/chat_draft_recovery.js` can be run with
`agent-browser eval --stdin` on a running Chat page to verify reload before the
first update, including a lost acknowledgement, without issuing real mutations.
Real Qwen verification of this protected UI on the homelab remains pending.
`tests/browser/chat_viewport.js` runs with the same browser command and checks the
actual page and styles at desktop, phone, and landscape sizes, including long
histories and an expanded composer, without sending chat commands.

## Saved conversations

Migration `002_conversations.sql` adds saved Conversations, immutable submitted
messages, Response Attempts, bounded tool records, and command deduplication.
Run `shopping migrate` before using this code with an existing database; startup
only verifies the schema. Chat mutations use the protected WebSocket route.

`shopping.assistant.conversations` uses short-lived SQLite connections and functions:

- `new_draft()` issues a creation key without saving a Conversation. `accept_command()`
  accepts submit, Retry, Stop, rename, or confirmed delete. First submission saves
  its locally derived title, fixed endpoint/model, message, and attempt atomically.
- `command_status()` resolves uncertain acknowledgements. An identical accepted
  command returns its original outcome; changed content under that ID is rejected.
  The caller must use the saved snapshot to obtain subsequent state.
- `checkpoint()` and `record_tool()` compare attempt versions and commit before the
  caller broadcasts. Stop saves Stopping before cleanup; completion cannot overwrite
  it. Storage failures propagate, with the entire operation rolled back.
- `get_conversation()`, `get_attempt()`, and paginated `history()` restore saved state.
  `context_for_attempt()` selects at most 16 recent complete exchanges / 256 KiB;
  the runtime then applies its exact token budget. Failed text and orphaned tool
  results stay visible in history but never enter model context.
- `interrupt_unfinished()` marks active attempts interrupted at startup, without
  resubmitting. `finalize_delete()` removes owned records after confirmed cleanup.
  Startup wiring and browser coordination belong to the next ticket.

There is one active saved attempt globally, including Stopping, with no queue.
Retry creates a fresh attempt for the latest unsuccessful response and keeps its
original question once. A changed endpoint/model keeps history readable but requires
creating a new Conversation to submit more work.

History pages are capped at 50 attempts and 256 KiB (default 20); individual records
may exceed the future 64 KiB browser frame and must be chunked by that transport.
Response text is capped at 64 KiB including JSON encoding; each of at most eight
tools retains bounded 4 KiB arguments and 4 KiB results. No token-event log is stored.

Deletion first fences writes and remains recoverable if cleanup/removal fails.
It removes Conversation-owned content from the active database, preserving purchase
facts, archives, and existing backups. Only creation/command identifiers survive to
reject stale creation: deleted command IDs return `gone` even for changed content,
and their content fingerprints are erased. Homelab migration and rollback checks
remain pending; implementation and verification here are local.

## Commands

~~~bash
# Apply packaged migrations
uv run shopping migrate

# Migrate an explicitly selected database
uv run shopping migrate --database /absolute/path/shopping.sqlite3

# Archive and import an email selected by the local operator
uv run shopping import-eml path/to/message.eml

# Run the local web interface
uv run shopping serve --host 127.0.0.1 --port 8000
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

Ruff targets Python 3.14 by default. `pyproject.toml` makes one exception:

~~~toml
[tool.ruff.per-file-target-version]
"deploy/validate_config.py" = "py312"
~~~

This tells Ruff to use Python 3.12 as the target for linting and formatting that
file, keeping version-dependent fixes and formatting compatible with the deployment
host's system Python. Both Ubuntu deployment scripts invoke the validator with
`python3`, independently of the application's uv-managed Python 3.14 environment.
The override does not install or select a Python interpreter, or change the
application's Python requirement. See Ruff's
[per-file target version documentation](https://docs.astral.sh/ruff/settings/#per-file-target-version).

~~~bash
uv lock --check
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
git ls-files -co --exclude-standard -z |
  xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline
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

The deployment helper now validates optional local Chat settings alongside the
original production environment. Deploy this preparation before adding settings;
see [Chat environment preparation](docs/DEPLOYMENT.md#chat-environment-preparation-ticket-15).
