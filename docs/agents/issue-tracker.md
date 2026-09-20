# Issue tracker: Local Markdown

Issues, specs, research, and plans for this repo live as Markdown files in `.scratch/shopping-assistant/`.

## Conventions

- `shopping-assistant/` is the only immediate child directory of `.scratch/`. Keep all feature work there; do not create sibling feature directories.
- Keep plans under `.scratch/shopping-assistant/plans/` and research under `.scratch/shopping-assistant/research/`; use descriptive filenames such as `plans/source-layout.md`. Preserve existing documents when adding another plan or research note.
- Implementation issues are one file per ticket at `.scratch/shopping-assistant/issues/<NN>-<slug>.md`. Continue the existing number sequence, never a single combined tickets file.
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/shopping-assistant/`; use its existing `issues/` directory for tickets.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/shopping-assistant/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/shopping-assistant/issues/NN-<slug>.md`, continuing the existing numbering, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/shopping-assistant/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
