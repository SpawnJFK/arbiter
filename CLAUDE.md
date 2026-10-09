# CLAUDE.md

Project law for Arbiter. Read it fully before any command. `AGENTS.md` points here; `.cursor/rules/standing-rules.mdc` is a compressed copy and this file wins on any difference. Then follow the startup order below. Do not rely on chat history; the repo is the source of truth.

## What this is

Arbiter (working name) is an AI-native translation platform sold globally, English-first. It merges a business system (quotes, projects, invoicing, vendor payouts, plus the Agency OS: CRM, price lists, workflow templates, dashboards), a CAT/TMS (file formats, translation memory, termbase, MT, QA) and a reviewer marketplace, and adds a quality-estimation judge with a review senate that decides which segment ships without a human. Customers buy per-word tiers `auto`, `ai_review`, `hybrid`, `full`; every segment carries append-only provenance and an evidence pack.

Read `PRODUCT.md` for the business, `docs/DESIGN.md` for the system design, `ACCEPTANCE.md` for the journeys that must work, `phases/` for the work order, `HYPERPOWER.md` for the agent operating system.

## Startup order (zero chat history)

1. This file, all of it.
2. `hyperpower.json`: branch `main`, runtime pins (Node 24, Python 3.13, Postgres 16), dev ports (api 8000, web 3000), phases, MCP set.
3. `memory-bank/activeContext.md`, then `memory-bank/progress.md`.
4. The current phase file in `phases/` and the journeys and checkpoints it names in `ACCEPTANCE.md`.
5. `npm run hp -- resume`, then `npm run hp -- doctor` (no BROKEN except what the phase file lists as expected).
6. Then work. Read `SECURITY.md` before touching auth, tenancy, money, webhooks, file parsing or secrets, and `.cursor/rules/design.mdc` before UI.

## Standing rules

1. **Autonomy.** You install, run, test, build, migrate, commit, push and deploy yourself. Never hand the owner a terminal command. He only does steps that need his hands: creating accounts, pasting keys, approving DNS, payment setup, a browser login or OAuth click. When you need one of those, give numbered click-by-click steps with exact URLs and what success looks like.
2. **Find it before asking.** If you need to know how something is configured, read `.env.example`, `services/api/.env`, `services/api/arbiter/config.py`, `hyperpower.json`, the migrations or the code. Before asking a human, try in order: repo, local CLI, provider CLI, MCP, API.
3. **Context7 before any library.** Before writing code against FastAPI, SQLAlchemy 2, Alembic, pydantic v2, psycopg 3, pgvector, Next.js 16, React 19, Tailwind 4, Playwright or any provider SDK, resolve it in Context7 at the pinned version and log it in `memory-bank/context7-log.md`. If Context7 is down, read the installed package's docs (`apps/web/node_modules/next/dist/docs/`, the venv's site-packages) and log the fallback. Never write an API from memory. Next.js 16 uses `proxy.ts`, never `middleware.ts`.
4. **Phase discipline.** Work only on the current phase in `phases/`, in order. A phase closes only when `npm run hp -- gate P0x --product` exits 0. Do not start P(n+1) items while P(n) is open unless the owner says so.
5. **Content rule.** Never write the name of any employer of the owner, past or present, or of any specific translation agency, into code, docs, fixtures or commit messages. Competitor products (Phrase, Trados, memoQ, Smartcat, Crowdin, Lokalise, XTM, Plunet, DeepL, ModelFront, Unbabel, Gengo) may be named where relevant. Legal items are written neutrally ("Legal review before public launch"). Never invent customers, revenue or metrics; fixtures stay clearly fictional.
6. **English-first.** Every user-visible web string goes through `t()` with a key in `apps/web/messages/en.json` and `npm run i18n:check` passes. Every user-visible backend string is English (D-045). Other UI locales live in the database (D-046).
7. **No secrets in the repo.** Keys only via `ARBITER_*` env vars; `.env.example` lists every setting with an empty or dev-only value. `.cursor/mcp.json` and env files are gitignored. Never paste a token into a shell command; the guard blocks it.
8. **Proof.** A claim of done is a replayable record in `evidence/ledger.jsonl` (`rigor` skill), reported as VERIFIED, DEFERRED or BROKEN. Run `npm run verify` before every push and `npm run verify:e2e` for UI or flow changes.
9. **Progress output.** Long operations (builds, test runs, migrations, measurements, deploys, e2e) print one newline-terminated status line every 5 % or 30 seconds with N/total, %, elapsed and ETA, inside the Cursor agent terminal. Never open extra console windows. Never start a second process on the same file.
10. **Spend.** When the owner says "apply" for a phase, that is approval for the spend the phase file declares (servers, DNS, deploys, provider usage). Do not stop again to ask. Anything not declared needs a new "apply".
11. **No em dashes** in docs, comments, UI copy or commit messages (test fixtures and the vendored skills in `.cursor/skills/` are exempt). No emoji. The pre-commit hook warns.
12. **Graphify first** for structural questions once P00 has installed it: `graphify query "<concept>" --dfs --budget 1500` before reading directories.

## Code conventions (non-negotiable)

- **contracts.py is the seam.** Modules (linguistic, engines, quality, pipeline) talk only through types in `arbiter/contracts.py`. Change internals freely; changing contracts.py is a decision: add an entry to `docs/decisions.md` and update every caller in the same change.
- **Money is `Decimal`.** Never float, anywhere: prices, costs, reviewer pay, ledger, invoices. Serialize as decimal strings (`"12.40"`). Currency travels with the amount.
- **Never call real providers in tests.** `tests/conftest.py` forces `ARBITER_ENV=test` and blanks all keys. Use the mock providers. A test that needs network is a bug.
- **Tagged text model.** Inline formatting is carried as `⟦1⟧...⟦/1⟧` (paired), `⟦2/⟧` (standalone); literal brackets are escaped `⟦⟦` `⟧⟧`. Engines, TM and QA see tagged text; only fileproc converts to and from native formats. Tag severity policy is D-009.
- **States change only through `arbiter/domain/states.py`.** No direct `obj.state = ...` outside it. A transition not listed there does not exist; `IllegalTransition` is a caller bug.
- **Provenance is append-only.** Every segment change (engine output, QE score, senate verdict, human edit, approval, delivery) writes a `provenance_events` row. A DB trigger rejects UPDATE/DELETE. Never work around it; corrections are new events.
- **Rule ids in docstrings.** Behaviour that implements a product rule names it: `R-SEG-*` (segmentation), `R-GL-*` (glossary), `R-TM-*` (translation memory), `R-MT-*` (engine routing), `R-IN-*` (ingest). Tests for a rule mention the same id. Do not renumber existing ids.
- **No silent AI substitution.** If a tier requires a human and none is available, apply the org `no_reviewer_policy` (`wait`, `ai_fallback`, `partial`) and record it in provenance and the evidence pack.
- **Regulated verticals** never get `auto` or `ai_review`. Enforce in quote and project creation, not only in the UI.
- **Glossary versions are frozen per job.** Terms are temporal (`valid_from`, `valid_to`); a job reads the version captured at creation.
- **Queue work goes through `work_items`** with an idempotency key, in the same transaction as the state change that caused it.
- **Tenancy.** Every query on customer data is scoped by `org_id`. Another org gets 404, not 403. Reviewers see only the task they hold.
- Python: ruff (line 110), type hints everywhere, `from __future__ import annotations`. Web: TypeScript strict, server components by default.

## Architecture map

```
services/api/arbiter/
  config.py          Settings, env prefix ARBITER_ (every field = ARBITER_<FIELD>)
  contracts.py       THE seam between modules: dataclasses + Protocols (TermHit, TermViolation, ...)
  errors.py          ServiceError family (NotFound 404, Forbidden 403, Conflict 409, Invalid 422)
  domain/states.py   state machines (Segment, Job, Task, Payout); only legal path to change state
  models/            SQLAlchemy 2 models: tenancy, content, assets, quality, reviewers, money,
                     integrations (work_items queue, webhooks, idempotency), provenance, agency, i18n
  dbinit.py          extensions + tables + append-only trigger; metadata_0001 for migration 0001 (D-037)
  fileproc/          FormatHandler per format, registry, segmenter; tagged text ⟦n⟧ model in base.py
  linguistic/        tm.py, glossary.py (org-wide versions D-016), lemma.py (Snowball), embeddings.py
  engines/           anthropic, openai, deepl, google (Basic v2), mock, llm_mt, tags, pricing, registry
  quality/           checks (hard QA), qe (decide), judge, senate, editor, mqm, calibration, prompts
  pipeline/          orchestrator (steps), queue (work_items), worker, events, evidence, hooks
  community/         profiles, testing, queue, review, pay, scoring, disputes, payouts
  billing/           quotes, pricing, usage, invoices, ledger
  agency/            Agency OS: crm, pricelists, workflows, dashboards, assistant (+ heuristic), schemas
  api/               app.py (arbiter.api.app:app, /healthz), deps.py (auth, roles, paging), security.py
  api/routes/        auth, files, quotes, projects (+ idempotency helpers), jobs, assets, quality,
                     integrations, reviewers, admin, crm, pricelists, workflows, dashboards, assistant, i18n
  cli.py             seed-demo, create-admin, calibrate, run-worker
  storage.py, webhooks.py
services/api/migrations/versions/   0001_initial, 0002_agency_os, 0003_ui_i18n (hand-written)
services/api/tests/  pytest, mock providers only; tests/db checks alembic head == create_all
apps/web/            Next.js 16 App Router: /app (customers), /reviewer, /admin; src/lib (api client, types,
                     i18n), src/app/api/proxy (server proxy, token in httpOnly cookie, D-036), src/proxy.ts
apps/web/messages/   en.json, the English UI catalog (source of every UI string)
apps/web/e2e/        real-flow.mjs: browser test of J-01..J-09 against a real API + worker + web
deploy/              compose, Caddy, backup.sh, Hetzner guide
phases/              the frozen phase plan (HYPERPOWER format), README has the order table
evidence/            ledger.jsonl (append-only proof) and schema.json
scripts/             ship check, e2e and deploy verifiers, sql verifier, git and Cursor hook scripts
.hyperpower/         control plane (core is hash-locked and project-agnostic), see HYPERPOWER.md
.cursor/             rules, commands, agents, skills, hooks.json, mcp.json.example
.githooks/           pre-commit, pre-push (tracked; soft, always exit 0)
.beads/              Beads config and the tracked issues.jsonl export
```

System design: `docs/DESIGN.md`. Decisions: `docs/decisions.md`. API: `docs/api-contract.md`. Product: `PRODUCT.md`. Acceptance: `ACCEPTANCE.md`. Machine contract: `hyperpower.json`.

## Commands

The npm scripts at the root work the same on Windows and Linux; the Makefile is the Linux and macOS shortcut for the same steps.

| Task | Command |
|---|---|
| Ship check (runtime pins, ruff, pytest, web lint + i18n, typecheck, build) | `npm run verify` (parts: `npm run verify:api`, `npm run verify:web`) |
| Browser e2e, J-01..J-09 (needs API, worker, web running) | `npm run verify:e2e` |
| Deployed commit equals HEAD (from P02) | `npm run verify:deployed` |
| HYPERPOWER | `npm run hp -- doctor`, `status`, `verify`, `resume`, `handoff`, `end`, `gate P0x --product` |
| Local Postgres | `docker compose -f deploy/docker-compose.dev.yml up -d --wait` (`make dev-db`) |
| Migrate | `alembic upgrade head` with the venv Python in services/api (`make migrate`) |
| API / worker / web | `make api`, `make worker`, `make web` (or the commands they wrap, see Makefile) |
| Lint / format | `make lint`, `make fmt` |
| New migration | `alembic revision -m "..."` in services/api (hand-written, reviewed) |
| Compose check | `docker compose -f deploy/docker-compose.yml config -q` (needs env vars, see deploy/README.md) |

Run `npm run verify` before declaring any task done. CI runs the same steps plus Docker builds and compose validation.

## Decisions

Any choice another engineer could reasonably have made differently goes into `docs/decisions.md` as a new `D-0NN` entry: context, decision, rejected alternatives, consequences. Never rewrite an old entry; supersede it with a new one.

## Session close (every session, in this order)

1. Run `/end` (`.cursor/commands/end.md`, identical to `.claude/commands/end.md`).
2. `npm run verify` green (and `npm run verify:e2e` if UI or flows changed), or the failure written down in `memory-bank/progress.md` with the reason.
3. Update `memory-bank/activeContext.md` (what you did, what is half-done, next step) and `memory-bank/progress.md` (what now exists, what is next) so an agent with zero chat history can continue.
4. Add a `docs/decisions.md` entry for every real architectural decision, including the rejected alternative.
5. If `docs/api-contract.md` or `contracts.py` changed, say so explicitly in activeContext.md, and check the web app still matches.
6. State the phase position (e.g. "P01, item 4 of 8") in activeContext.md and tick items in the phase file in `phases/`.
7. Beads export (`bd export -o .beads/issues.jsonl`), `npm run hp -- handoff`, then `npm run hp -- end`.
8. Leave a clean working tree in sync with `origin/main`. Commit only when the owner asked for commits.
