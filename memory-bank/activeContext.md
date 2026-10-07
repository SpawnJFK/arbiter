# Active context

Last updated: 2026-10-07. Phase position: **P0 Measurement harness, foundation complete; measurement not started** (docs/phases/phase-0.md: foundation 10/10, measurement 0/5, ops 0/2). Several P1 and P2 product items are already built (see progress.md); their exit criteria are not met because nothing has run in production.

## Where things stand
The whole system is built and tested locally: file formats, linguistic assets, engines, QE + senate, pipeline and worker, reviewer community, billing, API (~100 endpoints), Agency OS (CRM, price lists, workflow templates, dashboards, AI setup assistant) and the web app with an end-to-end browser test. 432 backend tests. Everything runs on mock providers by default; no real provider key has been used and no measurement exists.

This session (docs only, no code changes):
- `docs/api-contract.md` rewritten to match `services/api/arbiter/api/routes/*.py` (roles per endpoint, error codes, idempotency scope, score scales, Agency OS shapes, DELETE semantics).
- `docs/decisions.md` D-016..D-044 added.
- README, CLAUDE.md architecture map, ROADMAP status, phase checklists, `.env.example` (new settings: CORS origins, seller country, VAT rate, 32-char JWT secret, web API_URL / mock flag).

## Open items found while documenting
1. `deploy/docker-compose.yml` does not pass `ARBITER_CORS_ORIGINS`, `ARBITER_SELLER_COUNTRY`, `ARBITER_VAT_RATE`, and the web service has no `API_URL` (should be `http://api:8000`). `ARBITER_JWT_SECRET` must now be at least 32 characters.
2. `apps/web` now has its own `Dockerfile`; compose and CI still build the web image from `deploy/web.Dockerfile`. Pick one and remove the other.
3. No automated test that `alembic upgrade head` equals `metadata.create_all` (D-037 relies on it).
4. Payouts in prod only accrue: no payout provider integration.
5. Context7 was not used while building; library calls were not checked against current docs.
6. The web E2E script's assistant prompt uses fictional company names; keep any agency-like name in fixtures clearly fictional.

## Next steps (in order)
1. Fix open items 1-3 (small, infra).
2. P0 measurement: get real provider keys from the owner, assemble the EN to SR reference set with human MQM labels, write the harness script, run threshold sweeps, record numbers.
3. Staging deploy on Hetzner per deploy/README.md, backups in cron, one restore drill.
4. Then P1 gaps: payment provider, real payout provider, legal and tax review, error tracking.
