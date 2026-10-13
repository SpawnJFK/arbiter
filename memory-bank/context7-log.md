# Context7 log

Append-only. One line per library lookup before code was written against it.

Format: `date | library | version or Context7 id | source (context7 or fallback) | what was confirmed`

A gate fails if a library touched in the phase has no line here with a version.

---

2026-10-09 | all libraries used by the build up to commit 32e8cd0 (FastAPI, SQLAlchemy 2, Alembic, pydantic v2, psycopg 3, pgvector, Next.js 16.4, React 19.3, Tailwind 4, Playwright) | versions in services/api/pyproject.toml and apps/web/package-lock.json | fallback | The cloud build sessions had no Context7 (open item 5 in activeContext.md). APIs were written against installed package sources and `apps/web/node_modules/next/dist/docs/`. P00 item 16 re-checks the conventions the code relies on in Context7 and logs each one here.
2026-10-09 | Node.js built-ins (child_process spawn, fetch, AbortSignal.timeout) for the root scripts in scripts/ | Node 24.21 | fallback | No Context7 in the install session; behaviour confirmed by running every script under Node 24.21 (verify, verify:e2e, sql verifier, git hooks). spawn of npm.cmd on Windows uses shell: true because Node refuses .cmd without a shell; unproven on Windows until P00.
2026-10-13 | PyJWT (encode/decode with audience), SQLAlchemy 2 (postgresql insert on_conflict_do_nothing, with_for_update), FastAPI (APIRouter dependencies, File/Form), reportlab (platypus), Next.js 16 route handlers and server components | pyjwt 2.15.1, sqlalchemy 2.1.4, fastapi 0.143.0, reportlab 5.0.1, next 16.4.0 | fallback | No Context7 in the parallel cloud build session. Signatures read from the installed packages in services/api/.venv and the existing patterns in the repo (routes/proxy, jobs evidence PDF, queue insert); behaviour proven by the vendor test suite and a local smoke run.
