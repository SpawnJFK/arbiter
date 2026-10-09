# /status: where is the build

Without changing anything, report:
1. Phase position from memory-bank/activeContext.md and the open checklist items in the current docs/phases/phase-N.md.
2. `git log --oneline -10`, `git status -sb`, and whether HEAD equals origin/main.
3. Latest GitHub Actions run result (`gh run list --limit 3`).
4. Alembic head (`cd services/api && .venv/bin/alembic heads`) and the newest D-0NN in docs/decisions.md.
5. Open items listed in activeContext.md, in order.
