# HYPERPOWER.md

How the agent operating system works in this repo. `CLAUDE.md` is the law, `hyperpower.json` is the machine contract, this file explains how the two are used. Everything named here exists in the tree; if you find a reference to a file that does not exist, that is a bug in this file, report it.

Installed on 2026-10-09 from the HYPERPOWER v2 pilot (core 1.0.0 vendored unchanged, decision D-047). Nothing in this layer has been proven on the owner's Windows machine yet; that is P00.

## Startup order (zero chat history)

1. `CLAUDE.md`, all of it.
2. `hyperpower.json`: branch (`main`), runtime pins (Node 24, Python 3.13, Postgres 16), dev ports (api 8000, web 3000), phases, MCP set.
3. `memory-bank/activeContext.md`, then `memory-bank/progress.md`: where the last session stopped and what is next.
4. The current phase file in `phases/` and the journeys and checkpoints it names in `ACCEPTANCE.md`.
5. `npm run hp -- resume`: reconciles `.hyperpower/state/session.json`, git HEAD and the Beads issue graph. Any disagreement it prints is the first thing to fix.
6. `npm run hp -- doctor`: must show no BROKEN item except the ones the current phase file lists as expected.
7. Then work. Read `SECURITY.md` before auth, tenancy, money, webhooks, file parsing or secrets; `.cursor/rules/design.mdc` before UI.

## Operating mode

- Manual mode, relay disabled (`mode.relayEnabled: false`). The owner drives a Cursor window; the agent in it does all terminal, code, database and deploy work.
- Phases run in the frozen order in `phases/README.md`. "apply" from the owner authorises the spend a phase file declares and nothing else.
- The MCP set is frozen per phase (`tools.mcp.set`): context7 required, github optional. Adding a server mid-phase invalidates the prompt cache for every later turn.

## Division of truth

| Question | Source of truth | Where |
| --- | --- | --- |
| What did we decide and why | Markdown | `CLAUDE.md`, `PRODUCT.md`, `docs/DESIGN.md`, `SECURITY.md`, `docs/decisions.md` |
| What is the API | Contract | `docs/api-contract.md`, `services/api/arbiter/contracts.py` (module seam) |
| What must work for a user | Journeys | `ACCEPTANCE.md` |
| What is executable right now | Beads | `.beads/issues.jsonl` (tracked), local store via `bd` (from P00) |
| What calls what, what breaks if I change it | Graphify | `graphify-out/` (gitignored, rebuilt locally, from P00) |
| How does this library work at our version | Context7, logged | `memory-bank/context7-log.md` |
| Did it actually happen | Evidence ledger | `evidence/ledger.jsonl`, schema in `evidence/schema.json` |

Never answer one of these questions from a different source. A chat claim that a phase is done is not evidence.

## Where systems live

| System | Location |
| --- | --- |
| Code | `SpawnJFK/arbiter`, branch `main` (private) |
| API | `services/api`: Python 3.13, FastAPI, SQLAlchemy 2, Alembic, venv at `services/api/.venv` (uv on Windows) |
| Web | `apps/web`: Next.js 16, React 19, Tailwind 4, Node 24 |
| Database | Postgres 16 + pgvector + pg_trgm. Local: `deploy/docker-compose.dev.yml` (Docker Desktop on Windows) |
| CI | GitHub Actions `.github/workflows/ci.yml`: ruff + pytest, web lint + tsc + build, Docker builds, compose config |
| Staging and production | none yet. Staging on Hetzner in P02, production in P04 (`hyperpower.json` `shipped`) |
| Control plane | `.hyperpower/core/` (project-agnostic, hash-locked in `core.lock.json`) |
| Tool binaries | `.hyperpower/tools/bin/` (gitignored), pinned with SHA256 in `.hyperpower/tools/registry.json` |

## The control plane

`npm run hp -- <command>` runs `.hyperpower/core/control.mjs`. The core contains no project strings; everything project specific comes from `hyperpower.json`. Do not edit core files. If a core file must change, change it, run `npm run hp -- lock`, and record a decision with the reason. `doctor` names any core file whose hash drifted.

| Command | What it does here | When |
| --- | --- | --- |
| `doctor` | Core hash check, Node major vs pin, storage policy, tool licences, forbidden tools (gitnexus) referenced in code, guard deny/allow proof, Graphify pre-push guard run through its real script. A skipped guard is BROKEN, not a pass. | Session start, before a gate |
| `status` | Branch, dirty tree, HEAD vs origin, ledger counts by tier and status, which required registry tools are present | Any time |
| `evidence append <file.json>` | Appends one record to `evidence/ledger.jsonl`. Refuses `replayable` without a verifier and refuses `attested` (no CI signer yet) | After proving a claim |
| `verify [id]` | Re-runs the verifier of every replayable record (or one): `cli`, `http`, `commit-exists`, `playwright`, `sql` | Before a gate, after a deploy |
| `gate <P0x> --product` | Loads the phase's `evidenceIds`, refuses self-hashed proof, re-runs every verifier, runs `npm run verify` (900 s limit), then closes the phase bead and reads it back from Beads. Only a read-back that shows `closed` with a `closed_at` writes `VERIFIED_SYNCHRONIZED` to `.hyperpower/state/phase-sync.json`. Report lands in `reports/gates/` | Phase close |
| `beads health` | `bd` version, issue count, every phase in `hyperpower.json` maps to a real bead | After P00 creates the beads |
| `handoff` | Read-only JSON summary for the next agent (schema `.hyperpower/schemas/handoff.schema.json`) | Before `/end` |
| `resume` | Compares session checkpoint, HEAD and bead state; prints disagreements | Session start |
| `end` | Writes `.hyperpower/state/session.json` and a checkpoint under `.hyperpower/state/checkpoints/` | Part of `/end` |
| `lock` | Regenerates `core.lock.json` | Only after a deliberate core change |

Monorepo notes, all outside the core: the root `package.json` holds only the control plane and the ship check; `npm run verify` chains `scripts/check-runtime.mjs`, `scripts/run-api-checks.mjs` and `scripts/run-web-checks.mjs`. Core `status` looks for Playwright and Impeccable at the repo root, so `hyperpower.json` lists them under `tools.requiredOutsideRegistry` with how each is proven.

## Evidence tiers

- **self-hashed**: the agent wrote a file and hashed it. Useful as a note, never accepted by a gate.
- **replayable**: the record carries a verifier that `verify` re-runs. This is the bar for every phase in this plan.
- **attested**: CI build provenance the agent cannot forge. Declared in `hyperpower.json` for launch-grade gates; core 1.0.0 cannot write it yet, so no phase uses it.

Verifiers this repo provides (all take no arguments, because the core's `cli` verifier turns every argument of a `node` command into a repo path; narrow them with `expectOutputContains`):

| Script | Proves |
| --- | --- |
| `scripts/run-api-checks.mjs` | ruff check, ruff format --check, pytest in services/api |
| `scripts/run-web-checks.mjs` | web lint (ESLint + i18n:check), typecheck, build |
| `scripts/verify-e2e.mjs` | J-01..J-09 through `apps/web/e2e/real-flow.mjs`; prints `J-0n PASS` lines |
| `scripts/verify-deployed-version.mjs` | the deployed API's `/healthz` commit equals HEAD (from P02) |
| `scripts/run-sql-verifier.mjs` | the `sql` kind: one read-only statement through psycopg in the API venv, `ARBITER_DATABASE_URL` from the process or `services/api/.env` |

Write evidence artifacts with repo-relative paths (`evidence/p00/api-checks.txt`). The guard blocks commands that write `.json`, `.log` or media files to an absolute path outside `storagePolicy.artifactRoot`, and an absolute path inside the repo counts as outside.

## Guards

- **Cursor hooks** (`.cursor/hooks.json`): `beforeShellExecution` runs `scripts/cursor-shell-guard.mjs`, which feeds the command to the core guard (blocks `git reset --hard`, forced `git clean`, force push, recursive deletes at a root, download-and-execute pipes, literal tokens in commands). It fails closed on a payload it cannot read. UNPROVEN in Cursor until P00 proves it through Cursor itself. The Impeccable `preToolUse` hook (`scripts/impeccable-pre-edit-hook.mjs`) exists but is not wired yet: its engine binary is not in the repo, and P00 item 13 installs it, wires it and proves it.
- **Git hooks** (`.githooks/`, tracked; P00 runs `git config core.hooksPath .githooks`): `pre-commit` runs `scripts/githook-pre-commit.mjs` on staged files (ruff on Python, i18n catalog check on web files, staged env files, em dashes, Betterleaks when installed); `pre-push` checks Graphify freshness (`scripts/graphify-pre-push-hook.mjs`) and Beads export staleness (`scripts/beads-pre-push-hook.mjs`). All are `#!/bin/sh`, locate Node with `scripts/githook-locate-node.sh` (Git Bash on Windows has no Node on PATH), print loudly and always exit 0. A guard that blocks work gets bypassed; a guard that warns survives.
- A guard counts as working only when proven through its real invocation path (a real `git commit` or `git push`, a real Cursor tool call), never by running its script by hand.

## Session flow

| Step | Command file |
| --- | --- |
| Start | `.cursor/commands/start.md` |
| Continue the phase | `.cursor/commands/next.md` |
| Health | `.cursor/commands/status.md` |
| Pick up after a gap | `.cursor/commands/resume.md` |
| Show the plan | `.cursor/commands/plan.md` |
| Close | `.cursor/commands/end.md` (implements the session close in `CLAUDE.md`; `.claude/commands/end.md` is the same file for Claude Code) |

Reviewers are subagents in `.cursor/agents/`: `gate-reviewer` (read-only, did not write the code, checks the phase against `ACCEPTANCE.md` and the ledger), `design-reviewer`, `security-reviewer`. Procedures live in `.cursor/skills/` (`rigor`, `graphiphy`, `impeccable`, `audit`, `polish`, `design-taste-frontend`), laws in `.cursor/rules/` (`standing-rules.mdc` always on, `security.mdc` and `design.mdc` by path). New machine: `docs/runbooks/bootstrap-fresh-clone.md`.
