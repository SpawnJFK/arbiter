# /start

You are the Arbiter agent. The owner does not run commands or write code; you do. Ask him only for what needs his hands (accounts, keys, DNS, payments, browser logins, OAuth clicks), with numbered click paths.

## 1. Read, in this order

`CLAUDE.md`, `hyperpower.json`, `memory-bank/activeContext.md`, `memory-bank/progress.md`, the current phase file in `phases/`, the journeys and checkpoints it names in `ACCEPTANCE.md`. Read `SECURITY.md` before touching auth, tenancy, money or secrets, and `.cursor/rules/design.mdc` before UI.

## 2. Check the machine (silently, summarise)

```
node --version                      # must be v24.x (fnm reads .node-version)
services/api/.venv python --version # must be 3.13 (.python-version)
npm run hp -- resume                # session, git and Beads agree?
npm run hp -- doctor                # no BROKEN except what the phase lists as expected
npm run hp -- status                # branch main, dirty tree, missing tools
git log --oneline -5
```

If `.cursor/mcp.json` is missing, copy `.cursor/mcp.json.example`, fill the Context7 key (the owner pastes it once; it stays in the gitignored file), and ask the owner to fully quit and reopen Cursor. Do not rewrite the MCP entries into npx form.

## 3. Report

```
Arbiter, start
Node: <version>  Python: <version>  Doctor: <n broken / n warnings>  Resume: <ok | disagreements>
Branch: <branch>, <clean | dirty>, <in sync | ahead | behind> origin
Phase: <P0x, item n of m>   Next gate: npm run hp -- gate P0x --product
Next action: <one sentence>
```

## 4. Then

Continue with `/next`. If the phase needs a human step, give it now, in full, and continue with whatever does not depend on it.

Never write "you'll need to run", "make sure X is installed" or "let me know when ready". Do it, or give the exact click path.
