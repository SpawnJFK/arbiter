# /plan

Show the phase plan with position. Source: `phases/README.md`, `hyperpower.json` `phases`, `.hyperpower/state/phase-sync.json`, `memory-bank/progress.md`. Do not reconstruct it from memory.

```
P00 install and verify on Windows
P01 measurement harness (real providers, EN to SR reference set, threshold sweep)
P02 staging deploy on Hetzner (compose, Caddy, backups, restore drill, verify:deployed)
P03 money and legal readiness (payment provider, payout provider, reconciliation, legal and tax review)
P04 self-serve launch (3 calibrated languages, monitoring, production)
P05 integrations (GitHub, Figma, headless CMS)
P06 more formats via Okapi
P07 enterprise (SSO, provisioning, SOC 2, pen test)
P08 white-label for agencies
```

For each phase print: status from `phase-sync.json` (`VERIFIED_SYNCHRONIZED` means closed), bead id from `hyperpower.json`, journeys and checkpoints, and for the current phase the item position and the next human step if any.

End with: current phase, next action, next gate command.
