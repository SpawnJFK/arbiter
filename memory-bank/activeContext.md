# Active context

Last updated: 2026-10-07. Phase: **P0 Measurement harness**, foundation stage (see docs/phases/phase-0.md).

## What is happening now
Several agents are building in parallel:
- `arbiter/linguistic` (TM, glossary, lemma/Snowball, embeddings): in progress
- `arbiter/engines` (mock, Anthropic, OpenAI, DeepL, Google, LLM MT, tag protection, pricing, registry): in progress
- `arbiter/quality` (hard QA, QE judge, senate): started (prompts)
- `apps/web` (Next.js 16): scaffold only
- Infra and docs: done in this session (Dockerfiles, compose, Caddy, backup, CI, Makefile, .env.example, README, CLAUDE.md, DESIGN, decisions D-001..D-015, ROADMAP, phases, runbook, SECURITY, LICENSE)

Not started: `arbiter/api` (FastAPI app, `arbiter.api.app:app`), `arbiter/pipeline` (worker, `python -m arbiter.pipeline.worker`), `arbiter/community`, `arbiter/billing`.
The API image healthcheck and the compose worker depend on these two entry points existing.

## Open issues to resolve
1. **State names differ** between `docs/api-contract.md` and `arbiter/domain/states.py`:
   - Jobs, contract: draft, queued, preparing, translating, scoring, review, merging, delivered, failed, cancelled, disputed. states.py: draft, quoted, cancelled, running, review, ready, merging, failed, delivered, settled, disputed.
   - Segments, contract adds: scored, ai_reviewed, approved, blocked. states.py has: pending, translated, auto_approved, needs_review, in_review, reviewed, delivered.
   Pick one set (states.py is the authority per CLAUDE.md), update the other, record a decision.
2. `apps/web/next.config.ts` lacks `output: "standalone"`. The web Dockerfile (`deploy/web.Dockerfile`) works either way but standalone gives a much smaller image. Add it when the web workstream is free.
3. `apps/web` has no `package-lock.json`. CI and Docker fall back to `npm install`; commit a lockfile for reproducible builds.
4. Docker images were not built in this environment (no daemon). First CI run is the first real build.

## Next steps
1. API app skeleton with `/healthz` and auth, following docs/api-contract.md.
2. Pipeline worker on `work_items` (claim, lease, retry, dead).
3. Quality: hard QA with D-009 tag policy, QE judge, senate, decide step.
4. P0 reference set for EN to SR and the measurement harness script.
