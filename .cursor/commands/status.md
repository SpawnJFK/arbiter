# /status

Live health check. Changes nothing. Run everything, report in three buckets, keep it short.

```
npm run hp -- doctor
npm run hp -- status
npm run hp -- verify
git status -sb
git log --oneline -10
gh run list --limit 3
```

Also, when they exist for the current phase:

- Local Postgres up? `docker compose -f deploy/docker-compose.dev.yml ps` (or `pg_isready -h localhost`).
- Alembic head: `services/api/.venv` python `-m alembic heads` in services/api; newest D-0NN in `docs/decisions.md`.
- API: `http://localhost:8000/healthz` returns `ok: true`; web on `http://localhost:3000`.
- Staging: `npm run verify:deployed` (from P02 on).
- Beads: `npm run hp -- beads health` (from P00 on).

Report:

```
Arbiter status, <date>
Phase: P0x, item n of m. Next gate: npm run hp -- gate P0x --product
Git: <branch>, <clean | dirty>, HEAD <short sha> <= | != origin/main>, CI <result>
VERIFIED: <items with evidence ids>
DEFERRED: <items with the phase that proves them>
BROKEN:   <command and first error line>
```
