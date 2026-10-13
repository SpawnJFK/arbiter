# Arbiter

Arbiter (working name) is an AI-native translation platform sold globally, English-first. It merges three things translation teams usually buy separately, and adds a fourth:

1. **Business system** (Plunet-like): quotes, projects, jobs, subscriptions, invoicing, payouts, plus the Agency OS (CRM, price lists, workflow templates, dashboards, own vendors).
2. **CAT/TMS** (Trados/Phrase-like): file formats, translation memory, termbase, workbench, software strings, MT, QA.
3. **Reviewer marketplace** (Smartcat-like): reviewers sign up, pass tests, get paid per decision.
4. **Quality estimation + senate**: independent accuracy, fluency, terminology and consistency judges, with overlap arbitration, decide which segment ships without a human.

Service tiers `auto`, `ai_review`, `hybrid`, `full`; regulated verticals cannot use `auto` or `ai_review`. When no reviewer is available the org's `no_reviewer_policy` (`wait`, `ai_fallback`, `partial`) applies. AI is never silently substituted for a human. Every segment carries append-only provenance and an evidence pack (JSON + PDF).

Status 2026-10-13: built and tested locally (789 backend tests, 30-step browser e2e); not deployed; no measurement on a real pair yet. Next: P00 on the owner's Windows machine (`phases/README.md`).

## Features by module

Sold as seven modules plus add-ons through plans (D-087). A disabled module answers 404.

- **`tms` Web translation**: 25+ formats (docx, xlsx, pptx, html, md, json, po, txt, csv, tsv, xliff, IDML, SRT, VTT, ASS, XML with ITS rules, DITA, Android and iOS strings and stringsdict, ARB, properties, resx, YAML, AsciiDoc) with inline formatting kept as tagged text and per-file handler options; XLIFF 2.1 export; presigned direct uploads up to 1 GB. TM (in-context 101, exact, fuzzy, semantic), TMX import and export; glossaries with mandatory, preferred, forbidden and do-not-translate terms, versioned and frozen per job; segment workbench with live QA, TM diff, concordance, split and merge, find and replace, locks, comments and client queries, live preview; TM editor, alignment, term extraction; LQA scorecards.
- **`engine` Translation engine API**: Anthropic, OpenAI, DeepL, Google, Claude on AWS Bedrock and Google Vertex, any OpenAI-compatible endpoint, mock providers; keys in the database, encrypted, with org BYOK first; routing rules per pair, content type and purpose; monthly budgets per provider; scoreboard routing; own models (per-client fine-tunes with consent, evaluated on the scoreboard). Add-ons: `eu_processing`, `byok`, `custom_models`.
- **`ai` Quality layer**: hard QA (tags, numbers, glossary), MQM-Core QE judge, review and translation senates, AI editor, calibrated thresholds per org, content type and target language, 2 % blind control samples, escaped-error reporting.
- **`pm` Project management**: Agency OS (CRM with deals pipeline, client price lists, executable workflow templates, dashboards), AI setup assistant and PM copilot (proposes, a human applies), own vendors with rates, availability and NDAs, ranked offers with timeout escalation, a no-login vendor workbench, purchase orders, vendor invoices, capacity planner and deadline risk.
- **`auditor` Quality auditor**: standalone QA and LQA of bilingual files on the work queue, MQM score and verdict.
- **`strings` Software strings**: keys, copy-on-write branches, releases, over-the-air bundles, push and pull CLI.
- **`community` Reviewer marketplace**: application, qualification tests, task queue with a keyboard cockpit, second review, per-decision pay, reviewer score, disputes, payouts.
- **Billing and payouts** (every org): plans as data, subscriptions, prepaid credits, period-close overage, Paddle as merchant of record, Stripe adapter (off), manual bank invoices; payout rails Payoneer, PayPal and bank files; platform fee on human work (default 5 %).
- **Platform**: custom roles and team invites, append-only audit log with export, OIDC SSO with PKCE and verified domains, encrypted secrets, queued transactional email, PostHog and OpenTelemetry hooks, worker heartbeat.
- **API**: about 300 endpoints documented, JWT or API keys, idempotent creates, signed webhooks. Contract: [docs/api-contract.md](docs/api-contract.md).

## Layout

```
services/api/            Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Postgres 16 (pgvector, pg_trgm)
  arbiter/contracts.py   seams between modules (change = decision in docs/decisions.md)
  arbiter/domain/        state machines (states.py is the only way to change state)
  arbiter/models/        SQLAlchemy models
  arbiter/fileproc/      FormatHandler per format
  arbiter/linguistic/    TM, glossary, stemming, embeddings, alignment
  arbiter/engines/       MT + LLM providers, BYOK, routing, budgets
  arbiter/training/      own models (datasets, fine-tune providers)
  arbiter/quality/       hard QA, QE judge, senate, editor, calibration
  arbiter/pipeline/      orchestrator, durable queue, worker, evidence
  arbiter/tms/           workbench, comments and queries, TM tools
  arbiter/auditor/       standalone QA and LQA
  arbiter/strings/       software strings, releases, OTA
  arbiter/community/     reviewers, tests, task queue, pay, score, disputes, payouts and rails
  arbiter/billing/       quotes, plans, subscriptions, credits, entitlements, invoices, ledger, providers
  arbiter/agency/        Agency OS: CRM, price lists, workflows, dashboards, assistant, vendors, POs
  arbiter/platform/      modules, roles, team, audit, SSO, secrets
  arbiter/notify/        queued email
  arbiter/api/           HTTP layer (routes/*.py)
  arbiter/cli.py         operator CLI
  migrations/            Alembic (0001 to 0011, one chain)
apps/web/                Next.js 16: customers (/app), reviewers (/reviewer), operators (/admin), vendors; e2e/
deploy/                  Kamal configs (deploy/kamal, primary), Compose + Caddy (local and fallback), backups
docs/                    system design, infrastructure, decisions, subprocessors draft, runbooks, API contract
phases/                  the phase plan (P00..P09) in HYPERPOWER format
memory-bank/             current state for the next session (human or agent)
evidence/                append-only evidence ledger (replayable proof)
.hyperpower/             agent control plane (see HYPERPOWER.md)
```

## Quickstart (local)

Requirements: Python 3.13 (`.python-version`), Node 24 (`.node-version`), Docker (for Postgres only). On Windows use uv for Python and the root npm scripts instead of make: `docs/runbooks/bootstrap-fresh-clone.md`.

```bash
cp .env.example services/api/.env      # dev defaults work as-is, provider keys can stay empty
make install                           # services/api/.venv + web deps
make dev-db                            # Postgres 16 + pgvector on 127.0.0.1:5432 (dbs arbiter, arbiter_test)
make migrate
cd services/api && .venv/bin/python -m arbiter.cli seed-demo && .venv/bin/python -m arbiter.cli seed-plans && cd -
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

Without provider keys everything runs on the mock providers (`mock-mt`, `mock-llm`); the assistant then uses its built-in heuristic planner, billing uses the manual provider, payouts use mocks, email goes to the log. The web app can also run with no backend at all: `cd apps/web && npm run dev:mock`.

Operator CLI (`python -m arbiter.cli ...` in services/api): `seed-demo`, `seed-plans`, `create-admin`, `calibrate`, `run-worker`, `close-billing-period`, `refresh-payouts`.

## Tests and lint

```bash
npm run verify       # the ship check: runtime pins, ruff, pytest, web lint + i18n, typecheck, build (any OS)
npm run verify:e2e   # the 30-step browser flow (J-01..J-09 mapped today, J-10..J-18 from P00) against a running stack
make test            # 789 backend tests against arbiter_test; never calls a real provider
make lint            # ruff check + ruff format --check, eslint + tsc
make fmt
```

CI (`.github/workflows/ci.yml`) runs lint, tests, web build, Docker builds of both images and the compose check. `release.yml` builds, attests and deploys with Kamal once environments are configured (P02); `backup.yml` runs the nightly dump and the monthly restore drill.

## Deploy

Planned stack (D-080 to D-083): Hetzner Cloud VMs behind a Hetzner Load Balancer, Kamal 2 deploys of attested GHCR images, Ubicloud managed Postgres, Hetzner Object Storage, Backblaze B2 EU backups, Cloudflare in front, Tailscale for SSH, PostHog EU and Better Stack. Staging in P02, production in P04. Overview: [docs/infrastructure.md](docs/infrastructure.md). Operations: [deploy/README.md](deploy/README.md). Incidents: [docs/runbook.md](docs/runbook.md).

## More

- [docs/DESIGN.md](docs/DESIGN.md) system design; [docs/infrastructure.md](docs/infrastructure.md) hosting, deploy, backups, scaling, costs
- [docs/decisions.md](docs/decisions.md) architecture decision log (D-001..D-090)
- [docs/subprocessors.md](docs/subprocessors.md) subprocessor list (draft, pending legal review)
- [ROADMAP.md](ROADMAP.md) phases P00-P09 and exit criteria; [phases/](phases/README.md) the working plan
- [PRODUCT.md](PRODUCT.md) what Arbiter is and is not, who pays
- [ACCEPTANCE.md](ACCEPTANCE.md) journeys J-01..J-18 and integration checkpoints INT-01..INT-11
- [SECURITY.md](SECURITY.md) security policy and controls
- [HYPERPOWER.md](HYPERPOWER.md) the agent operating system (control plane, evidence, gates, hooks)
- [memory-bank/progress.md](memory-bank/progress.md) what exists, what is missing, known limitations
- [CLAUDE.md](CLAUDE.md) rules for AI coding agents working in this repo

Proprietary. See [LICENSE](LICENSE).
