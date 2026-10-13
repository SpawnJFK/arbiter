# ACCEPTANCE.md

The journeys Arbiter must pass and the integration checkpoints that need the owner's keys or accounts. A journey or checkpoint is proven only by a replayable record in `evidence/ledger.jsonl` whose verifier `npm run hp -- verify` can re-run. Code existing is not proof; a test passing once in a chat is not proof.

Evidence tier for every item: **replayable** (`hyperpower.json` `gates.evidenceTier.phase`).

Verifier kinds available in core: `cli`, `sql` (through `scripts/run-sql-verifier.mjs`), `http`, `commit-exists`, `playwright`. Arbiter's journeys use `cli`:

- The browser journeys are automated by one script, `apps/web/e2e/real-flow.mjs` (30 steps on 2026-10-13), against a real API, worker and web server (not mock mode). `node scripts/verify-e2e.mjs` checks the stack is up, runs it, echoes every step line, and prints one line per journey (`J-03 PASS`) plus a final line. Today the script maps J-01 to J-09 and ends with `E2E JOURNEYS J-01..J-09 PASS`; P00 item 10 adds the J-10 to J-18 markers below to its `JOURNEYS` table, after which it prints `J-10 PASS` to `J-18 PASS` and `E2E JOURNEYS J-01..J-18 PASS`. A journey's verifier is that command with `expectOutputContains` set to its line. The script stops at the first failure, so a PASS line means every step up to it passed. Each replay runs the whole flow (a few minutes).
- Journeys whose browser step only opens a page also name the pytest files that cover the deeper pass condition; those run inside `node scripts/run-api-checks.mjs` (the ship check), which is their second verifier.
- The core's `cli` verifier rewrites every argument of a `node` command into a repo path, so verifier scripts take no arguments. Remote runs (staging, production) set `BASE_URL` and `API_URL` in the environment.
- The local stack: Postgres 16 + pgvector, `alembic upgrade head`, `python -m arbiter.cli seed-demo` and `seed-plans`, API on :8000, worker, web built without `NEXT_PUBLIC_API_MOCK` on :3000 (`apps/web/README.md`, "End-to-end test").

Status values: **UNPROVEN** (no ledger record, no automated check), **COVERED** (an automated check in the repo exercises it, not yet replayed into the ledger), **PROVEN** (replayable record, last `verify` VERIFIED, with the record id).

---

## J-01: Company registers, uploads .md and .docx, gets a 4-tier quote

**Journey:** A new company registers on `/register`, uploads a Markdown file and a Word file, and asks for a quote into one target language.

**Pass condition:** The organisation and its first user exist, both files are segmented, and the quote shows the four tiers `auto`, `ai_review`, `hybrid`, `full`, each with price (decimal, currency shown), ETA and availability.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-01 PASS"` (real-flow step "quote shows 4 tiers").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `apps/web/e2e/real-flow.mjs` (green in the cloud sessions, last run 2026-10-13 with all 30 steps), API tests under `services/api/tests/api/`. UNPROVEN until P00 replays it on Windows.

---

## J-02: Auto tier job runs MT, QE and senate and is delivered; file and evidence PDF download

**Journey:** The customer orders the `auto` tier for the Markdown file.

**Pass condition:** The job runs prepare, translate, score and decide through the `work_items` worker, reaches `delivered` without a human, the translated file downloads, and the evidence pack PDF downloads. Every segment change has a `provenance_events` row.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-02 PASS"` (step "evidence PDF ok").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs`, pipeline and evidence tests in `services/api/tests/`. UNPROVEN until P00.

---

## J-03: Full tier job waits for humans; a reviewer clears the cockpit queue; job delivered

**Journey:** The customer orders the `full` tier for the Word file. The demo reviewer opens `/reviewer`, accepts one segment with `A` and edits another with `E` then `Ctrl+Enter`.

**Pass condition:** The job waits in human review, the reviewer's queue holds only that job's tasks, the job is delivered after the queue is cleared, and the PM sees it delivered.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-03 PASS"` (step "full-tier job delivered after human review").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs`, community queue and review tests. UNPROVEN until P00.

---

## J-04: A forbidden glossary term blocks a segment and it appears in Exceptions

**Journey:** The PM adds a glossary with a mandatory and a forbidden term, then orders a job whose source triggers the forbidden term.

**Pass condition:** The segment is blocked by the hard QA glossary check (R-GL), the job shows up on the Exceptions screen, and the exception links to the job filtered on blocked segments.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-04 PASS"` (step "blocked segment listed in Exceptions").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs`, glossary and QA tests in `services/api/tests/`. UNPROVEN until P00.

---

## J-05: A reviewer applicant applies and takes a qualification test

**Journey:** A new person applies as a reviewer from `/reviewers` and takes the qualification test for a pair.

**Pass condition:** The application is stored, the test is graded automatically, and the result ("Passed" or "Not passed this time") is shown with retake rules applied.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-05 PASS"` (step "applicant took a test:").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs`, community testing tests. UNPROVEN until P00.

---

## J-06: The platform admin sees reviewers and payouts

**Journey:** The operator signs in and opens the reviewer and payout screens under `/admin`.

**Pass condition:** Reviewers with levels and scores are listed, payout runs and their ledger state are visible, and non-admin users cannot reach these screens or the `/v1/admin` endpoints.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-06 PASS"` (step "admin sees reviewers and payouts").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs`, admin role tests in `services/api/tests/api/test_api_rev_reviewers.py` and `test_api_i18n.py` (non-admin gets 403). UNPROVEN until P00.

---

## J-07: The AI assistant turns an agency description into a plan; applying it creates the setup

**Journey:** A PM describes a fictional agency in English to the setup assistant (clients, workflow with second review and client approval, price per word, dashboard wishes) and applies the proposed plan.

**Pass condition:** The assistant proposes a plan and changes nothing until a human applies it (D-042). After apply, the accounts, the workflow template, the price list and the dashboard exist, named in the UI locale (D-045).

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-07 PASS"` (step "accounts, the pharma workflow and the new dashboard exist").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs` (built-in planner, no provider key), assistant tests in `services/api/tests/agency/`. With a real Anthropic key the model path is exercised in P01. UNPROVEN until P00.

---

## J-08: Account workflow with second review and client approval

**Journey:** A project for the pharma account runs the account's workflow: first review, second review by a senior reviewer, then client approval.

**Pass condition:** Two different reviewers take the two review steps, the job waits for the client, the client approves, and the job is delivered. Regulated-vertical rules keep `auto` and `ai_review` unavailable for it.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-08 PASS"` (step "client approved, job delivered").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs` (the second reviewer comes from `apps/web/e2e/ensure_reviewer.py`), workflow pipeline tests. UNPROVEN until P00.

---

## J-09: Admin adds a UI language via XLIFF export and import; the UI switches with English fallback

**Journey:** The operator exports the English UI catalog as XLIFF for `de`, fills some targets, imports a file with a broken placeholder, then the fixed file, enables `de`; the PM switches language.

**Pass condition:** The broken placeholder is rejected per key, the fixed strings import, `de` is enabled, and the PM sees German navigation with English fallback for missing keys, then switches back to English (D-046).

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-09 PASS"` (step "PM switched to Deutsch").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `real-flow.mjs`, i18n API tests. UNPROVEN until P00.

---

## J-10: Engines, BYOK and the EU route

**Journey:** An org admin opens Engines, adds the org's own key for a provider (BYOK), sees it masked, sets a routing rule and a monthly budget, and previews which engine a job would use; the Own models page opens. An org with `processing_region = eu` and no EU engine gets a visible failure, never a global fallback.

**Pass condition:** The key is stored encrypted and only its last 4 characters are ever returned; routing preview follows org rule, platform rule, scoreboard, default; capped providers drop out; the EU org's job fails with `no EU engine configured` and provenance records `routing_blocked`.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-10 PASS"` (marker "engines and own models pages render"), plus the ship check for `services/api/tests/api/test_api_engines.py` (`test_byok_create_never_returns_secret_and_is_encrypted`, routes and budgets, preview, region), `tests/engines/test_engines_routing.py`, `tests/engines/test_engines_eu.py`.

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger. The browser step only opens the pages; the key, routing and EU behaviour are covered by pytest. A deeper browser step (add a BYOK key in the UI) is a Beads issue from P00. Real EU calls: INT-03. UNPROVEN until P00.

---

## J-11: Software strings with a release and an OTA bundle

**Journey:** A developer creates a string project in the UI, pushes a JSON file with two keys, the keys are translated, a release is published and the public OTA endpoint serves the bundle.

**Pass condition:** Keys exist on the main branch, translations are attached, the release has a version label, and the OTA bundle for the release is served without login.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-11 PASS"` (marker "strings: project created, 2 keys pushed, translated, release"), plus `services/api/tests/strings/` (`test_release_publish_and_ota`, branches and merge, formats, placeholders, CLI).

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger. UNPROVEN until P00.

---

## J-12: Workbench editor edits and confirms a segment

**Journey:** A linguist opens a job in the segment editor (`/app/jobs/{id}/editor`), edits a segment with live QA, TM and glossary panels, and confirms it.

**Pass condition:** The edit is saved, a provenance event records the human edit, and the segment state changes through `states.py`.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-12 PASS"` (marker "workbench editor opened and saved an edited segment"), plus `services/api/tests/tms/test_tms_workbench.py` (split and merge, find and replace, locks, comments and queries) and `test_tms_tmtools.py`.

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger. UNPROVEN until P00.

---

## J-13: Auditor scores a bilingual file

**Journey:** A quality manager uploads a small XLIFF file to the standalone auditor (`/app/auditor`) and waits for the audit.

**Pass condition:** The audit runs on the work queue, reports segments audited, an MQM score and a verdict.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-13 PASS"` (marker "auditor: XLIFF audited"), plus `services/api/tests/auditor/test_auditor.py`.

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger. UNPROVEN until P00.

---

## J-14: Own vendor is suggested for a human step; capacity shows it

**Journey:** A PM creates an own vendor in the UI with a language pair and rate; the vendor is suggested for the review step of a job; the capacity page opens.

**Pass condition:** The vendor exists in the org only, appears in the assignment suggestions for `human_review`, and the capacity planner renders.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-14 PASS"` (marker "vendor created and suggested for the review step"), plus `services/api/tests/agency/test_agency_vendors.py` (offers, timeout escalation, workbench token, POs, vendor invoices) and `test_agency_capacity.py`.

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger. The full offer, accept, PO and vendor invoice flow is covered by pytest, not by the browser. UNPROVEN until P00.

---

## J-15: Billing: plans, checkout and entitlements

**Journey:** An org admin opens Billing, the public pricing page lists the plans, the admin starts a checkout; after the provider confirms payment the plan's modules and add-ons are active.

**Pass condition:** Pricing shows the seeded plans from the database; access starts only after a signed provider webhook; `org.settings["modules"]` and `["addons"]` follow the plan; the credit ledger and invoice records are written; a refund reverses.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-15 PASS"` (marker "billing settings and the public pricing page render"), plus `services/api/tests/billing/test_bill_api.py` (`test_paddle_checkout_webhooks_invoices_credits_refund_portal_cancel`, manual checkout, add-ons follow plan) and `test_bill_providers.py`.

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger. Locally the checkout runs against recorded Paddle fixtures; the real sandbox checkout is INT-09 (P03), after which the browser step is extended. UNPROVEN until P00.

---

## J-16: Team, roles and audit log

**Journey:** An org admin opens Settings: team (invite a user), roles, the audit log and modules with add-ons.

**Pass condition:** Invites go through the one invite flow (D-078); a custom role cannot grant more than its creator holds; every admin action writes an append-only audit row; modules and add-ons show read-only from the plan.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-16 PASS"` (marker "settings: team, audit log, modules with add-ons render"), plus `services/api/tests/platform/test_roles_team.py`, `test_audit.py`, `test_modules_api.py`.

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger. The browser step only opens the pages; invite, role and audit behaviour are covered by pytest. UNPROVEN until P00.

---

## J-17: SSO login with OpenID Connect

**Journey:** An org admin configures OIDC SSO, proves the email domain by DNS TXT, and a user signs in through the IdP; with SSO enforced, password login is refused.

**Pass condition:** The code flow with PKCE completes, the ID token is validated (issuer, audience, expiry, nonce), the user is provisioned just in time into the right org and audited; emails outside verified domains, expired state and PKCE mismatch are rejected.

**Verifier:** `cli` `node scripts/run-api-checks.mjs` (ship check), covering `services/api/tests/platform/test_sso.py` against a fake IdP. No browser step.

**Evidence tier:** replayable

**Status:** COVERED by pytest only, not yet in the ledger. A real IdP is tried in P07. UNPROVEN until P00.

---

## J-18: Presigned direct upload

**Journey:** A customer uploads a source file in the new-project wizard; the browser asks for an upload ticket, PUTs the bytes to the ticket URL and completes the upload.

**Pass condition:** With the local backend the bytes go to the API's HMAC-signed blob endpoint; with the S3 backend they go straight to the presigned bucket URL; `complete` checks size and content and registers the file with its handler options; tenancy, idempotency and module gates hold.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-18 PASS"` (marker "quote shows 4 tiers": the wizard in J-01 uploads through `lib/upload.ts`), plus `services/api/tests/api/test_api_ops_uploads.py` (`test_s3_direct_upload_and_presigned_download` with moto, size mismatch, damaged file, tenancy) and `test_api_ops_storage.py`.

**Evidence tier:** replayable

**Status:** COVERED locally with the local backend, not yet in the ledger. The real bucket and a 1 GB file: INT-06 (P02). UNPROVEN until P00.

---

## Ship check (not a journey, gates every phase)

`npm run verify`: runtime pins, API ruff check, ruff format --check and pytest (mock providers only), web lint with i18n:check, typecheck and build. Replayable as `cli` `node scripts/run-api-checks.mjs` and `node scripts/run-web-checks.mjs`.

Status: API checks PROVEN on Linux as baseline record EV-c769e975 (cloud install session, 2026-10-09, not assigned to a phase; 441 tests then, 789 since the 2026-10-13 merge). P00 records both checks on Windows.

---

## Integration checkpoints (need the owner's keys or accounts)

| ID | Checkpoint | Phase | Verifier | Status |
| --- | --- | --- | --- | --- |
| INT-01 | Provider keys: one authenticated call per configured provider; Anthropic judge and senate and at least one MT engine on real segments with model version, prompt version and cost recorded | P01 | `cli` recompute of the stored smoke runs (`evidence/p01/smoke-<engine>.json`) | UNPROVEN |
| INT-02 | Measurement: threshold sweep on a human-labelled EN to SR set, escaped-error rate per threshold with confidence interval | P01 | `cli` `measure` recompute from the stored run file, checked against `docs/measurements/p01-en-sr.md` | UNPROVEN |
| INT-03 | EU route: a job of an EU org through Bedrock EU and/or Vertex `eu` with the provider-reported region in provenance and the evidence pack; the same job without an EU engine fails with `no EU engine configured` | P01 if keys exist, else before the first EU customer (P03) | `cli` recompute over the stored run file | UNPROVEN |
| INT-04 | Ubicloud Postgres 16 accepts `CREATE EXTENSION vector` and `pg_trgm` and answers a vector query (or the D-081 fallback, with its superseding decision) | P02 | `sql` verifier against the staging database (`select extname from pg_extension`) | UNPROVEN |
| INT-05 | Staging deploy: Kamal over Tailscale, migrations in the pre-deploy hook, all 30 e2e steps (J-01 to J-18) against the public URL, deployed commit equals HEAD | P02 | `cli` `node scripts/verify-deployed-version.mjs` and `node scripts/verify-e2e.mjs` with staging `BASE_URL` and `API_URL` | UNPROVEN |
| INT-06 | A 1 GB file uploaded on staging through the presigned flow, bytes browser to bucket, size and checksum match after `complete` | P02 | `cli` check of the stored upload record and a `sql` read of the file row | UNPROVEN |
| INT-07 | Backups: nightly encrypted dump to Backblaze B2 EU and a restore drill with `ok: true`; one PITR restore duration recorded | P02 | `cli` check of `evidence/p02/restore-drill.json` | UNPROVEN |
| INT-08 | Attested deploy: build provenance for both images of the deployed SHA verifies (`gh attestation verify`), or the recorded GitHub-plan fallback | P02 | `cli` attestation check for the SHA in `shipped.staging` | UNPROVEN |
| INT-09 | Paddle sandbox checkout: signed webhook once, subscription active, modules and add-ons follow the plan, ledger and invoice record written, refund reverses | P03 | `sql` verifier over the stored webhook rows and ledger entries | UNPROVEN |
| INT-10 | Payoneer or PayPal sandbox payout: onboarding, payout run, settlement only after the poll | P03 | `sql` verifier over the payout batch and ledger entries | UNPROVEN |
| INT-11 | One real payout of at most 10 EUR to the owner's own payee account | P03 | provider reference plus `sql` read of the ledger entry | UNPROVEN |

Earlier numbering (2026-10-09 plan): INT-01 and INT-02 are now INT-01; INT-03 is INT-02; INT-04 is INT-05; INT-05 is INT-07; INT-06 is INT-11. None had evidence. Later phases add their own journeys from J-19 (`phases/README.md`).

