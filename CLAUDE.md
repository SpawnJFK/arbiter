# CLAUDE.md: rules for AI coding agents in this repo

Read this whole file before writing code. Then read `memory-bank/activeContext.md` and `memory-bank/progress.md` to learn where the build is. Do not rely on chat history; the repo is the source of truth.

## Standing rules

1. **Autonomy.** You install, run, test, build and fix everything yourself. Never hand the owner a command to run. The owner only does human-only steps (accounts, API keys, DNS, payment setup, browser logins). When you need to know how something is configured, read the config, env template or code yourself instead of asking.
2. **Context7 before any library.** Before using or changing code that calls FastAPI, SQLAlchemy 2, Alembic, pydantic v2, pgvector, Next.js 16, React 19, Tailwind 4, or any provider SDK, look the API up with the Context7 MCP. Agents hallucinate library APIs; versions here are recent.
3. **Phase order.** Work on the current phase in `docs/phases/` in order. Do not start P(n+1) items while P(n) exit criteria are open unless the owner says so.
4. **Content rule.** Never write the name of any employer of the owner, past or present, or of any specific translation agency, into code, docs, fixtures or commit messages. Competitor products (Phrase, Trados, memoQ, Smartcat, Crowdin, Lokalise, XTM, Plunet, DeepL, ModelFront, Unbabel, Gengo) may be named where relevant. Legal items are written neutrally ("Legal review before public launch"). Never invent customers, revenue or metrics.
5. **No secrets in the repo.** Keys only via `ARBITER_*` env vars. `.env.example` lists every setting with an empty or dev-only value.

## Architecture map

```
services/api/arbiter/
  config.py          Settings, env prefix ARBITER_ (every field = ARBITER_<FIELD>)
  contracts.py       THE seam between modules: dataclasses + Protocols (TermHit, TermViolation, ...)
  errors.py          ServiceError family (NotFound 404, Forbidden 403, Conflict 409, Invalid 422)
  domain/states.py   state machines (Segment, Job, Task, Payout); only legal path to change state
  models/            SQLAlchemy 2 models: tenancy, content, assets, quality, reviewers, money,
                     integrations (work_items queue, webhooks, idempotency), provenance, agency
  dbinit.py          extensions + tables + append-only trigger; metadata_0001 for migration 0001 (D-037)
  fileproc/          FormatHandler per format, registry, segmenter; tagged text ⟦n⟧ model in base.py
  linguistic/        tm.py, glossary.py (org-wide versions D-016), lemma.py (Snowball), embeddings.py
  engines/           anthropic, openai, deepl, google (Basic v2), mock, llm_mt, tags, pricing, registry
  quality/           checks (hard QA), qe (decide), judge, senate, editor, mqm, calibration, prompts
  pipeline/          orchestrator (steps), queue (work_items), worker, events, evidence, hooks
  community/         profiles, testing, queue, review, pay, scoring, disputes, payouts
  billing/           quotes, pricing, usage, invoices, ledger
  agency/            Agency OS: crm, pricelists, workflows, dashboards, assistant (+ heuristic), schemas
  api/               app.py (arbiter.api.app:app), deps.py (auth, roles, paging), security.py
  api/routes/        auth, files, quotes, projects (+ idempotency helpers), jobs, assets, quality,
                     integrations, reviewers, admin, crm, pricelists, workflows, dashboards, assistant
  cli.py             seed-demo, create-admin, calibrate, run-worker
  storage.py, webhooks.py
services/api/migrations/versions/   0001_initial, 0002_agency_os (hand-written)
apps/web/            Next.js 16 App Router: /app (customers), /reviewer, /admin; src/lib (api client,
                     types), src/app/api/proxy (server proxy, token in httpOnly cookie, D-036), proxy.ts
apps/web/e2e/        real-flow.mjs (npm run e2e, browser test against a real API + worker)
deploy/              compose, Caddy, backup.sh, Hetzner guide
```

System design: `docs/DESIGN.md`. Decisions: `docs/decisions.md`. API: `docs/api-contract.md`.

## Commands

| Task | Command |
|---|---|
| Local Postgres | `make dev-db` |
| Migrate | `make migrate` |
| API / worker / web | `make api`, `make worker`, `make web` |
| Tests | `make test` (needs `make dev-db`) |
| Lint / format | `make lint`, `make fmt` |
| New migration | `cd services/api && .venv/bin/alembic revision -m "..."` (hand-written, reviewed) |
| Compose check | `docker compose -f deploy/docker-compose.yml config -q` (needs env vars, see deploy/README.md) |

Run `make lint` and `make test` before declaring any task done. CI runs the same plus Docker builds.

## Conventions (non-negotiable)

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
- **Tenancy.** Every query on customer data is scoped by `org_id`. Reviewers see only the task they hold.
- Python: ruff (line 110), type hints everywhere, `from __future__ import annotations`. Web: TypeScript strict, server components by default.

## Decisions

Any choice another engineer could reasonably have made differently goes into `docs/decisions.md` as a new `D-0NN` entry: context, decision, rejected alternatives, consequences. Never rewrite an old entry; supersede it with a new one.

## Session close checklist

Do all of these before ending a session:

1. Run the repo's `/end` command (`.claude/commands/end.md`) if it exists.
2. `make lint` and `make test` green (or the failure is written down in progress.md with the reason).
3. Update `memory-bank/activeContext.md` (what you were doing, what is half-done, next step) and `memory-bank/progress.md` (what now exists, what is next) so an agent with zero chat history can continue.
4. Add a `docs/decisions.md` entry for every real architectural decision, including the rejected alternative.
5. If `docs/api-contract.md` or `contracts.py` changed, say so explicitly in activeContext.md, and check the web app still matches.
6. State the phase position (e.g. "P0, item 4 of 9") in activeContext.md and tick items in `docs/phases/`.
7. Leave a clean working tree. Commit only when the owner asked for commits.
