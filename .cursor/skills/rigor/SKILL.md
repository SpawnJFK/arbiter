---
name: rigor
description: Engineering proof discipline for Arbiter. Turns "it works" into replayable evidence, reports in VERIFIED / DEFERRED / BROKEN, and checks Context7 provenance before a phase closes. Use before ticking progress.md, on /end, on /status, before a gate, and whenever a claim of done is made. Not for visual design (use impeccable and design-taste-frontend).
version: 2.0.0
---

# Rigor

A file existing is not proof. A test that passed once in a chat is not proof. Proof is a record in `evidence/ledger.jsonl` whose verifier `npm run hp -- verify` re-runs and finds VERIFIED.

## When to run

- Before ticking any item in `memory-bank/progress.md` or a phase file.
- Inside `/end` and `/status`.
- Before `npm run hp -- gate P0x --product`.
- After a change that touches more than 5 files, any migration, `contracts.py` or `docs/api-contract.md`.

## Steps

1. **Name the claim** in one sentence a non-engineer can check ("an auto-tier job is delivered with a downloadable evidence PDF").
2. **Pick the verifier kind** the journey in `ACCEPTANCE.md` lists. Kinds in core: `cli`, `sql`, `http`, `commit-exists`, `playwright`. Arbiter uses mostly `cli`:
   - `node scripts/run-api-checks.mjs` (ruff + pytest),
   - `node scripts/verify-e2e.mjs` with `expectOutputContains: "J-0n PASS"` (needs API, worker and web running),
   - `node scripts/verify-deployed-version.mjs` after a deploy,
   - `sql` through `scripts/run-sql-verifier.mjs` (read-only, single statement, API venv psycopg).
   The core's `cli` verifier rewrites every argument of a `node` command into a repo path, so verifier scripts take no arguments; narrow them with `expectOutputContains`.
3. **Run it** and save the output under `evidence/<phase>/` with a repo-relative path (`evidence/p00/api-checks.txt`). Absolute paths for `.json` or `.log` files are blocked by the guard.
4. **Append the record**: a JSON file with `claim`, `tier: "replayable"`, `verifier`, `artifact`, `status`, then `npm run hp -- evidence append <file>`. Add the returned id to `hyperpower.json` `phases.P0x.evidenceIds` and to the journey's Status line in `ACCEPTANCE.md`.
5. **Replay** with `npm run hp -- verify <id>`. Only VERIFIED counts.

## Gauntlet before a push

```
npm run verify
npm run hp -- doctor
npm run hp -- verify
```

`npm run verify` is: runtime pins, API ruff check + ruff format --check + pytest, web lint (ESLint + i18n:check) + typecheck + build. For UI or flow changes also `npm run verify:e2e` against a running stack. Do not push if any step fails.

## Context7 provenance

For every library or framework convention touched in the phase (FastAPI, SQLAlchemy 2, Alembic, pydantic v2, psycopg, pgvector, Next.js 16, React 19, Tailwind 4, Playwright, provider SDKs), `memory-bank/context7-log.md` must have a line with the version. Missing line: the phase is not done.

## Reporting

Three buckets only, each item with its evidence id or the exact error:

- **VERIFIED**: replayed and passing.
- **DEFERRED**: not proven yet, with the phase that will prove it.
- **BROKEN**: failing, with the command and the first error line.

Never move an item from BROKEN to VERIFIED without a new ledger record. Never invent customers, revenue or metrics: a number in a report comes from a ledger artifact.
