# P03: Money and legal readiness

## Goal

Money moves for real in both directions on staging: a customer pays an invoice through a payment provider, a reviewer receives a payout through a payout provider, and the ledger reconciles both to the cent. The legal and tax documents a public launch needs have had legal review before public launch, and a security pass has closed its findings.

## Already built (not re-done here)

Quotes, usage metering, monthly invoices with the starting tax rule (D-029), the double-entry ledger, revenue recognised at delivery (D-041), reviewer per-decision pay (D-024), payout runs with tax-info completeness and failure handling on the ledger side (D-027, D-028) against a mock payout provider, regulated-vertical rules in the API, tenancy tests per module.

## Scope

1. **Payment provider decision.** Compare at least a direct processor and a merchant-of-record option for a global B2B SaaS selling per-word services (tax collection, invoicing, payout currency, fees, EU data handling). Decision entry with the rejected option. The owner opens the account (human step A).
2. **Payment integration.** Checkout or invoice payment for customer invoices, provider webhooks verified and idempotent, payments posted to the ledger as `Decimal` with currency, refunds and failed payments handled, sandbox tests in CI with recorded fixtures (no network in tests). New journey J-10: a customer pays an invoice in the provider sandbox and the ledger shows it.
3. **Payout provider.** Real payout provider behind the existing payout interface (for example Wise; decision entry with the rejected option). Reviewer payout details collected and stored by the provider, not by Arbiter. One real test payout of a small amount to the owner's own account (INT-06, provider reference in evidence).
4. **Reconciliation.** A report that matches ledger balances with provider statements for payments and payouts to the cent, as a CLI command with tests. New journey J-11: a payout run reconciles with the ledger.
5. **Tax review.** The invoice VAT rule (D-029) and the payment provider's tax handling reviewed by a qualified adviser (human step B); changes land as a decision entry.
6. **Legal review before public launch.** Terms of service, privacy policy, DPA, subprocessor list (AI and MT providers, hosting, payment, payout, error tracking), reviewer contractor terms, written neutrally and reviewed by counsel (human step B). Published pages in the web app read from `messages/en.json`.
7. **Security pass.** Tenancy tests reviewed for every route group, rate limits on auth and public endpoints, upload size and count limits, webhook target validation, OSV-Scanner on both dependency sets with no high or critical finding, Betterleaks on the full history clean, `security-reviewer` PASS.

## Human-only steps

**A. Provider accounts.** The agent gives the exact sign-up path for the chosen payment and payout providers after the decision in items 1 and 3 (business verification needs the owner's company documents). The owner pastes sandbox keys, then live keys, into the chat as the `ARBITER_*` names the agent adds to `.env.example`.

**B. Legal and tax review.** The agent prepares the drafts and a short brief per document; the owner sends them to his adviser and counsel and pastes back the approved versions or the requested changes.

## Declared spend

Payment and payout provider transaction fees on test transactions, and one test payout of at most 10 EUR. Adviser and counsel fees are the owner's own decision and are not authorised by "apply". No new servers.

## Acceptance

- J-10 and J-11 PROVEN with replayable records (sandbox for J-10, the test payout for INT-06 and J-11).
- Reconciliation report replays to zero difference on the recorded statements.
- Legal and tax items marked done only with the review date and the approved document version in `evidence/p03/` (no adviser names needed).
- Commands: `npm run verify` exit 0, `npm run verify:deployed` exit 0, `npm run hp -- verify` 0 broken.

## Exit gate

`npm run hp -- gate P03 --product` exits 0 and the P03 bead reads back closed.

## Out of scope

Public sign-up on a production domain (P04). Agency invoicing to its own clients (P08).
