# /end

Session close. Implements "Session close" in `CLAUDE.md`. Do every step, in order, even if the session was short, and report each as VERIFIED / DEFERRED / BROKEN. `.claude/commands/end.md` is the same file for Claude Code; keep them identical.

## 1. Prove what you claim

- `npm run verify` if any code, migration or config changed this session (Postgres must be running). If UI or flows changed: start API, worker and web and run `npm run verify:e2e`. A failure that cannot be fixed now goes into BROKEN below and into `memory-bank/progress.md` with the reason; do not hide it.
- `npm run hp -- verify` for ledger records touched this session.
- Every claim of done in this session has a ledger id, or it is reported as DEFERRED.

## 2. Write state for an agent with zero chat history

- `memory-bank/activeContext.md`: date, phase position ("P0x, item n of m"), what changed this session, what is verified (with evidence ids), what is half-done, the exact next action, the next gate, open items carried forward. If `docs/api-contract.md` or `services/api/arbiter/contracts.py` changed, say so explicitly and confirm the web app still matches.
- `memory-bank/progress.md`: what now exists, test counts, what is next; tick only items with a VERIFIED evidence id, and write the id next to the tick.
- `docs/decisions.md`: one new `D-0NN` entry for every real decision made this session (architecture, data, tooling, scope, business), each with the rejected alternative. Append only; never rewrite an old entry.
- `memory-bank/context7-log.md`: every library looked up this session.
- `ACCEPTANCE.md`: journey and checkpoint Status lines updated with evidence ids.
- The current phase file in `phases/`: tick finished items.

## 3. Sync the work graph

- Beads: update or close the beads you worked on (`bd update`; phase beads close only through the gate), then `bd export -o .beads/issues.jsonl`.
- `npm run hp -- handoff`, then `npm run hp -- end` (writes `.hyperpower/state/session.json` and a checkpoint).

## 4. Hygiene

- No secret in the diff: `git diff --cached` contains no keys, tokens or `.env` content; run Betterleaks if installed (`.hyperpower/tools/bin/`).
- No employer or translation-agency names, no invented customers or metrics, no em dashes in docs or copy.

## 5. Commit and push (only when the owner asked for commits)

- Commit per logical unit with plain messages. Push to `main` with a normal `git push` and read the hook output: any `skipped` line from a guard is reported as BROKEN.
- Confirm `git status` is clean and `git rev-parse HEAD` equals `git rev-parse origin/main`.
- Wait for the GitHub Actions run on that commit (`gh run watch` or `gh run list --limit 1`) and report its result.

## 6. Report to the owner

```
Session closed, <date>
Phase: P0x, item n of m
VERIFIED: <items, evidence ids>
DEFERRED: <items, which phase>
BROKEN:   <items, command, first error line>
Next action: <one sentence>
Human step waiting: <none | the step, with click path>
Tree: <clean, in sync with origin/main at <short sha> | uncommitted, owner commits>
CI: <result>
```
