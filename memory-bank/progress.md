# Progress

Last updated: 2026-10-13 (architecture decisions D-079..D-090 and the P00..P09 plan written). Phase: P00 next, item 1 of 19 (`phases/README.md`).

## Exists (built and tested locally)
- **File processing**: formats behind `FormatHandler`: docx, xlsx, pptx, html, md, json, po, txt, csv, tsv, xliff, IDML, SRT/VTT/ASS, XML with ITS rules, DITA, Android/iOS strings and stringsdict, ARB, properties, resx, YAML, AsciiDoc; OCR seam (no engine). Handler options stored per file and used by quote, extract and merge (D-076). Segmenter, tagged text model, round-trip tests, XLIFF 2.1 export.
- **Linguistic**: TM (context 101 / exact / fuzzy via pg_trgm / semantic via pgvector), TMX import with rights confirmation, glossaries with org-wide temporal versions (D-016), four term kinds, Snowball term matching, CSV/TBX import and export, term questions.
- **Engines**: mock, Anthropic, OpenAI, DeepL, Google Basic v2 (D-021), LLM MT, tag protection, cost estimates, registry and scoreboard routing. Engine module (2026-10-13): encrypted engine keys in the DB with org BYOK > platform > env resolution (D-056), Claude on AWS Bedrock and Google Vertex plus generic OpenAI-compatible endpoints, per-org EU processing route with no silent fallback (D-057), routing rules and monthly budgets (D-058), own models: consented dataset export, Together / Fireworks / manual training, held-out evaluation onto the scoreboard, activation (D-059). Web: /app/engines, /app/training, settings region + consent, /admin/engines.
- **Quality**: hard QA (tags D-009, numbers, glossary), QE judge (MQM-Core D-010), review senate with arbitration (D-019, D-020), translation senate (D-023), AI editor, calibration with control samples, PROMPT_VERSION tracking (D-022).
- **Pipeline**: Postgres queue + worker (D-031), prepare/translate/score/deadline/merge steps, no_reviewer_policy (D-035), evidence pack JSON + PDF (D-033), webhooks (D-032), append-only provenance.
- **Community**: reviewer apply, qualification tests, task queue, second review, pay (D-024), score (D-025), disputes (D-026), payouts with ledger (D-027, D-028).
- **Billing**: quotes with TM analysis and per-tier pricing (D-030), price lists, usage, invoices with starting tax rule (D-029), double-entry ledger.
- **Subscription billing** (2026-10-13, D-072..D-075, mocks only): plans as data (admin editor), subscriptions, entitlements writer, prepaid credit wallet, period-close overage, Paddle (merchant of record) / Stripe (off) / manual adapters, signed idempotent webhooks, provider invoice records vs our own PDF invoices, platform fee on human work. Payout rails: Payoneer, PayPal, bank files (SEPA pain.001, CSV, Wise CSV) with onboarding and minimums. Web: billing page, /pricing, /checkout/paddle, /reviewer/payouts, /admin/billing. CLI: `seed-plans`, `close-billing-period`, `refresh-payouts`.
- **API**: FastAPI, ~100 endpoints documented in `docs/api-contract.md`; JWT + API keys; idempotency per org.
- **Agency OS**: CRM (accounts, contacts, deals, activities), price lists, workflow templates with presets and validation, dashboards with widget metrics, AI setup assistant (plans only, D-042; replies in the UI locale, D-045).
- **Vendor management (module pm, 2026-10-13)**: own vendors with pairs, rates, availability, NDA documents and CSV import; per job and step routing to marketplace, own vendor (ranked offers, timeout escalation) or internal user; no-login vendor workbench; purchase orders with PDF; vendor invoices (upload or generated), payables per month, CSV export; job margin includes vendor cost; capacity planner, deadline risk in /exceptions, timeline; PM copilot intents in the assistant (D-067..D-071).
- **UI localization**: locales and translated UI strings in Postgres, public read endpoints, admin import with merge/replace and placeholder checks (D-046); the web app sends the UI locale and loads translations with English fallback (J-09).
- **Web**: Next.js 16 app for customers (/app), reviewers (/reviewer, keyboard cockpit) and operators (/admin); httpOnly cookie + server proxy (D-036); mock mode for demos; E2E browser test (apps/web/e2e/real-flow.mjs) against a real backend.
- **CLI** (`python -m arbiter.cli`): `seed-demo` (fictional demo org and users), `create-admin`, `calibrate`, `run-worker`.
- **Platform and ops (2026-10-13)**: module entitlements and gating, custom roles, team and invites, append-only audit log, OIDC SSO, Fernet secrets (D-052..D-055); S3 or local storage with presigned uploads, queued email (password reset, invites, job and payout notices, vendor offers), PostHog and OpenTelemetry, `/healthz` commit, Kamal configs, release and backup workflows (D-051). Add-ons per plan written by billing (D-077).
- **Software strings (module strings)**: keys, branches, releases, OTA bundles, push/pull, CLI (D-060..D-062).
- **Tests**: 789 backend tests (2026-10-13; was 441) (pytest, mock providers only), including the automated `alembic upgrade head` equals `create_all` check (tests/db). Web: lint with i18n:check, typecheck, build, E2E (J-01..J-09 plus one step per merged section, 30 steps).
- **Infra/docs**: Dockerfiles (web on Node 24), Kamal configs (primary, D-080), compose + Caddy (local and fallback), `release.yml` (build, attest, deploy), `backup.yml` (nightly B2 dump, monthly restore drill), CI (lint, tests, builds, compose config), Makefile, deploy guide, runbook, `docs/infrastructure.md`, `docs/subprocessors.md` (draft), decisions D-001..D-090.
- **Approved architecture (2026-10-13, on paper only)**: Hetzner Cloud VMs behind a load balancer with Kamal 2 and GHCR, Ubicloud Postgres (pgvector to verify), Hetzner Object Storage, Backblaze B2 EU backups, Cloudflare, Tailscale, PostHog EU + Better Stack, Paddle, Payoneer + PayPal; Claude through Anthropic's API by default, EU processing as an add-on (D-079..D-088).
- **HYPERPOWER v2** (installed 2026-10-09, proven on Linux only): control plane `.hyperpower/` (core 1.0.0, hash-locked), `hyperpower.json` schema 2, `phases/` P00..P09 (rewritten 2026-10-13, D-090), `ACCEPTANCE.md` journeys J-01..J-18 and checkpoints INT-01..INT-11 with verifiers, evidence ledger (baseline record EV-c769e975 VERIFIED), root npm ship check (`npm run verify`, `verify:e2e`, `verify:deployed`), git hooks, Cursor rules/commands/agents/skills/hooks, Beads skeleton, bootstrap runbook.

- **Workbench, TM tools, LQA, auditor** (2026-10-13, parallel builder, migration 0008): segment editor API and page `/app/jobs/{id}/editor` (live QA, TM diff, glossary, MT on demand, concordance, comments and client queries, split/merge, find/replace, PM locks, live preview), TM editor/alignment/term extraction/TM QA, job LQA scorecards with PDF/XLSX and org LQA settings, standalone auditor (`/v1/audits`, `/app/auditor`) on the work queue. Decisions D-063..D-066. The e2e opens the editor (edit and confirm) and runs one audit.

## Not yet
- P00: the HYPERPOWER layer proven on Windows (tools, hooks through Cursor, Beads graph P00..P09, Graphify index, Context7), J-10..J-18 markers in `scripts/verify-e2e.mjs`, journey records.
- Any measurement on a real pair with real keys; any real call to Bedrock or Vertex (P01, INT-01..INT-03).
- Any account or cloud resource: Hetzner, Ubicloud (pgvector unverified), Cloudflare, Tailscale, Backblaze B2, PostHog, Better Stack, SMTP provider; staging deploy, backups and restore drill in use, attestation verified (P02, INT-04..INT-08).
- Kamal secret gaps (`ARBITER_SECRETS_KEY` and others not passed; no refusal of dev default keys outside dev and test) (P02 item 7).
- Live Paddle (sandbox, live account, domain approval, webhook destination, client token), Payoneer and PayPal accounts, one test payout; legal and tax review; published DPA, subprocessor list, terms, privacy policy, trust page; security pass (P03). Seat limits are reported, not enforced.
- Production, public status page, calibrated launch languages, first customers (P04).
- Connectors (P05), own models on real data (P06), SAML, SCIM, certification, pen test (P07), white-label (P08), other regions (P09). Okapi sidecar and COMET plugin are backlog (D-090, D-005).
- Engine module: no real call made yet against Bedrock, Vertex (EU host), Together or Fireworks; no resume endpoint for failed jobs (EU route failures need one once the owner adds an EU engine).

## Known limitations
- No Snowball stemmer for some languages (e.g. sl, uk, bg, and others outside the Snowball set): exact matching only there.
- CJK term matching is naive (no word segmentation).
- Number check has edge cases (locale formats, ranges, spelled-out numbers).
- Embeddings are mock unless `ARBITER_EMBEDDING_PROVIDER=openai`; semantic TM matches are not meaningful in dev.
- Context7 was not used during the build; library usage was not verified against current docs (P00 item 16).
- Vendor invoices marked paid are not paid out through the platform rails (D-078).
- Strings and auditor import engines/quality/community internals (module isolation known debt).

## Next
See activeContext.md "Next steps".
