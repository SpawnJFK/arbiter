# Progress

Last updated: 2026-10-09. Phase: P00 next (`phases/README.md`).

## Exists (built and tested locally)
- **File processing**: 10 formats behind `FormatHandler` (docx, xlsx, pptx, html, md, json, po, txt, csv, xliff), segmenter, tagged text model, round-trip tests, XLIFF 2.1 export.
- **Linguistic**: TM (context 101 / exact / fuzzy via pg_trgm / semantic via pgvector), TMX import with rights confirmation, glossaries with org-wide temporal versions (D-016), four term kinds, Snowball term matching, CSV/TBX import and export, term questions.
- **Engines**: mock, Anthropic, OpenAI, DeepL, Google Basic v2 (D-021), LLM MT, tag protection, cost estimates, registry and scoreboard routing.
- **Quality**: hard QA (tags D-009, numbers, glossary), QE judge (MQM-Core D-010), review senate with arbitration (D-019, D-020), translation senate (D-023), AI editor, calibration with control samples, PROMPT_VERSION tracking (D-022).
- **Pipeline**: Postgres queue + worker (D-031), prepare/translate/score/deadline/merge steps, no_reviewer_policy (D-035), evidence pack JSON + PDF (D-033), webhooks (D-032), append-only provenance.
- **Community**: reviewer apply, qualification tests, task queue, second review, pay (D-024), score (D-025), disputes (D-026), payouts with ledger (D-027, D-028).
- **Billing**: quotes with TM analysis and per-tier pricing (D-030), price lists, usage, invoices with starting tax rule (D-029), double-entry ledger.
- **API**: FastAPI, ~100 endpoints documented in `docs/api-contract.md`; JWT + API keys; idempotency per org.
- **Agency OS**: CRM (accounts, contacts, deals, activities), price lists, workflow templates with presets and validation, dashboards with widget metrics, AI setup assistant (plans only, D-042; replies in the UI locale, D-045).
- **UI localization**: locales and translated UI strings in Postgres, public read endpoints, admin import with merge/replace and placeholder checks (D-046); the web app sends the UI locale and loads translations with English fallback (J-09).
- **Web**: Next.js 16 app for customers (/app), reviewers (/reviewer, keyboard cockpit) and operators (/admin); httpOnly cookie + server proxy (D-036); mock mode for demos; E2E browser test (apps/web/e2e/real-flow.mjs) against a real backend.
- **CLI** (`python -m arbiter.cli`): `seed-demo` (fictional demo org and users), `create-admin`, `calibrate`, `run-worker`.
- **Tests**: 441 backend tests (pytest, mock providers only), including the automated `alembic upgrade head` equals `create_all` check (tests/db). Web: lint with i18n:check, typecheck, build, E2E (J-01..J-09).
- **Infra/docs**: Dockerfiles (web on Node 24), compose, Caddy, backups, CI (lint, tests, builds, compose config), Makefile, deploy guide, runbook, decisions D-001..D-050.
- **HYPERPOWER v2** (installed 2026-10-09, proven on Linux only): control plane `.hyperpower/` (core 1.0.0, hash-locked), `hyperpower.json` schema 2, `phases/` P00..P08, `ACCEPTANCE.md` journeys with verifiers, evidence ledger (baseline record EV-c769e975 VERIFIED), root npm ship check (`npm run verify`, `verify:e2e`, `verify:deployed`), git hooks, Cursor rules/commands/agents/skills/hooks, Beads skeleton, bootstrap runbook.

## Not yet
- P00: the HYPERPOWER layer proven on Windows (tools, hooks through Cursor, Beads graph, Graphify index, Context7, journey records).
- Any measurement on a real pair with real keys (P01).
- Deployment, backups in cron, restore drill (P02).
- Payment provider; real payout provider; legal and tax review; security pass (P03).
- Okapi sidecar (P06), COMET plugin (D-005), SSO (P07).

## Known limitations
- No Snowball stemmer for some languages (e.g. sl, uk, bg, and others outside the Snowball set): exact matching only there.
- CJK term matching is naive (no word segmentation).
- Number check has edge cases (locale formats, ranges, spelled-out numbers).
- Embeddings are mock unless `ARBITER_EMBEDDING_PROVIDER=openai`; semantic TM matches are not meaningful in dev.
- Context7 was not used during the build; library usage was not verified against current docs (P00 item 16).
- `/healthz` does not report the deployed commit yet (P02).

## Next
See activeContext.md "Next steps".
