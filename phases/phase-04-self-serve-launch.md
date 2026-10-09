# P04: Self-serve launch

## Goal

A paying customer can sign up on the production domain, upload, get a quote, pick a tier, pay and download the result without the operator, in at least 3 calibrated target languages, with human review capacity that does not limit the tiers sold and with monitoring that tells the owner when something breaks.

## Scope

1. **Calibrate 3 target languages** with the P01 method (reference set, human MQM labels, sweep, thresholds, report in `docs/measurements/`). Target languages chosen by the owner from demand; decision entry per language.
2. **Reviewer capacity.** Recruit and qualify reviewers for each launch pair through the existing apply and test flow; wait-time monitoring per pair against the `hybrid` target, with an alert. New pairs are sold only when the target holds.
3. **Production environment.** Production hosts on the owner's production domain (a second server or a promotion of staging; decision entry), backups and restore drill repeated on production, error tracking and uptime on production, log retention set.
4. **Launch checks.** Every ROADMAP launch item for self-serve and the reviewer community has evidence: register, quote, project, payment, delivery, invoice, payouts, regulated-vertical rules, webhooks, API keys, usage.
5. **Journeys on production.** J-01 to J-11 against production with replayable records (J-08's second reviewer and J-09's locale import use the production admin flows, not fixtures).

## Human-only steps

Production domain and DNS (same click paths as P02 steps A and C), reviewers' contracts under the reviewed contractor terms, and the owner's "apply" for the launch itself. The agent lists every remaining step with exact click paths when the phase starts.

## Declared spend

A production server if the decision in item 3 needs one, priced from the Hetzner API and written into `hyperpower.json` `spend` before creation, plus provider usage for calibration under a budget the owner names with "apply". Declared in full at phase start.

## Acceptance

- Three languages calibrated with reports and decision entries.
- J-01 to J-11 PROVEN on production.
- Commands: `npm run verify`, `npm run verify:deployed` (production URL), `npm run hp -- verify` all clean.

## Exit gate

`npm run hp -- gate P04 --product` exits 0 and the P04 bead reads back closed.

## Out of scope

Connectors (P05), new formats (P06), enterprise features (P07), white-label (P08).
