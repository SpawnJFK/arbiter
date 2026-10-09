# Acceptance

A phase or launch gate passes only when its journeys run green against a real API + worker + web (not mock mode), and its INT checkpoints are proven with evidence a reviewer can replay.

## End-to-end journeys (automated: `cd apps/web && npm run e2e`)
| ID | Journey | Status |
|---|---|---|
| J-01 | Company registers, uploads .md and .docx, gets a 4-tier quote | automated, green |
| J-02 | Auto tier job runs MT, QE, senate and is delivered; file and evidence PDF download | automated, green |
| J-03 | Full tier job waits for humans; reviewer clears the cockpit queue (accept, edit); job delivered | automated, green |
| J-04 | Glossary forbidden term blocks a segment; it appears in Exceptions | automated, green |
| J-05 | Reviewer applicant applies, takes a qualification test | automated, green |
| J-06 | Admin sees reviewers and payouts | automated, green |
| J-07 | AI assistant turns an agency description into a plan; apply creates accounts, workflows, price list, dashboard | automated, green |
| J-08 | Account workflow with second review and client approval: two reviewers, client approves, delivered | automated, green |
| J-09 | Admin adds a language via XLIFF export/import, enables it, UI switches locale with English fallback | automated, green |

## Integration checkpoints (need the owner's keys or accounts; all open)
| ID | Checkpoint | Evidence required |
|---|---|---|
| INT-01 | Anthropic judge + senate on real segments | a measurement run log with model version and cost |
| INT-02 | DeepL and/or Google MT on real segments | same, per engine |
| INT-03 | P0 measurement: threshold sweep on a human-labelled EN to SR set | report with escaped-error rate per threshold (docs/phases/phase-0.md) |
| INT-04 | Vertical slice on Hetzner: compose deploy, TLS, migrations, J-01..J-03 run against the live URL | CI build provenance + e2e log against the public URL |
| INT-05 | Backups: nightly pg_dump to object storage and one restore drill | restore log |
| INT-06 | Real payout provider (e.g. Wise) sends one test payout | provider reference |
