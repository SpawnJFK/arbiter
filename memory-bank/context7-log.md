# Context7 log

Append-only. One line per library lookup before code was written against it.

Format: `date | library | version or Context7 id | source (context7 or fallback) | what was confirmed`

A gate fails if a library touched in the phase has no line here with a version.

---

2026-10-09 | all libraries used by the build up to commit 32e8cd0 (FastAPI, SQLAlchemy 2, Alembic, pydantic v2, psycopg 3, pgvector, Next.js 16.4, React 19.3, Tailwind 4, Playwright) | versions in services/api/pyproject.toml and apps/web/package-lock.json | fallback | The cloud build sessions had no Context7 (open item 5 in activeContext.md). APIs were written against installed package sources and `apps/web/node_modules/next/dist/docs/`. P00 item 16 re-checks the conventions the code relies on in Context7 and logs each one here.
2026-10-09 | Node.js built-ins (child_process spawn, fetch, AbortSignal.timeout) for the root scripts in scripts/ | Node 24.21 | fallback | No Context7 in the install session; behaviour confirmed by running every script under Node 24.21 (verify, verify:e2e, sql verifier, git hooks). spawn of npm.cmd on Windows uses shell: true because Node refuses .cmd without a shell; unproven on Windows until P00.
2026-10-13 | Paddle Billing API v1 (customers, transactions, portal-sessions, subscriptions cancel/charge, transaction invoice, webhook signature) | API v1 | fallback | No Context7 in the parallel build session. Signature format (ts:body HMAC-SHA256, several h1 on rotation), one-time charge body (effective_from, non-catalog price: name 1-50, description 2-200, integer quantity, lowest-denomination amount strings) and portal URL path data.urls.general.overview confirmed on developer.paddle.com; the rest from the API reference as known. All calls mocked with httpx.MockTransport; re-check in Context7 before P03 live keys.
2026-10-13 | Stripe API (checkout sessions, billing portal, invoice items, billing meter events, webhook signature) | API 2025+ | fallback | No Context7; written from the API reference as known, adapter disabled unless configured, mocked in tests. Re-check before enabling the Stripe rail.
2026-10-13 | Payoneer Mass Payouts v4 and PayPal Payouts v1 | v4 / v1 | fallback | No Context7; endpoints written in the documented style and fully mocked. Verify against the program's API reference with sandbox credentials in P03 before the first payout.
2026-10-13 | Paddle.js v2 (Environment.set, Initialize with token and checkout.settings.successUrl, auto-open on ?_ptxn) | v2 | fallback | No Context7; used on /checkout/paddle only. Verify in P03 with a sandbox client token.
