# P03: Money and legal

## Goal

Money moves for real in both directions on staging: a customer subscribes or buys credits through Paddle (sandbox, then live with an approved domain), a reviewer receives a payout through Payoneer or PayPal (sandbox, then one small real payout), and the ledger reconciles both to the cent. The documents a public launch needs (terms, privacy policy, DPA, public subprocessor list, reviewer contractor terms, trust page) are drafted and have had legal review before public launch, tax questions are answered by an adviser, and a security pass has closed its findings. The company-entity question for a future Stripe rail is put to the owner as an open decision with the facts.

## Already built (not re-done here)

Plans as data with an admin editor, subscriptions, the entitlements writer for modules and add-ons, the prepaid credit wallet on the double-entry ledger, period-close overage, provider invoice records, our own PDF invoices for manual billing (D-072 to D-077). Adapters: Paddle (merchant of record, checkout, portal, charges, signed idempotent webhooks at `/webhooks/paddle`), Stripe (same interface, off unless configured), manual bank-transfer provider. Payout rails: Payoneer, PayPal, bank files (SEPA pain.001, CSV, Wise CSV) with onboarding, minimums and polling; the platform fee (default 5 %, 0 to 8) on quotes and on credited review pay (D-073). Web: billing page, public `/pricing`, `/checkout/paddle`, `/reviewer/payouts`, `/admin/billing`. All proven only against mocks and recorded fixtures.

## Scope

1. **Paddle sandbox.** Sandbox account (human step A), API key, webhook destination pointing at `https://api.staging.<domain>/webhooks/paddle` with the events the adapter handles, client-side token for `/checkout/paddle`. Map the seeded plans and credit packs to sandbox prices (catalog prices through the API, not by hand). Prove INT-09: a test org on staging buys a plan in the sandbox checkout with Paddle's test card, the signed webhook arrives once, the subscription is active, `org.settings["modules"]` and `["addons"]` follow the plan, the credit ledger and invoice record are written, and a refund webhook reverses correctly. Replayable record over the stored webhook payloads and the ledger rows (`sql` verifier).
2. **Paddle live.** Live account verification with the business documents (human step A), domain approval for the staging and production app domains (website, terms, privacy policy and pricing page must be live first; research: review takes about 5 to 7 business days, so this starts on day one of the phase), live keys in the `production` GitHub environment only. No live charge on staging.
3. **Payout sandboxes.** Payoneer partner sandbox and PayPal Payouts sandbox credentials (human steps B and C). Prove INT-10: a sandbox reviewer onboards a payout method, earns pay on the ledger, a payout run sends through the rail, the poll settles it, and the ledger shows the move only after settlement.
4. **One real payout (INT-11).** One payout of at most 10 EUR through the live rail of the owner's choice to the owner's own payee account; provider reference and ledger entry in evidence.
5. **Reconciliation.** A CLI report matching ledger balances with Paddle and payout provider statements to the cent, tested with recorded statements; a replayable record shows zero difference on the stored statements.
6. **Subprocessors, DPA, trust page.** Finish `docs/subprocessors.md` from the draft with the providers actually configured, publish it with the DPA, terms, privacy policy, reviewer contractor terms and a trust page in the web app (strings in `messages/en.json`, legal text versioned). Written neutrally; legal review before public launch (human step D).
7. **Tax and compliance questions for an adviser.** Prepared as a brief (human step D): Paddle as merchant of record for the owner's situation and the invoice rule of D-029 for manual invoices; payee obligations for reviewer payouts (identity checks, sanctions screening, US tax forms W-8BEN and W-9 for US-linked payees, whether EU DAC7 reporting applies to review work, research could not confirm it). Answers land as decision entries.
8. **Company entity for Stripe (open owner decision).** A one-page brief with the research facts: Stripe Atlas US LLC (500 USD once, 100 USD a year, Form 5472 every year or a 25,000 USD penalty per form) or an Estonian company via e-Residency (about 415 EUR state fees, 700 to 2,000 EUR a year to run), and the risk that a company managed from Serbia is treated as Serbian-resident. The owner decides after the adviser's check; until then the Stripe adapter stays off. Nothing is formed in this phase.
9. **Kamal and secrets for money.** Add the billing and payout settings (`ARBITER_PADDLE_*`, `ARBITER_PAYONEER_*`, `ARBITER_PAYPAL_*`, `ARBITER_BILLING_PROVIDER`, seller details) to the Kamal secret names, `.kamal/secrets-common` and `release.yml`; sandbox values on staging.
10. **Security pass.** Tenancy tests reviewed for every route group (all seven modules and billing), rate limits on auth, public forms, OTA and webhooks, upload size and count limits, webhook target validation, BYOK keys never returned, OSV-Scanner on both dependency sets with no high or critical finding, Betterleaks on the full history clean, `security-reviewer` PASS.

## Human-only steps

**A. Paddle.**
1. Sandbox: open https://sandbox-login.paddle.com/signup (if the URL has moved, the agent finds the current sandbox sign-up from Paddle's developer docs), create the sandbox account.
2. In the sandbox dashboard open "Developer tools", "Authentication", create an API key with the permissions the agent lists, copy it, paste as `PADDLE_SANDBOX_API_KEY=...`. On the same page create a client-side token, paste as `PADDLE_SANDBOX_CLIENT_TOKEN=...`.
3. The agent creates the webhook destination through the API and stores its secret. If the API cannot, open "Developer tools", "Notifications", "New destination", URL `https://api.staging.<domain>/webhooks/paddle`, tick the events the agent lists, save, copy the secret key, paste as `PADDLE_SANDBOX_WEBHOOK_SECRET=...`.
4. Live: open https://login.paddle.com/signup, create the live account, complete business verification with your documents (Paddle's form asks for identity and business details), then request domain approval for your app domain from the "Checkout" settings ("Website approval" or "Request domain approval"). Tell the agent when Paddle confirms by email.
5. Live keys: same pages as steps 2 and 3 in the live dashboard; paste as `PADDLE_API_KEY=...`, `PADDLE_CLIENT_TOKEN=...`, `PADDLE_WEBHOOK_SECRET=...`. The agent stores them only in the `production` environment.

**B. Payoneer.**
1. Open https://www.payoneer.com and find the partner or mass payouts programme (the agent gives the current application URL from Payoneer's developer documentation); apply as a platform paying freelancers.
2. When approved, Payoneer issues sandbox and production program credentials (client id, client secret, program id). Paste them as `PAYONEER_CLIENT_ID=...`, `PAYONEER_CLIENT_SECRET=...`, `PAYONEER_PROGRAM_ID=...` (sandbox first).
3. Success: the agent registers a sandbox payee and shows its onboarding link.

**C. PayPal.**
1. Open https://www.paypal.com/business and create or upgrade to a Business account.
2. Open https://developer.paypal.com/dashboard/applications, log in, "Create App", name `arbiter-payouts`, type Merchant, sandbox first. Copy the client id and secret, paste as `PAYPAL_CLIENT_ID=...` and `PAYPAL_CLIENT_SECRET=...`.
3. Payouts must be enabled on the live account: in the app's settings tick "Payouts"; if PayPal asks for a review, submit it and tell the agent when it is approved.
4. Success: the agent sends a sandbox payout and shows it settled.

**D. Legal and tax review.** The agent prepares the drafts and a short brief per document and per question; you send them to your adviser and counsel and paste back the approved versions or the requested changes. Tell the agent the review date for each; no adviser names are needed in the repo.

**E. Entity decision.** After the adviser's answer on item 8, tell the agent "entity: none for now", "entity: US LLC" or "entity: Estonia". Forming a company is outside this phase.

## Declared spend

Paddle and payout provider fees on test transactions (Paddle research: 5 % + 50 cents per transaction, sandbox is free), and one real test payout of at most 10 EUR plus its fee. Adviser and counsel fees are the owner's own decision and are not authorised by "apply". No new servers.

## Acceptance

- INT-09: Paddle sandbox checkout to webhook to entitlement and ledger, replayable record.
- INT-10: Payoneer or PayPal sandbox payout settled only after the poll, replayable record.
- INT-11: one real payout with provider reference and ledger entry.
- J-15 PROVEN on staging with the sandbox checkout step added to the e2e.
- Reconciliation report replays to zero difference on the recorded statements.
- `docs/subprocessors.md`, DPA, terms, privacy policy, contractor terms and trust page published on staging; legal and tax items marked done only with the review date and the approved document version in `evidence/p03/`.
- Commands: `npm run verify` exit 0, `npm run verify:deployed` exit 0, `npm run hp -- verify` 0 broken.

## Exit gate

`npm run hp -- gate P03 --product` exits 0 and the P03 bead reads back closed.

## Out of scope

Production deploy and first customers (P04). Forming a company or activating Stripe. Agency invoicing to its own clients (P08). Certification audits (P07).
