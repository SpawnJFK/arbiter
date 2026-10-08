# Progress

Last updated: 2026-10-08.

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
- **UI localization store**: locales and translated UI strings in Postgres, public read endpoints, admin import with merge/replace and placeholder checks (D-046). English source catalog lives in the web repo.
- **Web**: Next.js 16 app for customers (/app), reviewers (/reviewer, keyboard cockpit) and operators (/admin); httpOnly cookie + server proxy (D-036); mock mode for demos; E2E browser test `npm run e2e` (apps/web/e2e/real-flow.mjs) against a real backend.
- **CLI** (`python -m arbiter.cli`): `seed-demo` (fictional demo org and users), `create-admin`, `calibrate`, `run-worker`.
- **Tests**: 439 backend tests (pytest, mock providers only). Web: lint, typecheck, build, E2E.
- **Infra/docs**: Dockerfiles, compose, Caddy, backups, CI, Makefile, deploy guide, runbook, decisions D-001..D-046.

## Not yet
- Any measurement on a real pair with real keys (P0 core).
- Deployment (no server), backups in cron, restore drill.
- Payment provider; real payout provider (prod payouts only accrue).
- Legal and tax review (terms, DPA, subprocessor list, VAT rule, reviewer contractor terms).
- Okapi sidecar (P4), COMET plugin (D-005), SSO (P5).

## Known limitations
- No Snowball stemmer for some languages (e.g. sl, uk, bg, and others outside the Snowball set): exact matching only there.
- CJK term matching is naive (no word segmentation).
- Number check has edge cases (locale formats, ranges, spelled-out numbers).
- Embeddings are mock unless `ARBITER_EMBEDDING_PROVIDER=openai`; semantic TM matches are not meaningful in dev.
- No automated parity test between `alembic upgrade head` and `create_all`.
- Context7 was not used during the build; library usage was not verified against current docs.
- Compose file lags the config (see activeContext.md open items).

## Next
See activeContext.md "Next steps".
