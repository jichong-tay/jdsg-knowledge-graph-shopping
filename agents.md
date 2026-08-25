# Agent Notes

## Current state

This is a Python 3.14 local-first shopping application, not a starter placeholder. The implemented first slice archives and deterministically parses a narrow retailer email layout into SQLite and renders current orders with FastHTML. The core is vendor-neutral; vendor-specific sender, subject, and HTML rules belong in adapters. Gmail, analytics, Graphify, Ollama/Gemma chat, Telegram, and off-machine backup are planned but not implemented. Ubuntu bootstrap and in-place deployment scripts exist but have not been run on the homelab host.

Read `README.md`, `docs/MVP_PLAN.md`, and `docs/DEPLOYMENT.md` before changing architecture or milestone scope.

## Invariants

- SQLite is the authoritative store. Graph and Markdown artifacts are derived and rebuildable.
- Archive the exact raw email before parsing. Never alter or delete archived input as part of normal ingestion.
- Manual source identity and archive paths are content-addressed with SHA-256.
- Treat MIME, headers, HTML, labels, item values, and filenames as untrusted input.
- Treat an inner `From` domain as extraction filtering, not authentication. Manual import is an explicit local-operator trust action; future automatic Gmail ingestion must verify Gmail/forwarding provenance or route the message to review.
- Deterministic parsing comes before any LLM use. Do not use an LLM to extract exact order totals.
- Store money as integer cents and timestamps as timezone-aware UTC ISO-8601 text.
- Parsed order revisions and items are append-only. Never rewrite historical facts.
- Choose the current revision primarily by the original source-message timestamp. Revision-kind precedence is only a tie-breaker; older messages remain historical.
- A different wrapper around the same original source event and business facts links
  to the existing revision; a later source event remains a new append-only revision
  even when its facts return to an earlier state.
- A failed reparse must never downgrade a source already marked `parsed`.
- Parse and perform external work outside transactions. Keep database transactions short.
- Use short-lived SQLite connections created in the thread that uses them. Never retain a transaction for a WebSocket or while calling an external service.

## Migrations

- Packaged migrations live in `app/migrations/` and use names like `001_ingestion.sql`.
- Only `shopping migrate` may change the schema. Web startup and import commands verify the schema and fail with an instruction to migrate.
- Migrations are checksum-recorded, dirty-state aware, and serialized with a file lock.
- Never edit an applied migration after release. Add the next numbered migration.
- Use a file-backed temporary database in migration tests; do not use `:memory:` for multi-connection checks.
- Before any production migration, `deploy-shopping` must stop application writers
  and create a verified SQLite backup. Preserve its automatic database-aware rollback.

## Privacy and security

- Never commit real `.eml` files, SQLite databases, `.env`, OAuth material, Telegram tokens, or model prompts containing household data.
- Test fixtures must be synthetic or irreversibly sanitized and use reserved `.invalid` addresses.
- Private samples under `data/` may guide adapter design but must never be copied into tests, logs, prompts, documentation, or tool output.
- Keep generated private state under ignored `data/`, `knowledge/`, or `graphify-out/` paths.
- Preserve `0700` directories and `0600` raw email/database files.
- The web app binds to loopback by default. Do not weaken this to `0.0.0.0`; private remote access is planned through Tailscale Serve. The explicit override exists for deliberate operator use only.
- Keep `SHOPPING_ENV` limited to `development` or `production`; automated tests use development with isolated temporary paths. Unknown values must fail closed and production paths must remain absolute.
- Do not render archived email HTML or load its remote resources.
- Update `.secrets.baseline` only after reviewing every finding and proving it is not a secret.
- GitHub pull-request CI must remain GitHub-hosted, read-only, secret-free, and must never target the homelab machine.

## Toolchain and checks

Use `uv` 0.12.3 and the committed lockfile. Keep runtime dependencies minimal and pin build/security tooling tightly enough for reproducible CI.

```bash
uv python install 3.14
uv sync --locked --all-groups
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest -q
git ls-files -co --exclude-standard -z | xargs -0 uv run --locked detect-secrets-hook --baseline .secrets.baseline
```

When behavior changes, add proportional tests. At minimum retain coverage for exact-repeat idempotency, alternate wrappers, concurrent import/migration, revision ordering, rollback on persistence failure, malformed/spoofed email rejection, HTML escaping, schema checks, and health output.

Before handoff, also verify a built wheel contains `app/migrations/001_ingestion.sql` and can run `shopping migrate` in an isolated environment.

## Runtime and deployment

- Development may run with an affected SQLite build only in the rollback journal; health is degraded and not production-ready.
- Production must reject affected WAL builds. Supported versions are SQLite 3.51.3+, 3.50.7+, or 3.44.6 within that backport line.
- Start with one Uvicorn worker and fewer than five trusted household users.
- Do not add Docker, PostgreSQL, Redis, Celery, Neo4j, LangChain, or a vector database without measured need and an explicit plan change.
- Initial homelab deployment uses the administrator login plus one non-login
  `shopping-app` runtime account, `bootstrap-ubuntu.sh`, systemd, and Tailscale Serve.
- Ongoing deployment is deliberately in place: `sudo deploy-shopping <green-main-sha>`
  briefly stops the service, backs up SQLite, updates `/opt/shopping-app`, migrates,
  restarts, health-checks, and rolls back on failure. Do not add release directories,
  symlink switching, blue/green services, or containers without measured need.
- Do not add a self-hosted GitHub runner to the public repository. If studied later in an isolated deployment design, it needs a separate account and must never accept pull-request work.
- Treat both deployment scripts as unverified on Ubuntu until the first bootstrap and
  a disposable failed-deployment rollback drill have succeeded.

## Documentation discipline

Update `README.md` after changing current behavior or setup. Update `docs/MVP_PLAN.md` when target architecture, schema, or milestones change. Update `docs/DEPLOYMENT.md` when CI or Ubuntu operations change. Clearly separate implemented behavior from planned behavior.

## Agent skills

### Issue tracker

Issues are tracked as local Markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default canonical label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain-doc layout. See `docs/agents/domain.md`.
