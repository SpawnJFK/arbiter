# Active context

Last updated: 2026-10-09. Phase position: **P00 next, item 1 of 18** (`phases/phase-00-install-and-verify.md`). HYPERPOWER v2 is installed in the repo (uncommitted at the end of the install session; the owner commits). Nothing in the HYPERPOWER layer is proven on the owner's Windows machine yet.

Next gate: `npm run hp -- gate P00 --product`.

## Session 2026-10-09 (HYPERPOWER v2 install, Linux cloud session)

What changed:
- `.hyperpower/core/` copied byte for byte from the HYPERPOWER v2 pilot (core 1.0.0, 14 files, `core.lock.json` unchanged; doctor reports no drift), plus `schemas/`, the tool registry (bd 1.3.1, OSV-Scanner 2.6.0, Betterleaks 1.9.0, Graphify 0.9.28 with SHA256 and licences) and a fresh `state/phase-sync.json` (D-047).
- `hyperpower.json` rewritten to schema 2 (runtime Node 24 + Python 3.13 + Postgres 16, storage policy on E:, MCP set context7 required and github optional, phases P00..P08 with empty bead ids, spend 0 EUR with planned items for P01 and P02).
- Plan moved from `docs/phases/` to root `phases/` and renumbered P00..P08 (D-048); `docs/phases/` removed; ROADMAP.md, README, docs and the tenancy docstring point to the new numbers.
- `ACCEPTANCE.md` rewritten in the journey format: J-01..J-09 with `cli` verifiers through `scripts/verify-e2e.mjs`, INT-01..INT-06 with phase and verifier.
- Root `package.json` (no workspaces): `hp`, `verify` (= `check:runtime` + `verify:api` + `verify:web`), `verify:e2e`, `verify:deployed`. Scripts in `scripts/`: run-api-checks, run-web-checks, check-runtime, verify-e2e, verify-deployed-version, run-sql-verifier (psycopg in the API venv), cursor-shell-guard, githook-pre-commit, graphify and beads pre-push hooks, githook-locate-node/graphify, impeccable-pre-edit-hook (not wired).
- `.cursor/`: one always-on law file `rules/standing-rules.mdc` (old `arbiter-laws.mdc` merged and removed), `security.mdc`, `design.mdc`; commands start, next, status, resume, plan, end (`.claude/commands/end.md` identical); agents gate-reviewer, design-reviewer, security-reviewer; skills rigor, graphiphy (Arbiter tokens), impeccable (engine not vendored), audit, polish, design-taste-frontend; `hooks.json` with the shell guard only; `mcp.json.example`.
- `.cursor/mcp.json` untracked and gitignored (D-050): pulling this commit deletes the owner's local copy; P00 item 16 writes the new one with the Context7 key.
- Node pin 22 -> 24 (`.node-version` replaces `.nvmrc`; CI web job and `apps/web/Dockerfile` follow; D-049).
- `.githooks/` (pre-commit, pre-push), `.beads/` skeleton (empty `issues.jsonl`), `evidence/` (ledger + schema), `.graphifyignore`, `docs/runbooks/bootstrap-fresh-clone.md`, `HYPERPOWER.md`, `PRODUCT.md`, `SECURITY.md` agent section, `CLAUDE.md` in the law style with the startup order and session close through `npm run hp -- end`.
- One em dash removed from a docstring in `services/api/arbiter/models/integrations.py`. No API or contract change: `docs/api-contract.md` and `contracts.py` are unchanged.

Verified in the cloud session (Linux, Node 24.21 from npm, Python 3.13):
- VERIFIED `npm run verify` exit 0 in 2m23s (ruff clean, 441 pytest passed, web lint + i18n:check, tsc, build). `make lint` exit 0.
- VERIFIED evidence record **EV-c769e975** (API ship check, `cli` `node scripts/run-api-checks.mjs`), replayed with `npm run hp -- verify` = VERIFIED. It is a baseline, not assigned to a phase.
- VERIFIED `npm run verify:e2e` against a local stack: `J-01 PASS` .. `J-09 PASS`, `E2E JOURNEYS J-01..J-09 PASS` (not written to the ledger: its replay needs a running stack; P00 records it on Windows).
- VERIFIED git hooks through a real `git commit` and `git push` in a throwaway clone: pre-commit printed `[ruff]`, `[i18n]`, `[env]`, `[dash]` warnings and exited 0; pre-push printed the graphify and beads skip lines (tools not installed) and exited 0.
- VERIFIED core zero-project-strings grep; core identical to the pilot; doctor core integrity clean; shell guard denies reset --hard, force push, curl|sh, literal tokens, unreadable payloads, allows `git status` (by script, not yet through Cursor).
- Doctor on Linux: runtime pin VERIFIED, storage policy WARNING (expected until P00), graphify guard BROKEN (no `graphify.exe`, expected until P00 item 12). `beads health` exits 1 (bd not installed, expected until P00 item 11).

DEFERRED to P00: everything Windows (paths, fnm, uv, Docker Desktop), tool installs, Cursor hook proof, Impeccable engine and its hook, Betterleaks flag check, Beads init and phase beads, Graphify index, Context7 key and convention re-check, journey records.

## Session 2026-10-13 (billing and payout rails, parallel worktree, owner-directed ahead of P03)

Built with tests (D-051..D-054), mocks only: plans catalog as data (seeded Starter/Team/Business/Enterprise), subscriptions, entitlements writer for `org.settings["modules"]`, prepaid credit wallet on the double-entry ledger, period-close overage job, Paddle adapter (merchant of record), Stripe adapter (off unless configured), manual bank-transfer provider with our PDF invoices, signed idempotent webhooks (`/webhooks/paddle`, `/webhooks/stripe`, outside /v1), Payoneer / PayPal / bank-file payout rails with onboarding and minimums, platform fee (default 5 %, 0..8) on quotes and on credited review pay. Web: billing page, public `/pricing`, `/checkout/paddle`, `/reviewer/payouts`, `/admin/billing` (plans editor, org override). Migration `0010` (down_revision `0003`). `docs/api-contract.md` changed (new billing, admin billing and payout rail sections; `/usage` gained `platform_fee`; `Invoice` gained provider fields; quotes gained `platform_fee` / `total_estimate` on human tiers). `contracts.py` unchanged.
Not live: no provider keys used; live Paddle/PayPal/Payoneer setup, webhook destination, Paddle client token + approved domain, test payout stay P03 human steps.

## Open items carried forward
1. Context7 was not used while building; P00 item 16 re-checks the conventions.
2. Payout rails exist (D-052) but are only proven against mocks; live credentials and one test payout are P03.
3. `/healthz` has no `commit` yet; `npm run verify:deployed` needs it (P02 item 6).
4. `apps/web/e2e/ensure_reviewer.py` writes to a local database; running e2e against staging needs a remote path (P02 item 11).
5. Core `status` cannot see Playwright and Impeccable in a monorepo; they are listed under `tools.requiredOutsideRegistry` instead of being patched into the core.

## Next steps (in order)
1. Owner reviews and commits the install (one commit is fine; message without employer or agency names).
2. P00 on Windows, item 1 onward: clone to `E:\arbiter`, runtimes, Docker Postgres, `npm run verify`, stack + `npm run verify:e2e`, tools from the registry, Beads, Graphify, Impeccable, hooks, Cursor hooks, Context7, ledger records, doctor clean, gate.
3. Then P01 measurement (needs provider keys and the EN to SR reference set).
