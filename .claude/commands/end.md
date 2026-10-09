# /end: session close

Run every step, in order, and report each as VERIFIED / DEFERRED / BROKEN.

1. `make lint` and `make test` (Postgres must be running: `make dev-db`). If UI or flows changed: start API + worker + web and run `cd apps/web && npm run e2e`. A failure that cannot be fixed now goes into memory-bank/progress.md with the reason.
2. Update `memory-bank/activeContext.md`: what you did this session, what is half-done, the exact next step, and the phase position (e.g. "P0, measurement 2 of 5").
3. Update `memory-bank/progress.md`: what now exists, test counts, what is next.
4. Add a `docs/decisions.md` entry (next D-0NN) for every real architectural decision, with the rejected alternative. Never rewrite an old entry.
5. If `docs/api-contract.md` or `services/api/arbiter/contracts.py` changed, say so in activeContext.md and confirm the web app still matches.
6. Tick finished items in `docs/phases/phase-N.md`.
7. Commit with a clear message (no employer or agency names), push to origin/main, and confirm `git status` is clean and `git rev-parse HEAD` equals `git rev-parse origin/main`.
8. Wait for the GitHub Actions run on that commit (`gh run watch` or `gh run list --limit 1`) and report its result.
