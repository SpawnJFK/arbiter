# Arbiter

Arbiter (working name) is an AI-native translation platform sold globally. It merges three things translation teams usually buy separately, and adds a fourth:

1. **Business system** (Plunet-like): quotes, projects, jobs, invoicing, vendor payouts.
2. **CAT/TMS** (Trados/Phrase-like): file formats, translation memory, termbase, MT, QA.
3. **Reviewer marketplace** (Smartcat-like): reviewers sign up, pass tests, get paid per decision.
4. **Quality estimation + senate**: independent accuracy, fluency, terminology and consistency judges, with overlap arbitration, decide which segment ships without a human.

Service tiers `auto`, `ai_review`, `hybrid`, `full`; regulated verticals cannot use `auto` or `ai_review`. When no reviewer is available the org's `no_reviewer_policy` (`wait`, `ai_fallback`, `partial`) applies. AI is never silently substituted for a human.
Every segment carries append-only provenance and an evidence pack (JSON + PDF).

## Layout

```
services/api/            Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Postgres 16 (pgvector, pg_trgm)
  arbiter/contracts.py   seams between modules (change = decision in docs/decisions.md)
  arbiter/domain/        state machines (states.py is the only way to change state)
  arbiter/models/        SQLAlchemy models
  arbiter/fileproc/      FormatHandler per format: docx xlsx pptx html md json po txt/csv xliff
  arbiter/linguistic/    TM, glossary, segmentation helpers
  arbiter/engines/       MT + LLM providers (Anthropic, OpenAI, DeepL, Google, mock)
  arbiter/quality/       hard QA, QE judge, senate, calibration
  arbiter/pipeline/      durable Postgres queue + worker
  arbiter/community/     reviewer onboarding, tests, task routing, disputes
  arbiter/billing/       quotes, usage, invoices, payouts (Decimal only)
  arbiter/api/           HTTP layer (contract: docs/api-contract.md)
  migrations/            Alembic
apps/web/                Next.js 16 (client portal, PM exceptions, reviewer workspace, admin)
deploy/                  Docker Compose, Caddy, backups, Hetzner guide
docs/                    design, decisions, runbook, phases, API contract
memory-bank/             current state for the next session (human or agent)
```

## Local development

Requirements: Python 3.13, Node 22, Docker (for Postgres only).

```bash
cp .env.example services/api/.env      # dev defaults work as-is, provider keys can stay empty
make install                           # services/api/.venv + web deps
make dev-db                            # Postgres 16 + pgvector on 127.0.0.1:5432 (dbs arbiter, arbiter_test)
make migrate
make api                               # http://localhost:8000/healthz
make worker                            # second terminal
make web                               # http://localhost:3000
```

Without provider keys everything runs on the mock providers (`mock-mt`, `mock-llm`).

## Tests and lint

```bash
make test     # pytest against arbiter_test; never calls a real provider
make lint     # ruff check + ruff format --check, eslint + tsc
make fmt
```

CI (`.github/workflows/ci.yml`) runs the same checks plus Docker builds of both images.

## Deploy

Single Hetzner host in the EU with Docker Compose and Caddy. Step by step: [deploy/README.md](deploy/README.md). Incidents: [docs/runbook.md](docs/runbook.md).

## More

- [docs/DESIGN.md](docs/DESIGN.md) system design
- [docs/decisions.md](docs/decisions.md) architecture decision log
- [ROADMAP.md](ROADMAP.md) phases P0-P6 and exit criteria
- [CLAUDE.md](CLAUDE.md) rules for AI coding agents working in this repo

Proprietary. See [LICENSE](LICENSE).
