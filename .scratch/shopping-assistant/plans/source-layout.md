# Source Layout and Feature Organization Plan

Status: Implemented and locally verified on 2026-09-20 with Luna subagents using low reasoning. Homelab deployment was outside this refactor.

**Goal:** Use `src/`, replace the generic `app` package name, and organize the implemented code by responsibility. Keep every planning artifact inside the existing `.scratch/shopping-assistant/` directory.

**Recommendation:** Use one Python package named `shopping` with five feature and infrastructure areas: `ingestion`, `purchases`, `assistant`, `web`, and `storage`. This changes code ownership as well as the package name. The product remains one Python application and one deployable service.

**Tech stack:** Existing Python 3.14, uv 0.12.3, Hatchling, FastHTML, SQLite, and pytest. No new runtime dependencies.

## Why this structure

- `ingestion` owns acquiring, archiving, parsing, and atomically importing email. Gmail is one input source within that workflow.
- `purchases` owns reusable Purchase History queries and deterministic product/listing identity rules. Web pages and assistant read tools can use these functions without putting the shopping data layer inside either interface.
- `assistant` owns Conversations, Response Attempts, model context, Ollama access, and bounded read-tool schemas and envelopes.
- `web` owns HTTP/WebSocket routes, HTML rendering, and browser assets.
- `storage` owns SQLite connection policy, runtime safety checks, and schema migration mechanics. Feature-specific SQL stays with the feature that owns it.

The `shopping` directory is the installed Python package name: imports become `shopping.ingestion`, `shopping.purchases`, and so on. `src` itself is not a package. A flat `src/ingestion`, `src/web`, `src/storage` layout is possible, but would expose several generic top-level Python packages. A single product name keeps imports and wheel ownership explicit.

## Implemented layout

Routine `__init__.py` files and unchanged tool configuration are omitted.

```text
jdsg-knowledge-graph-shopping/
├── src/
│   └── shopping/
│       ├── main.py                    # Command-line entry point
│       ├── config.py
│       ├── ingestion/
│       │   ├── pipeline.py            # Archive → parse → persist
│       │   ├── archive.py
│       │   ├── models.py              # Existing parsing/import contracts
│       │   ├── store.py               # One atomic ingestion transaction
│       │   ├── parsers/
│       │   │   ├── base.py
│       │   │   └── fairprice.py
│       │   └── gmail/
│       │       ├── auth.py
│       │       ├── client.py
│       │       ├── provenance.py
│       │       ├── sync.py
│       │       └── state.py           # Gmail cursor/sync persistence
│       ├── purchases/
│       │   ├── queries.py             # Orders, revisions, products, history
│       │   └── normalization.py       # Existing deterministic identity rules
│       ├── assistant/
│       │   ├── runtime.py
│       │   ├── context.py
│       │   ├── ollama.py
│       │   ├── conversations.py
│       │   └── tools.py
│       ├── web/
│       │   ├── __init__.py            # Exposes create_app
│       │   ├── factory.py             # App setup and route registration
│       │   ├── layout.py              # Shared page shell/display helpers
│       │   ├── queries.py             # Overview/system/ingestion projections
│       │   ├── overview.py
│       │   ├── orders.py
│       │   ├── products.py
│       │   ├── system.py
│       │   ├── health.py
│       │   ├── chat.py                # Protected browser/streaming adapter
│       │   ├── chat_ui.py
│       │   └── static/
│       │       ├── shopping.css
│       │       ├── shopping.js
│       │       └── chat.js
│       └── storage/
│           ├── connection.py
│           ├── runtime.py            # Existing Python/SQLite safety checks
│           ├── schema.py             # Migration runner
│           └── migrations/
│               ├── 001_ingestion.sql
│               └── 002_conversations.sql
├── tests/
│   ├── conftest.py
│   ├── fixtures/email/
│   ├── ingestion/                    # Includes Gmail and parser tests
│   ├── purchases/
│   ├── assistant/
│   ├── web/
│   ├── storage/
│   ├── deployment/
│   ├── integration/                  # Existing opt-in real-model check
│   ├── browser/
│   └── test_config.py
├── deploy/                           # Ubuntu deployment/systemd helpers
├── scripts/                          # Developer conveniences
├── docs/                             # Durable project reference
├── .scratch/
│   └── shopping-assistant/           # The only directory directly under .scratch
│       ├── map.md
│       ├── plans/
│       │   ├── chat-mvp.md           # Existing Chat implementation plan
│       │   └── source-layout.md      # This layout record
│       ├── research/
│       │   ├── local-model-selection.md
│       │   └── chat-ui-options.md
│       └── issues/                   # Existing numbered tickets
├── data/                             # Private runtime state; ignored
├── README.md
├── CONTEXT.md
├── agents.md
├── pyproject.toml
└── uv.lock
```

Keep root tooling files and `.github/`, `.agents/`, and `.codex/` in their expected locations when present. Generated `knowledge/` and `graphify-out/` remain ignored. Create no empty packages for future features.

## Planning folder organization

The five Markdown files previously at the root of `.scratch/shopping-assistant/` had three distinct roles. `map.md` remains the working index; the four supporting documents now sit one level below it:

| Previous file | Current location |
| --- | --- |
| `map.md` | `map.md`, unchanged |
| `implementation-plan.md` | `plans/chat-mvp.md` |
| `file-structure-plan.md` | `plans/source-layout.md` |
| `chat-ui-options-research.md` | `research/chat-ui-options.md` |
| `local-model-selection-research.md` | `research/local-model-selection.md` |

Keep `issues/` and all numbered ticket names intact. The 18 tickets already point to `map.md` as their parent, and the configured issue-tracker workflow uses that filename. Use the map to link to both plans and research notes; an additional README would duplicate its navigation role.

When applying these moves, update incoming links in README, MVP_PLAN, DEPLOYMENT, the map, and affected issues; adjust the moved Chat plan's relative links back to `../map.md` and `../issues/`. Update `docs/agents/issue-tracker.md` to describe `plans/` and `research/`. Verify all moved documents' local links resolve.

Also distinguish current status from historical planning: the map still says ticket 14 is next, while the repository records local implementations for tickets 14–17 and pending host verification. Refresh that summary from the implementation records without claiming deployment or automatically closing tickets. Keep research notes dated and label their role as decision background; the accepted FastHTML and Qwen choices are recorded elsewhere and those comparisons are not new prerequisites.

This nested grouping is implemented. The sole immediate child of `.scratch/` remains `shopping-assistant/`.

## Concrete source mapping

| Previous code | Current owner |
| --- | --- |
| `app/main.py`, `app/config.py` | `shopping/main.py`, `shopping/config.py` |
| `app/ingestion.py` | `shopping/ingestion/pipeline.py` |
| `app/models.py` | `shopping/ingestion/models.py`, kept intact |
| `app/email/archive.py`, `app/email/parsers/` | `shopping/ingestion/archive.py`, `shopping/ingestion/parsers/` |
| `app/gmail/` | `shopping/ingestion/gmail/` |
| Source lookup, successful import, and failed-source persistence from `app/db/repository.py` | `shopping/ingestion/store.py` |
| Gmail cursor/success/error persistence from `app/db/repository.py` | `shopping/ingestion/gmail/state.py` |
| Current-order reads/counts from `app/db/repository.py` | `shopping/purchases/queries.py` |
| `app/assistant/queries.py` | `shopping/purchases/queries.py`; preserve existing `read_page` behavior |
| `list_orders`, `get_order_history`, `list_scheduled_deliveries` from `app/web_queries.py` | `shopping/purchases/queries.py` |
| Overview/system/recent-source projections from `app/web_queries.py`, plus `ingestion_counts` from the repository | `shopping/web/queries.py` |
| `app/email/normalize.py` | `shopping/purchases/normalization.py`, moved unchanged |
| Assistant runtime, context, Ollama, conversations, and tools | `shopping/assistant/` |
| `app/web.py`, `app/web_app.py`, `app/web_ui.py` | `shopping/web/`, split by page responsibility |
| `app/assistant/web.py`, `app/assistant/ui.py` | `shopping/web/chat.py`, `shopping/web/chat_ui.py` |
| `app/static/` | `shopping/web/static/` |
| `app/db/connection.py`, `app/db/migrations.py`, `app/runtime.py` | `shopping/storage/connection.py`, `shopping/storage/schema.py`, `shopping/storage/runtime.py` |
| `app/migrations/*.sql` | `shopping/storage/migrations/*.sql` |

## Design constraints

- Preserve the current entry-point consolidation: move the existing `app/main.py` implementation, without restoring `app/cli.py` or root `main.py`.
- The public command stays `shopping`; its implementation target changes to `shopping.main:main`. Internal imports change from `app.*` to `shopping.*`. No temporary `app` compatibility package is planned for this local application.
- `ingestion/models.py` contains the existing parsing/import contracts. Do not invent a shared Purchase model or split its 158 lines solely to fill folders.
- `ingestion/store.py` retains the single transaction for source records, revisions, items, and links. Do not split these writes into separately committed feature repositories.
- `purchases/queries.py` keeps the existing SQL, ordering, and return shapes. This is a relocation of implemented reads, not a new generic query framework. Assistant schemas, cursors, validation, byte limits, and evidence envelopes remain in `assistant/tools.py`.
- The product evidence page may continue calling the existing bounded tool interface during this refactor. Relocating shared query ownership does not require redesigning that interface or duplicating its safety checks.
- `storage` imports no web, assistant, ingestion, or purchases modules. Feature persistence calls its short-lived connection and transaction helpers.
- The web factory composes routes; page modules import their concrete dependencies, not the factory. Preserve the injectable Chat runner and avoid circular imports through `web/__init__.py`.
- SQL resources move to `src/shopping/storage/migrations/`; installed wheel paths become `shopping/storage/migrations/`. Preserve SQL filenames, contents, checksums, ordering, and schema version. Migration history remains valid.
- Browser assets move to `src/shopping/web/static/`; public `/static/...` URLs stay the same.
- Development state already defaults to `Path.cwd() / "data"`; production keeps explicit absolute paths. Keep databases, archives, credentials, and session keys at their current locations, with existing permissions.
- Keep deterministic parsing, fingerprint values, provenance checks, runtime safety policy, loopback binding, protected Chat, and deployment rollback behavior unchanged.
- Keep all planning files in `.scratch/shopping-assistant/`: `map.md` at the root, plans under `plans/`, research under `research/`, and tickets under the existing `issues/` directory with continuous numbering. The single immediate-child convention is recorded in the agent instructions; the nested grouping and application layout are implemented.

## Implementation checklist

### 1. Move and rename the installed package

- [x] Preserve the existing working-tree edits, move the current `app/` package to `src/shopping/`, and update imports without splitting feature modules yet.
- [x] In `pyproject.toml`, set wheel packages to `["src/shopping"]`, Pyright application include to `"src/shopping"`, and the command target to `shopping = "shopping.main:main"`. Keep the distribution name, dependencies, uv version, and console command unchanged.
- [x] Update migration lookup and tests to resolve resources relative to the installed package rather than `<checkout>/app`. In the intermediate layout migrations are next to `shopping/config.py`; when storage is regrouped, update this to `Path(__file__).resolve().parent / "storage" / "migrations"`.
- [x] Update CI's installed-resource checks from `files("app")` to `files("shopping")`. Check both migration filenames and all three browser assets at their current stage's packaged paths.
- [x] Make deployment-helper loading explicit in shared test setup: load `<checkout>/deploy/sqlite_backup.py` with `importlib.util.spec_from_file_location` and `module_from_spec`, register it in `sys.modules` before `exec_module`, and pass the loaded helper to the two test files that currently import `deploy.sqlite_backup`. Keep deployment helpers outside the wheel.
- [x] Refresh the editable installation using `uv sync --all-groups`. Verify a fresh `uv run pytest -q`, without `PYTHONPATH`, pytest `pythonpath`, or `sys.path` workarounds.

### 2. Establish ingestion, purchases, and storage ownership

- [x] Apply the source mappings for ingestion, Gmail state, purchase queries, normalization, and storage. Keep SQL and domain calculations unchanged.
- [x] Keep the complete ingestion persistence transaction in `ingestion/store.py` and keep Gmail authentication/provenance distinct from retailer parser filtering.
- [x] Update all callers and tests to the mapped modules. Purchase queries use `shopping.storage.connection`; assistant tool dispatch uses `shopping.purchases.queries.read_page`.
- [x] Move SQL resources into `storage/migrations/` and update config, fixtures, and installed-resource assertions together. Compare SQL files byte-for-byte with their originals.
- [x] Run ingestion, Gmail, Purchase History tool, conversation, migration, and runtime-safety tests. Retain idempotency, alternate-wrapper, ordering, concurrency, and rollback assertions.

### 3. Consolidate the website

- [x] Create `shopping/web/` with `create_app` exposed through `__init__.py` and implemented in `factory.py`.
- [x] Split routes and rendering by overview, orders, products, system, and health. Shared shell/formatting goes in `layout.py`; product-history rendering goes in `products.py`.
- [x] Move Chat browser transport and rendering from the assistant package into `web/chat.py` and `web/chat_ui.py`.
- [x] Move browser assets to `web/static/`; factory asset lookup becomes `Path(__file__).with_name("static")`. Preserve public routes and URLs.
- [x] Update imports and monkeypatch targets. Verify page rendering, static responses, health, Chat origin/session protections, streaming, and existing browser probes with synthetic data.

### 4. Group tests and synchronize documentation

- [x] Mirror the proposed responsibilities under `tests/`. Retain existing test basenames to avoid pytest import collisions, shared `tests/conftest.py`, synthetic `tests/fixtures/email/`, and the browser/integration directories.
- [x] Update README setup/source references, the current-layout diagram in `docs/MVP_PLAN.md`, installed-package checks in `docs/DEPLOYMENT.md`, the tree in `docs/agents/domain.md`, and migration source/wheel references in `agents.md`.
- [x] Keep current implementation separate from planned capabilities. Leave historical issue discussions intact unless an active execution instruction would become wrong.
- [x] Search active code, configuration, tests, and runbooks for stale `app` imports, package-resource lookups, and source paths. Preserve unrelated existing edits.

## Acceptance checks

1. Fresh editable install: `uv run shopping --help` and the required Ruff, Pyright, pytest, lockfile, and secret checks pass without path workarounds.
2. Installed wheel: from a temporary directory outside the checkout, import `shopping`, confirm both SQL resources and three static files, migrate a temporary database, and exercise health/static responses. The install location can remain read-only.
3. Private state: source relocation does not change development working-directory defaults, explicit production paths, file modes, archives, credentials, or session keys.
4. Behavior: retain existing ingestion, provenance, schema, Purchase History, conversation, and protected-streaming coverage. All purchase/conversation facts and migration bytes remain unchanged by the refactor.
5. Deployment: existing systemd commands still invoke the installed `shopping` command. Keep `deploy/`, host working directories, backup, and rollback logic intact.

Review any secret-baseline filename changes individually instead of regenerating or suppressing findings. This structural refactor needs no real Gmail access, model inference, database migration against private data, or homelab deployment.

## Implementation result

Implemented on `codex/source-layout`, preserving the existing entry-point edits. The package, feature boundaries, grouped tests, documentation, planning links, and CI wheel checks now follow this layout. Independent source and documentation reviews found no remaining issues.

Local verification:

- Fresh editable installation and the `shopping` command work without Python-path overrides; the committed dependency lockfile is unchanged.
- Ruff formatting/lint and Pyright pass. Pytest reports 272 passed and one skipped opt-in real-model test, matching the baseline; the existing Fastcore deprecation warning remains.
- The secret scan passes using the reviewed baseline. Only six baseline filenames changed; no findings or hashes were added. A temporary Git index allowed the hook to verify the baseline without changing the user's staging area.
- The built wheel contains both SQL migrations and all three browser assets. From a directory outside the checkout, its read-only installation migrated a temporary database to schema 2 and served health, overview, orders, system, and static responses successfully.
- SQL literals, migration bytes, and browser asset bytes match the original source.
- Browser verification of the installed wheel with synthetic data passed: overview and Chat render without browser errors, all 24 layout cases across eight viewports pass, and both draft-recovery scenarios preserve the draft without replaying a mutation.
- Local Markdown links resolve, and active imports, resource lookups, and runbooks contain no stale `app` package paths.

No private-state migration, real Gmail operation, model inference, or homelab deployment was performed. Host Chat verification remains tracked separately in ticket 18.
