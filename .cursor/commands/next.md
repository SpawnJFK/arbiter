# /next

Advance the current phase by one scope item.

1. Find the phase and item in `memory-bank/activeContext.md`. Re-read that item in `phases/`.
2. If it touches code: `graphify query "<concept>" --dfs --budget 1500` first (from P00 on), then Context7 for every library you will call, logged in `memory-bank/context7-log.md`.
3. Do the work. Respect the conventions in `CLAUDE.md` (contracts.py seam, Decimal money, states.py, append-only provenance, org_id scoping, rule ids). Long operations print a status line every 5 % or 30 seconds.
4. Prove it: the narrowest check that fails when the item is not done. Turn it into a ledger record (`rigor` skill) when the item maps to a journey or INT checkpoint.
5. Run `npm run verify` before any push (and `npm run verify:e2e` for UI or flow changes). Push to `main`. No `--no-verify`.
6. Update `memory-bank/progress.md` (tick with evidence id), `activeContext.md` (new position, next action) and the phase file checkbox.
7. Spend, DNS, deploys and cloud resources: only what the phase file declares, and only after the owner said "apply" for this phase.
8. UI changes: `design-reviewer` subagent. Auth, tenancy, money, webhooks, files, env, deploy: `security-reviewer` subagent.
9. When every scope item is done: hand the phase to the `gate-reviewer` subagent, then `npm run hp -- gate P0x --product`. Do not start the next phase until the gate exits 0.
