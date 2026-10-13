# Active context

Last updated: 2026-10-13 (module integration). Phase position: **P00 next, item 1 of 18** (`phases/phase-00-install-and-verify.md`). HYPERPOWER v2 is installed in the repo (uncommitted at the end of the install session; the owner commits). Nothing in the HYPERPOWER layer is proven on the owner's Windows machine yet.

Next gate: `npm run hp -- gate P00 --product`.

## Session 2026-10-13 (integration of the eight parallel module builds)

Merged into main in this order, each with a merge commit: infra, platform, engines, strings, fileproc, workbench, vendors, billing; then one integration commit and one e2e commit. Not pushed (the lead pushes). Outside the phase order by the owner's request; tick nothing in `phases/`.
- Migrations: one linear chain 0001 .. 0011. New 0011 adds `files.options`, `upload_sessions.options`, `plans.addons` and seeds the starter billing catalog (moved from 0010, because the seed uses the ORM model). `dbinit.LATER_TABLES / LATER_COLUMNS / LATER_INDEXES` hold the union; `tests/db` (alembic head == create_all) passes.
- Decisions renumbered in merge order, references updated in code and docs: infra D-051 (new entry), platform D-052..D-055, engines D-056..D-059, strings D-060..D-062, workbench D-063..D-066, vendors D-067..D-071, billing D-072..D-075, integration D-076..D-078.
- Unified: one invite flow (platform `user_invites` + `/v1/auth/invite/accept`, email through `notify.send_invite`); password reset keeps `account_tokens` and accepts reset tokens only; one Fernet helper (`platform/secrets.py`, `arbiter/crypto.py` removed); vendor offer emails through `notify.vendor_message`; billing is the only writer of `org.settings["modules"]` and `["addons"]` (the platform module editor stores overrides, D-077); handler options from upload to merge (D-076).
- **api-contract.md changed** (all builder sections merged; file options, add-ons, module mapping, webhook events, invite vs reset). **contracts.py changed** by the engines build (`region` on MtEngine and LlmClient, D-057); the web app matches.
- Web: nav sections mapped to modules (engines/training -> engine, auditor -> auditor, strings -> strings, vendors/POs/vendor invoices/capacity/assistant -> pm, queries/editor -> tms, quality -> ai, billing always visible); platform audit-log client methods renamed `auditLog`/`auditLogExportUrl` (name clash with the auditor); add-ons shown read-only on Settings > Modules and the admin org page; subtitle line limit in the new-project wizard.
- VERIFIED on Linux, Node 22 (check:runtime skipped): ruff check + format clean, pytest 789 passed, web `npm ci`, lint + i18n:check, `tsc --noEmit`, `next build`; real browser e2e `npm run e2e` 30 steps passed against a fresh dev DB (alembic head, seed-demo), API, worker and `next start`, including the presigned upload flow and one step per new section.
- Not wired: vendor invoices marked paid do not use the platform payout rails (an agency pays its own vendors; the rails pay marketplace reviewers from platform funds, D-078). Module isolation: strings and auditor import engines/quality/community internals, recorded as known debt in `tests/platform/test_module_isolation.py`. Seat limits are still not enforced.

## Session 2026-10-13 (parallel builder: agency vendor management, module pm)

Built on b95f0a8 (platform module and permission seams) in an isolated worktree; outside the phase order by the owner's request (parallel module build).
- Own vendors (`vendors`, `vendor_absences`, `vendor_documents`), assignments of human steps (`vendor_assignments`), `number_series`, `purchase_orders`, `vendor_invoices`, `jobs.cost_vendors`: models in `models/vendors.py`, migration `0009_vendors` (down_revision 0008 after the merge), listed in `dbinit.LATER_TABLES` / `LATER_COLUMNS`.
- Services: `agency/vendors.py` (CRUD, CSV import, rates, number series, notify-or-log), `agency/assignments.py` (routing, ranked offers, timeout work item `vendor.offer_timeout`, signed workbench token, vendor decisions through `hooks.segment_reviewed`, approve/reopen/cancel), `agency/procurement.py` (PO + PDF, vendor invoices upload/auto, statuses, payables, CSV), `agency/capacity.py` (planner, deadline risk, timeline), `agency/copilot.py` + `agency/heuristic_pm.py` (PM copilot).
- Pipeline: `orchestrator._queue_review` / `reroute_open_segments` / `segment_step` / `open_step_segments`; default stays the marketplace (D-068). Worker dispatches `vendor.*`. `/exceptions` adds `deadline_risk`. State machines `assignment`, `purchase_order`, `vendor_invoice` in `domain/states.py` (`transition_status`).
- API: `routes/vendors.py` (module pm, writes need `vendors.manage`) and `routes/vendor_portal.py` (no login, token). `docs/api-contract.md` has the new "Vendors (module pm)" section and the PM copilot paragraph. `contracts.py` unchanged. Assistant prompt version 2026-10-13.1 (two new action types).
- Web: `/app/vendors` (+ profile tabs, CSV import), assignment picker on the job page, `/app/purchase-orders`, `/app/vendor-invoices` (payables, auto-invoice, CSV), `/app/capacity` (planner, two-week timeline, risk), public `/vendor/[token]` workbench with its own proxy `/api/vendor-portal/*`, nav section, assistant examples. New setting `ARBITER_WEB_BASE_URL`.
- Decisions D-067..D-071 (numbered high to avoid clashes with other parallel builders; renumber on merge if needed).
- VERIFIED `npm run verify:api` (462 tests) and `npm run verify:web` on Node 22 (check:runtime and e2e skipped by instruction). Smoke: API + `next start` against the test DB, every new page 200 without error boundary, workbench and PO PDF through the public proxy.
- Not done at build time (integration since fixed e-mail through notify and nav gating): e2e journey for the full vendor flow, vendor document file upload.

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

## Session 2026-10-13 (engine module: keys, EU route, routing, budgets, own models; parallel worktree build)

What changed: migration 0006 (`engine_credentials`, `engine_routes`, `engine_budgets`, `training_jobs`, `custom_models`, down_revision 0005 after the merge), `arbiter/crypto.py` (merged into `platform/secrets.py` at integration), `arbiter/engines/{bedrock,vertex,openai_compatible,credentials,catalog,routing,budgets,errors,probe,manage}.py`, registry with `EngineContext`, `arbiter/training/`, routes `engines.py`, `admin_engines.py`, `training.py`, org settings `processing_region` and `training_consent`, worker step kinds `training.poll` / `training.evaluate`, evidence pack `processing` block. **contracts.py changed**: `MtEngine` and `LlmClient` gain `region` (D-057). **api-contract.md changed**: Engines, Platform engines, Own models sections; `Org` and `PATCH /org` fields. The web app matches (types, api client, pages). Decisions D-056..D-059 (renumber if parallel builds took these numbers). Not a phase item: built ahead of the phase plan on the owner's request; tick nothing in `phases/`.
Verified: `npm run verify:api` and `npm run verify:web` exit 0 (Node 22 session; check:runtime and e2e skipped).
## Session 2026-10-13 (billing and payout rails, parallel worktree, owner-directed ahead of P03)

Built with tests (D-072..D-075), mocks only: plans catalog as data (seeded Starter/Team/Business/Enterprise), subscriptions, entitlements writer for `org.settings["modules"]`, prepaid credit wallet on the double-entry ledger, period-close overage job, Paddle adapter (merchant of record), Stripe adapter (off unless configured), manual bank-transfer provider with our PDF invoices, signed idempotent webhooks (`/webhooks/paddle`, `/webhooks/stripe`, outside /v1), Payoneer / PayPal / bank-file payout rails with onboarding and minimums, platform fee (default 5 %, 0..8) on quotes and on credited review pay. Web: billing page, public `/pricing`, `/checkout/paddle`, `/reviewer/payouts`, `/admin/billing` (plans editor, org override). Migration `0010` (down_revision `0009` after the merge; its catalog seed moved to 0011). `docs/api-contract.md` changed (new billing, admin billing and payout rail sections; `/usage` gained `platform_fee`; `Invoice` gained provider fields; quotes gained `platform_fee` / `total_estimate` on human tiers). `contracts.py` unchanged.
Not live: no provider keys used; live Paddle/PayPal/Payoneer setup, webhook destination, Paddle client token + approved domain, test payout stay P03 human steps.

## Open items carried forward
1. Context7 was not used while building; P00 item 16 re-checks the conventions.
2. Payout rails exist (D-073) but are only proven against mocks; live credentials and one test payout are P03.
3. `/healthz` reports `commit` (ARBITER_GIT_SHA) since the infra merge; `npm run verify:deployed` still needs a deployment (P02 item 6).
4. `apps/web/e2e/ensure_reviewer.py` writes to a local database; running e2e against staging needs a remote path (P02 item 11).
5. Core `status` cannot see Playwright and Impeccable in a monorepo; they are listed under `tools.requiredOutsideRegistry` instead of being patched into the core.

## Next steps (in order)
1. Owner reviews and commits the install (one commit is fine; message without employer or agency names).
2. P00 on Windows, item 1 onward: clone to `E:\arbiter`, runtimes, Docker Postgres, `npm run verify`, stack + `npm run verify:e2e`, tools from the registry, Beads, Graphify, Impeccable, hooks, Cursor hooks, Context7, ledger records, doctor clean, gate.
3. Then P01 measurement (needs provider keys and the EN to SR reference set).
