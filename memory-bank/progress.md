# Progress

Last updated: 2026-10-07.

## Exists
- **Backend core**: pyproject (Python 3.13 runtime, >=3.12 supported), `config.py` (all `ARBITER_*` settings), `contracts.py`, `domain/states.py`, `db.py`, `dbinit.py`.
- **Data model**: tenancy, content, assets, quality, reviewers, money (Decimal, double-entry ledger), integrations (work_items queue, webhooks, idempotency), provenance (append-only trigger). Alembic migration 0001.
- **File processing**: FormatHandler + docx, xlsx, pptx, html, md, json, po, txt/csv, xliff, segmenter, registry; tests incl. round-trip.
- **Linguistic / engines / quality**: in progress by parallel agents (see activeContext.md).
- **Infra**: `services/api/Dockerfile` (+ entrypoint with `ARBITER_MIGRATE_ON_START`), `deploy/web.Dockerfile`, `deploy/docker-compose.yml` (postgres pgvector pg16, api, worker, web, caddy), `deploy/docker-compose.dev.yml` (+ `initdb` creating `arbiter_test`), `deploy/Caddyfile`, `deploy/backup.sh`, `deploy/README.md`, `.github/workflows/ci.yml`, `Makefile`, `.env.example`.
- **Docs**: README, CLAUDE.md, AGENTS.md, docs/DESIGN.md, docs/decisions.md (D-001..D-015), ROADMAP.md, docs/phases/phase-0..6.md, docs/runbook.md, SECURITY.md, LICENSE (proprietary).

## Not yet
- FastAPI app (`arbiter.api.app`), pipeline worker, community, billing.
- Web UI beyond scaffold.
- Any deployment (no server yet), any measurement results.

## Validation done
- Compose files validated with `docker compose config` (with env set); YAML of CI and compose parsed; Makefile targets dry-run OK; backup.sh `bash -n` OK.

## Next
See activeContext.md "Next steps".
