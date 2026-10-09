# P00: Install and verify on Windows

## Goal

Arbiter, built and tested in a Linux cloud session, runs on the owner's Windows machine from `E:`, with local Postgres 16 + pgvector, every check green, and the HYPERPOWER tooling (Beads, Graphify, OSV-Scanner, Betterleaks, Impeccable, Context7, git hooks, Cursor hooks, doctor) working through their real invocation paths. Every journey in `ACCEPTANCE.md` that has an automated check is replayed into the evidence ledger.

## Scope

1. **Clone to E:.** `git clone https://github.com/SpawnJFK/arbiter.git E:/arbiter`. Never work from `C:`. Write the real path into `hyperpower.json` `storagePolicy.current` and set `storagePolicy.status` to `OK`.
2. **Caches on E:.** `npm config set cache E:/.caches/npm`; user environment variables (PowerShell `[Environment]::SetEnvironmentVariable(..., "User")`): `PLAYWRIGHT_BROWSERS_PATH=E:\.caches\ms-playwright`, `UV_CACHE_DIR=E:\.caches\uv`, `UV_PYTHON_INSTALL_DIR=E:\.caches\uv-python`, `IMPECCABLE_HOME=E:\.caches\impeccable`. Tool binaries go under `.hyperpower/tools/` in the repo on E:.
3. **Node 24.** `fnm install 24`, `fnm use` in the repo (fnm reads `.node-version`). `node --version` prints v24. Doctor's runtime pin must be VERIFIED.
4. **Python 3.13 with uv.** `uv python install 3.13`, `uv venv --python 3.13 services/api/.venv`, `uv pip install --python services/api/.venv/Scripts/python.exe -e "services/api[dev]"`. `npm run check:runtime` passes.
5. **Web dependencies.** `npm ci` in `apps/web`, then `npx playwright install chromium` there.
6. **Docker Desktop and Postgres.** `docker version` and `docker info`; if either fails, human step A. Then `docker compose -f deploy/docker-compose.dev.yml up -d --wait` (Postgres 16 + pgvector, databases `arbiter` and `arbiter_test`), `alembic upgrade head` with the venv Python in `services/api`, and `python -m arbiter.cli seed-demo`.
7. **Env.** `services/api/.env` from `.env.example` (dev defaults, provider keys stay empty: everything runs on mock providers in P00), `apps/web/.env.local` from `apps/web/.env.example`. Never print secret values in the terminal.
8. **Ship check.** `npm run verify` (runtime pins, ruff, pytest, web lint with i18n:check, typecheck, build). Every step must pass on Windows. Any Windows-only failure (paths such as the `/tmp` storage default in `tests/conftest.py`, line endings, `.venv\Scripts`) is fixed in this phase, with a decision entry if the fix changes behaviour. Record how long `verify` takes: the gate gives the ship script 900 seconds.
9. **Full stack and e2e.** Start API (`uvicorn arbiter.api.app:app --port 8000`), worker (`python -m arbiter.pipeline.worker`) and web (build without `NEXT_PUBLIC_API_MOCK`, `npm start -- -p 3000`) as background processes in the agent terminal. `npm run verify:e2e` prints `J-01 PASS` to `J-09 PASS` and `E2E JOURNEYS J-01..J-09 PASS`.
10. **OSV-Scanner and Betterleaks.** Install both pinned binaries into `.hyperpower/tools/bin/` per `docs/runbooks/bootstrap-fresh-clone.md`, verify SHA256. OSV: `apps/web/package-lock.json`, plus the API dependencies frozen from the venv (`uv pip freeze` to `evidence/p00/api-requirements.txt`, then scan it as a requirements lockfile). Betterleaks over the full git history. Record results in `evidence/p00/`. A high or critical finding in a production dependency is fixed in this phase. Confirm Betterleaks' pre-commit flags from its `--help` output and fix `scripts/githook-pre-commit.mjs` if they differ.
11. **Beads.** Install `bd` 1.3.1 per the runbook. `bd init --prefix arbiter` (the tracked `issues.jsonl` is empty, so `bd bootstrap --yes` has nothing to import; log which command ran). Create one bead per phase P00 to P08 with `blocks` dependencies in order, write each id into `hyperpower.json` `phases.P0x.beadId`, then `bd export -o .beads/issues.jsonl`. `npm run hp -- beads health` must report every mapping ok.
12. **Graphify.** Install `graphifyy==0.9.28` into `.hyperpower/tools/graphify-venv`, copy `Scripts/graphify.exe` to `.hyperpower/tools/bin/`, check the SHA256 against `.hyperpower/tools/registry.json`. Run `graphify extract . --code-only --no-viz` and one budgeted query (`graphify query "no_reviewer_policy" --dfs --budget 1500`) that lands in `services/api/arbiter/pipeline/`.
13. **Impeccable.** Run `.cursor/skills/impeccable/scripts/impeccable.cmd context` once: the launcher downloads engine 0.1.3, verifies it against its `.sha256` sidecar and caches it under `IMPECCABLE_HOME`. Then add the `preToolUse` hook (`node "scripts/impeccable-pre-edit-hook.mjs"`) to `.cursor/hooks.json` and prove it through a real Cursor edit of a `.tsx` file.
14. **Git hooks.** `git config core.hooksPath .githooks`. Prove `pre-commit` and `pre-push` through a real `git commit` and a real `git push` (not by running the scripts): the commit output shows the `[ruff]`/`[i18n]`/`[secrets]` lines, the push output shows `[graphify] pre-push: index fresh` and `[beads] pre-push: export in sync`, and no `skipped` line.
15. **Cursor hooks.** Prove `.cursor/hooks.json` through Cursor itself: ask the agent to run `git reset --hard` and capture the denial; run `git status` and capture that it is allowed. If Cursor's hook payload or response shape differs from what `scripts/cursor-shell-guard.mjs` handles, fix the adapter (never the core) and log the docs source.
16. **MCP and Context7.** Copy `.cursor/mcp.json.example` to `.cursor/mcp.json` (gitignored; the old tracked `.cursor/mcp.json` was removed from git in the install commit, so a pull deletes the local copy), put the Context7 key into the header (human step B). After the restart, prove Context7 with `resolve-library-id` for `fastapi` and `next`. Because the build had no Context7 (open item 5 in `memory-bank/activeContext.md`), re-check the conventions the code relies on (FastAPI dependencies and exception handlers, SQLAlchemy 2 `select()` and sessions, Alembic hand-written migrations, pydantic v2 settings, psycopg 3, Next.js 16 `proxy.ts` and route handlers, React 19, Tailwind 4 `@theme`) and log each in `memory-bank/context7-log.md`.
17. **Replay into the ledger.** Append replayable records (`npm run hp -- evidence append`) for: the API checks (`cli`, `node scripts/run-api-checks.mjs`), the web checks (`cli`, `node scripts/run-web-checks.mjs`), and the journeys (`cli`, `node scripts/verify-e2e.mjs`, one record per journey with `expectOutputContains: "J-0n PASS"`, or one record with `"E2E JOURNEYS J-01..J-09 PASS"` if replay time matters; log the choice). Update each journey's Status in `ACCEPTANCE.md` to PROVEN with the record id and list the ids in `hyperpower.json` `phases.P00.evidenceIds`.
18. **Doctor clean.** `npm run hp -- doctor` exits 0 with no BROKEN items.

## Human-only steps

**A. Install Docker Desktop (only if `docker version` fails).**
1. Open https://www.docker.com/products/docker-desktop/ and click "Download for Windows - AMD64".
2. Run `Docker Desktop Installer.exe`. Keep "Use WSL 2 instead of Hyper-V" ticked. Click OK, wait, click "Close and restart".
3. After the restart Docker Desktop opens. Accept the terms. Sign-in is optional, click "Skip".
4. Click the gear icon (Settings), then Resources, then Advanced. Set "Disk image location" to `E:\.caches\docker`. Click "Apply & restart".
5. Success looks like: the whale icon in the taskbar tray is steady and Docker Desktop shows "Engine running" bottom left. Tell the agent "docker ok".

**B. Context7 key and Cursor restart.**
1. Open https://context7.com/dashboard and sign in.
2. Open "API Keys", click "Create API key", name it `arbiter`, copy it.
3. Paste it into the Cursor chat as `CONTEXT7_API_KEY=...`. The agent writes it only into the gitignored `.cursor/mcp.json` and never echoes it.
4. Quit Cursor fully (File, Exit, not just closing the window) and open it again on `E:\arbiter`.
5. Success looks like: Cursor Settings, "Tools & MCP" shows `context7` with a green dot. Tell the agent "context7 ok".

## Declared spend

None. Docker Desktop is free for this use. No cloud resources and no provider keys are used.

## Acceptance

- Journeys: J-01 to J-09 PROVEN on Windows with replayable records.
- Commands: `npm run verify` exit 0; `npm run verify:e2e` exit 0; `npm run hp -- doctor` exit 0; `npm run hp -- beads health` exit 0; `npm run hp -- verify` reports 0 broken and 0 stale.

## Exit gate

`npm run hp -- gate P00 --product` exits 0, the P00 bead reads back closed, `.hyperpower/state/phase-sync.json` shows P00 `VERIFIED_SYNCHRONIZED`.

## Out of scope

Real provider keys and any measurement (P01). Any cloud resource (P02). Any product feature.
