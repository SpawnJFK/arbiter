# Arbiter

Arbiter (working name) is an AI-native translation platform sold globally. It merges three things translation teams usually buy separately, and adds a fourth:

1. **Business system** (Plunet-like): quotes, projects, jobs, invoicing, vendor payouts, plus the Agency OS layer (CRM, client price lists, workflow templates, dashboards).
2. **CAT/TMS** (Trados/Phrase-like): file formats, translation memory, termbase, MT, QA.
3. **Reviewer marketplace** (Smartcat-like): reviewers sign up, pass tests, get paid per decision.
4. **Quality estimation + senate**: independent accuracy, fluency, terminology and consistency judges, with overlap arbitration, decide which segment ships without a human.

Service tiers `auto`, `ai_review`, `hybrid`, `full`; regulated verticals cannot use `auto` or `ai_review`. When no reviewer is available the org's `no_reviewer_policy` (`wait`, `ai_fallback`, `partial`) applies. AI is never silently substituted for a human. Every segment carries append-only provenance and an evidence pack (JSON + PDF).

## Features

- **Files**: docx, xlsx, pptx, html, md, json, po, txt, csv, xliff; inline formatting preserved as tagged text; XLIFF 2.1 export.
- **Linguistic assets**: TM (in-context 101, exact, fuzzy, semantic), TMX import/export with rights confirmation; glossaries with mandatory / preferred / forbidden / do-not-translate terms, versioned and frozen per job; CSV/TBX import/export; term questions.
- **Engines**: Anthropic, OpenAI, DeepL, Google, mock providers; per-pair scoreboard routing; best-of-N translation senate.
- **Quality**: hard QA (tags, numbers, glossary), MQM-Core QE judge, review senate, AI editor, calibrated thresholds per org / content type / target language, 2% blind control samples, escaped-error reporting.
- **Pipeline**: durable Postgres queue and worker, deadline policies, evidence packs, signed webhooks.
- **Reviewer community**: application, qualification tests, task queue with keyboard cockpit, second review, per-decision pay, reviewer score, disputes, payouts on a double-entry ledger.
- **Billing**: quotes with TM analysis and per-tier price/ETA, client price lists, usage, monthly invoices.
- **Agency OS**: CRM (accounts, contacts, deals pipeline, activities), price lists, executable workflow templates (TM, MT, QE, senate, AI review, human review, second review, client approval), dashboards (KPI, charts, pipeline, tables).
- **AI setup assistant**: describe your agency in plain language; it proposes a plan (workflows, price lists, accounts, dashboards...) that a human reviews and applies.
- **API**: about 100 endpoints, JWT or API keys, idempotent creates. Contract: [docs/api-contract.md](docs/api-contract.md).

## Layout

```
services/api/            Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Postgres 16 (pgvector, pg_trgm)
  arbiter/contracts.py   seams between modules (change = decision in docs/decisions.md)
  arbiter/domain/        state machines (states.py is the only way to change state)
  arbiter/models/        SQLAlchemy models
  arbiter/fileproc/      FormatHandler per format
  arbiter/linguistic/    TM, glossary, stemming, embeddings
  arbiter/engines/       MT + LLM providers
  arbiter/quality/       hard QA, QE judge, senate, editor, calibration
  arbiter/pipeline/      orchestrator, durable queue, worker, evidence
  arbiter/community/     reviewers, tests, task queue, pay, score, disputes, payouts
  arbiter/billing/       quotes, pricing, usage, invoices, ledger
  arbiter/agency/        Agency OS: CRM, price lists, workflows, dashboards, assistant
  arbiter/api/           HTTP layer (routes/*.py)
  arbiter/cli.py         operator CLI
  migrations/            Alembic
apps/web/                Next.js 16: customers (/app), reviewers (/reviewer), operators (/admin); e2e/
deploy/                  Docker Compose, Caddy, backups, Hetzner guide
docs/                    system design, decisions, runbooks, API contract
phases/                  the phase plan (P00..P08) in HYPERPOWER format
memory-bank/             current state for the next session (human or agent)
evidence/                append-only evidence ledger (replayable proof)
.hyperpower/             agent control plane (see HYPERPOWER.md)
```

## Local development

Requirements: Python 3.13 (`.python-version`), Node 24 (`.node-version`), Docker (for Postgres only). On Windows use uv for Python and the root npm scripts instead of make: `docs/runbooks/bootstrap-fresh-clone.md`.

```bash
cp .env.example services/api/.env      # dev defaults work as-is, provider keys can stay empty
make install                           # services/api/.venv + web deps
make dev-db                            # Postgres 16 + pgvector on 127.0.0.1:5432 (dbs arbiter, arbiter_test)
make migrate
cd services/api && .venv/bin/python -m arbiter.cli seed-demo && cd -   # fictional demo data
make api                               # http://localhost:8000/healthz, docs at /docs
make worker                            # second terminal
make web                               # http://localhost:3000
```

Demo logins after `seed-demo` (all fictional, password `demo-password-123`):

| Email | Role |
|---|---|
| pm@demo.test | project manager (customer org) |
| client@demo.test | client user (no money fields) |
| reviewer@demo.test | reviewer |
| reviewer2@demo.test | senior reviewer (needed for second review) |
| admin@demo.test | platform operator |

Without provider keys everything runs on the mock providers (`mock-mt`, `mock-llm`); the assistant then uses its built-in heuristic planner. The web app can also run with no backend at all: `cd apps/web && npm run dev:mock`.

Operator CLI (`python -m arbiter.cli ...` in services/api): `seed-demo`, `create-admin`, `calibrate`, `run-worker`.

## Tests and lint

```bash
npm run verify   # the ship check: runtime pins, ruff, pytest, web lint + i18n, typecheck, build (any OS)
npm run verify:e2e   # J-01..J-09 against a running API + worker + web
make test     # 439 backend tests against arbiter_test; never calls a real provider
make lint     # ruff check + ruff format --check, eslint + tsc
make fmt
cd apps/web && npm run e2e   # browser end-to-end against a running API + worker (see apps/web/README.md)
```

CI (`.github/workflows/ci.yml`) runs lint, tests, web build and Docker builds of both images.

## Deploy

Single Hetzner host in the EU with Docker Compose and Caddy. Step by step: [deploy/README.md](deploy/README.md). Incidents: [docs/runbook.md](docs/runbook.md).

## More

- [docs/DESIGN.md](docs/DESIGN.md) system design
- [docs/decisions.md](docs/decisions.md) architecture decision log (D-001..D-050)
- [ROADMAP.md](ROADMAP.md) phases P00-P08 and exit criteria; [phases/](phases/README.md) the working plan
- [PRODUCT.md](PRODUCT.md) what Arbiter is and is not, who pays
- [ACCEPTANCE.md](ACCEPTANCE.md) journeys and integration checkpoints
- [HYPERPOWER.md](HYPERPOWER.md) the agent operating system (control plane, evidence, gates, hooks)
- [memory-bank/progress.md](memory-bank/progress.md) what exists, what is missing, known limitations
- [CLAUDE.md](CLAUDE.md) rules for AI coding agents working in this repo

Proprietary. See [LICENSE](LICENSE).
