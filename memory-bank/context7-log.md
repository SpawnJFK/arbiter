# Context7 log

Append-only. One line per library lookup before code was written against it.

Format: `date | library | version or Context7 id | source (context7 or fallback) | what was confirmed`

A gate fails if a library touched in the phase has no line here with a version.

---

2026-10-09 | all libraries used by the build up to commit 32e8cd0 (FastAPI, SQLAlchemy 2, Alembic, pydantic v2, psycopg 3, pgvector, Next.js 16.4, React 19.3, Tailwind 4, Playwright) | versions in services/api/pyproject.toml and apps/web/package-lock.json | fallback | The cloud build sessions had no Context7 (open item 5 in activeContext.md). APIs were written against installed package sources and `apps/web/node_modules/next/dist/docs/`. P00 item 16 re-checks the conventions the code relies on in Context7 and logs each one here.
2026-10-09 | Node.js built-ins (child_process spawn, fetch, AbortSignal.timeout) for the root scripts in scripts/ | Node 24.21 | fallback | No Context7 in the install session; behaviour confirmed by running every script under Node 24.21 (verify, verify:e2e, sql verifier, git hooks). spawn of npm.cmd on Windows uses shell: true because Node refuses .cmd without a shell; unproven on Windows until P00.
2026-10-13 | cryptography (Fernet, MultiFernet, HKDF), pyjwt (PyJWK, get_unverified_header, decode with audience/issuer/require, RSAAlgorithm.to_jwk), httpx (MockTransport, BasicAuth), FastAPI router-level dependencies, Starlette pure ASGI middleware | cryptography 50.0.2, pyjwt 2.15.1, httpx 0.28, FastAPI as installed | fallback | Platform module build (modules, roles, audit, OIDC SSO) ran in a parallel worktree without Context7. Signatures were read from the installed packages with inspect.signature and confirmed by the tests in services/api/tests/platform (fake IdP with local RSA keys).
