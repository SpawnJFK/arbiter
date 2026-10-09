# /resume

Pick up after a gap with no chat history. Do not trust memory or chat; trust the repo.

1. `git fetch`, `git status`, `git log --oneline -10`. If the tree is dirty with work you did not make, stop and report it; never discard it.
2. `npm run hp -- resume`. Every disagreement (session commit vs HEAD, phase marked synchronized but bead open, bead missing) is fixed or reported before new work.
3. `npm run hp -- doctor` and `npm run hp -- verify`.
4. Graphify: if `graphify-out/` is older than HEAD, `graphify update . --no-viz` (or `graphify extract . --code-only --no-viz` if it does not exist).
5. Read `memory-bank/activeContext.md`, `progress.md`, the last 5 entries of `docs/decisions.md`, and the current phase file.
6. Check versions still match the pins: `node --version` (24), API venv Python (3.13), `npm ls next react --depth=0` in apps/web, Alembic head in services/api.
7. If the state is unclear after this (long gap, doctor and memory bank disagree), run a full audit: every phase item against the code and the ledger, written to `reports/audits/<date>-resume.md`, before any new work.

Report the position ("P0x, item n of m"), the last verified evidence id, and the next action. Then continue with `/next`.
