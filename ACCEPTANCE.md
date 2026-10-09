# ACCEPTANCE.md

The journeys Arbiter must pass and the integration checkpoints that need the owner's keys or accounts. A journey or checkpoint is proven only by a replayable record in `evidence/ledger.jsonl` whose verifier `npm run hp -- verify` can re-run. Code existing is not proof; a test passing once in a chat is not proof.

Evidence tier for every item: **replayable** (`hyperpower.json` `gates.evidenceTier.phase`).

Verifier kinds available in core: `cli`, `sql` (through `scripts/run-sql-verifier.mjs`), `http`, `commit-exists`, `playwright`. Arbiter's journeys use `cli`:

- The browser journeys J-01 to J-09 are automated by one script, `apps/web/e2e/real-flow.mjs`, against a real API, worker and web server (not mock mode). `node scripts/verify-e2e.mjs` checks the stack is up, runs it, and prints one line per journey (`J-03 PASS`) plus `E2E JOURNEYS J-01..J-09 PASS`. A journey's verifier is that command with `expectOutputContains` set to its line. The script stops at the first failure, so a PASS line means every step up to it passed. Each replay runs the whole flow (a few minutes).
- The core's `cli` verifier rewrites every argument of a `node` command into a repo path, so verifier scripts take no arguments.
- The stack for J-01 to J-09: Postgres 16 + pgvector, `alembic upgrade head`, `python -m arbiter.cli seed-demo`, API on :8000, worker, web built without `NEXT_PUBLIC_API_MOCK` on :3000 (`apps/web/README.md`, "End-to-end test").

Status values: **UNPROVEN** (no ledger record, no automated check), **COVERED** (an automated check in the repo exercises it, not yet replayed into the ledger), **PROVEN** (replayable record, last `verify` VERIFIED, with the record id).

---

## J-01: Company registers, uploads .md and .docx, gets a 4-tier quote

**Journey:** A new company registers on `/register`, uploads a Markdown file and a Word file, and asks for a quote into one target language.

**Pass condition:** The organisation and its first user exist, both files are segmented, and the quote shows the four tiers `auto`, `ai_review`, `hybrid`, `full`, each with price (decimal, currency shown), ETA and availability.

**Verifier:** `cli` `node scripts/verify-e2e.mjs`, `expectOutputContains: "J-01 PASS"` (real-flow step "quote shows 4 tiers").

**Evidence tier:** replayable

**Status:** COVERED, not yet in the ledger: `apps/web/e2e/real-flow.mjs` (reported green by the cloud build sessions up to commit 32e8cd0), API tests under `services/api/tests/api/`. UNPROVEN until P00 replays it on Windows.

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

## Ship check (not a journey, gates every phase)

`npm run verify`: runtime pins, API ruff check, ruff format --check and pytest (mock providers only), web lint with i18n:check, typecheck and build. Replayable as `cli` `node scripts/run-api-checks.mjs` and `node scripts/run-web-checks.mjs`.

Status: API checks PROVEN on Linux as baseline record EV-c769e975 (cloud install session, 2026-10-09, not assigned to a phase). P00 records both checks on Windows.

---

## Integration checkpoints (need the owner's keys or accounts)

| ID | Checkpoint | Phase | Verifier | Status |
| --- | --- | --- | --- | --- |
| INT-01 | Anthropic judge and senate on real segments: model version, prompt version and cost recorded | P01 | `cli` recompute of the stored smoke run (`evidence/p01/smoke-anthropic.json`) | UNPROVEN |
| INT-02 | DeepL and/or Google MT on real segments, same record per engine | P01 | `cli` recompute of the stored smoke run per engine | UNPROVEN |
| INT-03 | Measurement: threshold sweep on a human-labelled EN to SR set, escaped-error rate per threshold with confidence interval | P01 | `cli` `measure` recompute from the stored run file, checked against `docs/measurements/p01-en-sr.md` | UNPROVEN |
| INT-04 | Staging on Hetzner: compose deploy, TLS, migrations, J-01 to J-03 against the public URL, deployed commit equals HEAD | P02 | `cli` `node scripts/verify-deployed-version.mjs` and `node scripts/verify-e2e.mjs` against staging; attested CI provenance later | UNPROVEN |
| INT-05 | Backups: nightly encrypted off-site dump and one restore drill | P02 | `cli` check of the drill log and the remote listing | UNPROVEN |
| INT-06 | Real payout provider sends one test payout | P03 | provider reference plus `sql` read of the ledger entry | UNPROVEN |

Journeys J-10 (customer pays an invoice through the payment provider) and J-11 (a payout run reconciles with the ledger) are written in P03; later phases add their own (`phases/README.md`).
