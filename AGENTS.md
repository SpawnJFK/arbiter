# AGENTS.md

All instructions for AI coding agents live in [CLAUDE.md](CLAUDE.md). Read it fully before changing anything.
Short version: contracts.py is the seam, states.py owns state changes, provenance is append-only, tests never call real providers.
At session end, run the close checklist in CLAUDE.md and update memory-bank/.
