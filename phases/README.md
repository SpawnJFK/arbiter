# Phases

Frozen order. Work only on the current phase (`memory-bank/activeContext.md` names it). A phase closes when `npm run hp -- gate P0x --product` exits 0, which means: every evidence record listed for the phase in `hyperpower.json` re-verifies, `npm run verify` passes, and the phase bead reads back as closed from Beads.

| Phase | File | Journeys | Depends on | Human steps | Declared spend |
| --- | --- | --- | --- | --- | --- |
| P00 | `phase-00-install-and-verify.md` | J-01 to J-09 replayed locally on Windows | none | Docker Desktop install (if missing), Context7 key paste, Cursor restart | none |
| P01 | `phase-01-measurement-harness.md` | INT-01, INT-02, INT-03 | P00 | Provider accounts and keys with spend caps, EN to SR reference documents and human MQM labels | provider usage up to the budget the owner names with "apply" |
| P02 | `phase-02-staging-deploy.md` | INT-04, INT-05; J-01 to J-03 on staging | P01 | Domain choice, Hetzner API token, DNS access, object storage keys | Hetzner server and object storage, exact price recorded before create |
| P03 | `phase-03-money-and-legal.md` | INT-06; new money journeys J-10, J-11 | P02 | Payment and payout provider accounts, legal and tax review | provider transaction fees, one small test payout |
| P04 | `phase-04-self-serve-launch.md` | J-01 to J-11 on production | P03 | Production domain, reviewers for 3 languages, launch "apply" | production server, declared in the phase |
| P05 | `phase-05-integrations.md` | new connector journeys | P04 | GitHub App, Figma and CMS sandbox accounts | none |
| P06 | `phase-06-okapi-formats.md` | J-01 extended to new formats | P04 | none | none (sidecar runs on the existing host) |
| P07 | `phase-07-enterprise.md` | new SSO and audit journeys | P04 | IdP test tenants, auditor and pen-test vendor | auditor and pen-test fees, declared in the phase |
| P08 | `phase-08-white-label.md` | new tenant-isolation journeys | P04 | A pilot agency's domain and branding | none |

Beads: P00 creates one bead per phase and writes its id into `hyperpower.json` `phases.P0x.beadId`. Until then every phase shows `bead: "to be created in P00"`.

Every phase file has the same sections: Goal, Scope, Human-only steps, Declared spend, Acceptance, Exit gate, Out of scope. If a phase needs a human step that is not listed, first check whether a CLI, MCP or API can do it (`CLAUDE.md` law 2); only then add it, with exact click paths.

## Mapping from the earlier plan

Until 2026-10-09 the plan lived in `docs/phases/phase-0..6.md` with ROADMAP numbers P0 to P6 (decision D-048). Older decisions and notes that say "P0" or "P4" mean the earlier numbers:

| Earlier | Now |
| --- | --- |
| P0 Measurement harness (foundation, measurement, ops) | foundation: built; measurement: P01; ops (staging, backups, restore drill): P02 |
| P1 MVP self-serve | built items stay built; payment provider, legal and tax review, security pass: P03; 3 calibrated languages, monitoring, production: P04 |
| P2 Reviewer community at scale | built items stay built; payout provider, reconciliation, contractor terms: P03; wait-time monitoring: P04 |
| P3 Integrations | P05 |
| P4 More formats via Okapi | P06 |
| P5 Enterprise | P07 |
| P6 White-label for agencies | P08 |

## Already built (before HYPERPOWER, tested locally, never deployed)

Everything below exists in code with automated tests (439 backend tests, web lint/typecheck/build, the `real-flow.mjs` browser test for J-01..J-09). It is not re-done in any phase; P00 replays it into the evidence ledger on the owner's machine. Details: `memory-bank/progress.md`.

- Monorepo, config (`ARBITER_*`), `contracts.py`, state machines, SQLAlchemy models, Alembic migrations 0001 to 0003, append-only provenance trigger, automated `alembic upgrade head` equals `create_all` check (D-037).
- File formats: docx, xlsx, pptx, html, md, json, po, txt, csv, xliff with round-trip tests; XLIFF 2.1 export.
- Linguistic: segmentation (R-SEG), TM exact/fuzzy/semantic (R-TM), glossaries with org-wide temporal versions and Snowball term checks (R-GL).
- Engines: mock, Anthropic, OpenAI, DeepL, Google Basic v2, LLM MT, tag protection, scoreboard routing (R-MT). Never run with a real key yet.
- Quality: hard QA (D-009), QE judge (MQM-Core, D-010), review and translation senates, AI editor, calibration with control samples.
- Pipeline: `work_items` queue and worker, deadline policies, no-reviewer policy, evidence pack JSON + PDF, signed webhooks.
- Community: apply, qualification tests, task queue and keyboard cockpit, second review, per-decision pay, score, disputes, payout runs on the ledger (mock provider).
- Billing: quotes with TM analysis and per-tier price/ETA, price lists, usage, invoices (D-029), double-entry ledger.
- Agency OS: CRM, price lists, workflow templates, dashboards, AI setup assistant (plans only, D-042).
- UI localization: English catalog in the web repo, translations in the database (D-046); web app sends the UI locale to the assistant.
- Web: Next.js 16 app for `/app`, `/reviewer`, `/admin`; httpOnly cookie proxy (D-036); mock mode.
- Infra on paper: Dockerfiles, compose, Caddy, `deploy/backup.sh`, CI (lint, tests, builds, compose config), Hetzner guide, runbook.
