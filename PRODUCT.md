# PRODUCT.md

What Arbiter is, who pays for it, and what it refuses to be. Written from `README.md`, `docs/DESIGN.md`, `docs/infrastructure.md`, `ROADMAP.md` and `docs/decisions.md`. Nothing here is a measured number: no customers, revenue or quality metrics exist yet. The first real numbers come from P01.

## What it is

Arbiter (working name) is an AI-native translation platform sold globally, English-first. It merges three systems translation buyers and agencies usually buy separately, and adds a fourth that none of them has:

| Layer | Comparable products | In Arbiter |
| --- | --- | --- |
| Business system | Plunet, XTRF | quotes, projects, jobs, usage, subscriptions and credits, invoices, reviewer payouts, double-entry ledger, plus the Agency OS: CRM, client price lists, executable workflow templates, dashboards, own vendors, purchase orders, capacity planning, an AI setup assistant and PM copilot |
| CAT/TMS | Trados, Phrase, memoQ, XTM, Crowdin, Lokalise | 25+ file formats with inline tags preserved (Office, web, XLIFF, IDML, DITA, subtitles, app resource files), segmentation, translation memory (in-context, exact, fuzzy, semantic), versioned termbase, a segment workbench, software strings with releases and OTA, MT and LLM routing per pair, hard QA, LQA, XLIFF 2.1 export |
| Reviewer marketplace | Smartcat, Gengo | reviewer sign-up, qualification tests, task routing by pair, domain, level and load, a keyboard-first review cockpit, per-decision pay, disputes, payouts |
| Quality decision (original) | ModelFront and Unbabel do parts of QE | an MQM-based QE judge plus a senate of independent judges with overlap arbitration, thresholds calibrated per org, content type and target language, 2 % blind control samples, and an evidence pack per job |

The core promise: a customer knows, segment by segment, why a translation shipped, who or what touched it, and what that cost. AI is never silently substituted for a human.

## Modules and add-ons (D-087)

Arbiter is sold as modules through plans; a plan grants modules and add-ons, and billing is the only writer of what an org may use.

| Module | What it is |
| --- | --- |
| `tms` | Web translation: projects, files and formats, TM, glossaries, the segment workbench, comments and client queries |
| `engine` | Translation engine API: provider keys, routing rules, budgets, scoreboard, own models |
| `ai` | The quality layer: QE judge, review and translation senates, AI editor, calibration |
| `pm` | Project management: the Agency OS, own vendors, assignments, purchase orders, vendor invoices, capacity, PM copilot |
| `auditor` | Standalone QA and LQA of bilingual files, with or without the rest of Arbiter |
| `strings` | Software strings: keys, branches, releases, OTA bundles, CLI (needs `tms`) |
| `community` | The reviewer marketplace (needs `tms`) |

Add-ons on the engine module: `eu_processing` (every AI and MT call processed in the EU, D-079), `byok` (the customer's own provider keys), `custom_models` (per-client fine-tuned models, D-059, delivered once a client has enough consented approved segments, D-088).

## Who uses it

| Audience | Where | What they do |
| --- | --- | --- |
| Companies buying translation (product, docs, marketing, regulated content) | `/app` | upload files or connect content, get a quote per tier, order, review exceptions, approve, download with the evidence pack, pay invoices |
| Agencies and language service providers | `/app` with the Agency OS | run their own clients, vendors, price lists and workflows on Arbiter; later white-label (P08) |
| Software teams | `/app/strings`, CLI, OTA | push string files, release translations, serve them over the air |
| Vendors of an agency | `/vendor/[token]` | accept offers and work assignments without an account |
| Reviewers (freelance linguists) | `/reviewer` | apply, pass a qualification test, take review tasks, get paid per decision |
| The operator | `/admin` | reviewers, payouts, disputes, UI languages, platform health |
| Developers | `/v1` API, webhooks | automate jobs; connectors from P05 |

## Who pays and for what

- **Customers pay per word per tier.** The quote shows every tier with price, ETA and availability before ordering:
  - `auto`: nobody touches a segment that passes QE and the senate; the org's `no_reviewer_policy` decides the rest.
  - `ai_review`: an AI editor works segments below the threshold.
  - `hybrid`: a human reviewer works segments below the threshold, the rest ships automatically.
  - `full`: a human reviewer on every segment.
- Regulated verticals (for example pharma, legal, medical) can only buy `hybrid` or `full`; the API enforces it.
- TM matches lower the price (TM analysis in the quote). Agencies can set client price lists.
- Plans (modules and add-ons, priced as data) are sold by subscription; usage beyond the plan is drawn from prepaid credits or billed as overage at period close. Paddle is the merchant of record (global VAT and sales tax, chargebacks, enterprise invoices with terms and PO numbers); our database stays the source of truth for usage, credits and entitlements (D-084). Enterprise customers can pay by bank invoice. Revenue is recognised at delivery (D-041). Live payments start in P03.
- A platform fee of 0 to 8 % (default 5 %) on human work is charged to the customer and shown on quotes for `hybrid` and `full` (D-085).
- **Reviewers are paid** per decision on the ledger (D-024), through Payoneer or PayPal with bank files as fallback (D-085); live payouts start in P03. Agencies pay their own vendors outside the platform rails (D-078).

## Why it can win

1. **The decision layer.** Calibrated QE plus senate decides which segments need a human, which lowers cost where quality allows and keeps humans where it does not. Proven or disproven by measurement in P01; until then it is a hypothesis, not a claim.
2. **Evidence by default.** Append-only provenance and an evidence pack per job (JSON + PDF) answer "who touched this and why did it ship" for audits and regulated buyers.
3. **One system instead of three.** Business system, CAT/TMS and reviewer marketplace share one data model, so quotes, routing, pay and invoices use the same segments and the same ledger.
4. **Honest tiers.** No silent AI substitution; the `no_reviewer_policy` choice is the customer's and is recorded.
5. **Agency OS.** Agencies can describe their setup in plain language and get workflows, price lists and dashboards proposed, reviewed and applied (D-042).

## What it is not

- Not a general machine translation engine: it routes between providers (Anthropic, OpenAI, DeepL, Google, Claude on Bedrock or Vertex, customer endpoints) and judges their output; own models are per client, trained only with consent.
- Not a free consumer translator.
- Not a staffing agency: reviewers are independent contractors on reviewed terms (legal review before public launch, P03).
- Not a desktop CAT tool and not a mobile app.
- Not claiming quality numbers it has not measured. English to Serbian is the first measurement pair: a test instrument, not the target market.

## Constraints that shape the product

- Sold globally. GDPR transfers rest on DPAs with the EU-US Data Privacy Framework or SCCs, not on EU hosting (D-079); legal review before public launch.
- Hosting on Hetzner Cloud with managed Postgres (Ubicloud), one region per deployment; a US cell or an AWS enterprise region only when demand or a contract triggers it (P09).
- Segment text goes to external AI providers only for organisations that opted in; EU-only processing is a paid add-on and never falls back silently.
- English-first UI; other UI languages are added through string export and import without a deploy (D-046).
- Every money value is a decimal with its currency.

## Phase map

`phases/README.md` holds the order (D-090): P00 install and verify, P01 measurement, P02 production-grade staging, P03 money and legal, P04 self-serve launch, P05 integrations, P06 own models in production, P07 enterprise, P08 white-label, P09 enterprise region and US cell.
