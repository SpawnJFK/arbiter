# Active context

Last updated: 2026-10-08. Phase position: **P0 Measurement harness, foundation complete; measurement not started** (docs/phases/phase-0.md: foundation 10/10, measurement 0/5, ops 0/2). Several P1 and P2 product items are already built (see progress.md); their exit criteria are not met because nothing has run in production.

## Where things stand
The whole system is built and tested locally: file formats, linguistic assets, engines, QE + senate, pipeline and worker, reviewer community, billing, API (~100 endpoints), Agency OS (CRM, price lists, workflow templates, dashboards, AI setup assistant) and the web app with an end-to-end browser test. 432 backend tests. Everything runs on mock providers by default; no real provider key has been used and no measurement exists.

Session 2026-10-08 (backend, English-first, D-045 / D-046):
- Assistant: `locale` on POST /assistant/threads/{id}/messages; prompt version 2026-10-08.1; built-in planner output is English only (Serbian still parsed), note for other locales.
- UI string store: `ui_locales` / `ui_messages` (migration 0003_ui_i18n, hand-written; alembic == create_all verified on a scratch DB), public `GET /v1/i18n/locales`, `GET /v1/i18n/messages/{locale}`, admin `PUT/DELETE /v1/admin/i18n/...` with merge/replace and ICU placeholder checks.
- `docs/api-contract.md` changed (assistant `locale`, new "UI string localization" section): the web app must send `locale` and load translations from `/v1/i18n`.
- 439 backend tests green, ruff clean.

Previous session (docs only, no code changes):
- `docs/api-contract.md` rewritten to match `services/api/arbiter/api/routes/*.py` (roles per endpoint, error codes, idempotency scope, score scales, Agency OS shapes, DELETE semantics).
- `docs/decisions.md` D-016..D-044 added.
- README, CLAUDE.md architecture map, ROADMAP status, phase checklists, `.env.example` (new settings: CORS origins, seller country, VAT rate, 32-char JWT secret, web API_URL / mock flag).

## Open items found while documenting (1, 2, 3 and 6 resolved on 2026-10-09)
1. `deploy/docker-compose.yml` does not pass `ARBITER_CORS_ORIGINS`, `ARBITER_SELLER_COUNTRY`, `ARBITER_VAT_RATE`, and the web service has no `API_URL` (should be `http://api:8000`). `ARBITER_JWT_SECRET` must now be at least 32 characters.
2. `apps/web` now has its own `Dockerfile`; compose and CI still build the web image from `deploy/web.Dockerfile`. Pick one and remove the other.
3. No automated test that `alembic upgrade head` equals `metadata.create_all` (D-037 relies on it). It was checked by hand with a scratch DB for 0002 and 0003.
4. Payouts in prod only accrue: no payout provider integration.
5. Context7 was not used while building; library calls were not checked against current docs.
6. The web E2E script's assistant prompt uses fictional company names; keep any agency-like name in fixtures clearly fictional.

## Session 2026-10-09
- Repo pushed to github.com/SpawnJFK/arbiter (private, main). GitHub Actions green on first run: api (ruff + pytest), web (lint + tsc + build), docker build api + web, compose config.
- Compose passes CORS / seller country / VAT rate, web gets API_URL=http://api:8000; single web Dockerfile (apps/web/Dockerfile).
- Automated D-037 check: tests/db/test_db_migrations_match.py builds two scratch DBs (alembic head vs create_all) and compares them.
- Cursor layer: .cursor/rules/arbiter-laws.mdc, .cursor/mcp.json (Context7 hosted HTTP), /status and /end commands, ACCEPTANCE.md (J-01..J-09 automated, INT-01..INT-06 open), hyperpower.json manifest, .nvmrc 22, .python-version 3.13.
- Beads and Graphify are not installed yet: they arrive with the hyperpower v2 core.

## Next steps (in order)
1. Fix open items 1-3 (small, infra). Web: send the UI `locale` to the assistant, load `/v1/i18n/messages/{locale}` with English fallback, admin screen for locales and imports.
2. P0 measurement: get real provider keys from the owner, assemble the EN to SR reference set with human MQM labels, write the harness script, run threshold sweeps, record numbers.
3. Staging deploy on Hetzner per deploy/README.md, backups in cron, one restore drill.
4. Then P1 gaps: payment provider, real payout provider, legal and tax review, error tracking.
