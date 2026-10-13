# P05: Integrations and connectors

## Goal

Content flows in and out without manual upload: GitHub, Figma, at least one headless CMS and Slack notifications, all built on the public API (`/v1`), webhooks and the strings module only.

## Already built (not re-done here)

Public API with API keys and idempotency, signed webhooks (D-032), the strings module with keys, branches, releases, OTA bundles and a push/pull CLI (D-060 to D-062), encrypted per-org secrets (`platform/secrets.py`), module gating (D-052).

## Scope

1. **Connector framework** on the public API and signed webhooks only, no private endpoints; per-connector credentials stored encrypted per org with the platform secrets helper; connectors are gated by the module they feed (`strings` or `tms`). Decision entry for where connectors live (inside the API process or a separate worker role).
2. **GitHub connector**: a GitHub App; watch paths in a repo, create strings or file jobs from changed files, open a pull request with the translations; webhook signature checked.
3. **Figma connector**: text layers out, translations back into a copy of the frame.
4. **Headless CMS connector**: at least one, chosen by the owner from demand (decision entry).
5. **Slack**: job and exception notifications to a channel per org (incoming webhook or Slack app; decision entry).
6. **Tests**: recorded fixtures in CI (no network in tests); one live sandbox replay per connector as the ledger verifier; new journeys J-19 onward, numbered at phase start.
7. **Customer docs** per connector (English, in the web app's docs area).
8. Subprocessor list and trust page updated if a connector adds a processor.

## Human-only steps

Created by the owner with exact click paths the agent gives at phase start (after checking which parts the providers' CLIs or APIs can do): the GitHub App registration on https://github.com/settings/apps/new, a Figma developer app on https://www.figma.com/developers/apps, the chosen CMS sandbox account, a Slack app on https://api.slack.com/apps and its installation into a test workspace.

## Declared spend

None (sandbox and developer tiers). Anything paid is declared before use.

## Acceptance

Each connector journey PROVEN with a replayable record on staging; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P05 --product` exits 0 and the P05 bead reads back closed.

## Out of scope

Own models (P06). SAML and SCIM (P07). Okapi formats (ROADMAP backlog).
