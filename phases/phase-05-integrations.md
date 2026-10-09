# P05: Integrations

## Goal

Content flows in and out without manual upload: a GitHub connector, a Figma connector and at least one headless CMS connector, all built on the public API and webhooks only.

## Scope

1. Connector framework on the public API (`/v1`) and signed webhooks only, no private endpoints; per-connector credentials stored encrypted per org.
2. GitHub connector: watch paths in a repo, create jobs from changed files, open a pull request with the translations.
3. Figma connector: text layers out, translations back into a copy of the frame.
4. At least one headless CMS connector (owner picks from demand; decision entry).
5. One end-to-end test per connector against a sandbox account, as a new journey each (J-12 onward), recorded fixtures in CI and a live sandbox replay as the ledger verifier.
6. Customer docs per connector (English, in the web app's docs area or `docs/`).

## Human-only steps

Create the GitHub App, the Figma app and the CMS sandbox accounts; the agent gives exact click paths at phase start and does everything the providers' CLIs or APIs allow.

## Declared spend

None (sandbox and developer tiers). Anything paid is declared before use.

## Acceptance

Each connector journey PROVEN with a replayable record; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P05 --product` exits 0 and the P05 bead reads back closed.

## Out of scope

New file formats (P06). SSO (P07).
