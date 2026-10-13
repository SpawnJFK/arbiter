# Phases

Frozen order (rewritten 2026-10-13, D-090). Work only on the current phase (`memory-bank/activeContext.md` names it). A phase closes when `npm run hp -- gate P0x --product` exits 0, which means: every evidence record listed for the phase in `hyperpower.json` re-verifies, `npm run verify` passes, and the phase bead reads back as closed from Beads.

| Phase | File | Journeys and checkpoints | Depends on | Human steps | Declared spend (ceiling) |
| --- | --- | --- | --- | --- | --- |
| P00 | `phase-00-install-and-verify.md` | J-01 to J-18 replayed locally on Windows (30 e2e steps) | none | Docker Desktop (if missing), Context7 key, Cursor restart | none |
| P01 | `phase-01-measurement-harness.md` | INT-01, INT-02, INT-03 (EU route, if keys) | P00 | Provider keys with spend caps, EN to SR reference set with human MQM labels, optional AWS Bedrock or Vertex access | provider usage, suggested 50 EUR + 20 EUR for the EU route |
| P02 | `phase-02-staging-deploy.md` | INT-04 to INT-08; J-01 to J-18 on staging | P01 | Domain + Cloudflare, Hetzner, Ubicloud, Tailscale, Backblaze B2 (EU), PostHog EU, Better Stack, SMTP provider, GitHub plan check | staging infra up to 60 EUR per month (estimate), pgvector check up to 5 EUR, GitHub plan up to 25 EUR per month only if needed |
| P03 | `phase-03-money-and-legal.md` | INT-09, INT-10, INT-11; J-15 with sandbox checkout | P02 | Paddle sandbox and live (domain approval), Payoneer, PayPal, legal and tax review, entity decision | test transaction fees, one real payout up to 10 EUR |
| P04 | `phase-04-self-serve-launch.md` | J-01 to J-18 on production | P03 | Better Stack responder seat, reviewer approvals, launch "apply", production deploy approvals | production infra up to 200 EUR per month (estimate), responder seat 34 USD per month, calibration usage (suggested 100 EUR) |
| P05 | `phase-05-integrations.md` | J-19 onward (connectors) | P04 | GitHub App, Figma app, CMS sandbox, Slack app | none |
| P06 | `phase-06-own-models.md` | training and activation journeys | P04 and a consenting customer | Together or Fireworks key | training and serving, declared at phase start (suggested 100 EUR) |
| P07 | `phase-07-enterprise.md` | SAML, SCIM, audit export journeys | P04 and an enterprise deal | IdP test tenants, compliance platform, auditor, pen-test vendor | declared at phase start (research ranges in the file) |
| P08 | `phase-08-white-label.md` | tenant-isolation journeys | P04 | A pilot agency's DNS and branding | none expected |
| P09 | `phase-09-enterprise-region.md` | journeys in the new cell, cross-cell isolation | P04 and a contract or US demand | AWS account and Bedrock access, the trigger decision | declared at phase start |

P05 to P09 depend on P04 but not on each other; after P04 the owner may reorder them (a decision entry records it). P06, P07 and P09 start only on their trigger.

Beads: P00 creates one bead per phase (P00 to P09) and writes its id into `hyperpower.json` `phases.P0x.beadId`. Until then every phase shows `bead: "to be created in P00"`.

Every phase file has the same sections: Goal, Already built, Scope, Human-only steps (numbered, click by click, with URLs), Declared spend (ceilings), Acceptance, Exit gate, Out of scope. If a phase needs a human step that is not listed, first check whether a CLI, MCP or API can do it (`CLAUDE.md` law 2); only then add it, with exact click paths.

## Owner override on 2026-10-13

The owner asked for every product module to be built ahead of the plan while P00 was current (D-089). That work is listed below as built; no phase item was ticked for it, and each phase still proves it through its own gate.

## Already built (tested locally, never deployed)

789 backend tests (mock providers only), web lint with i18n, typecheck, build, and the `real-flow.mjs` browser test with 30 steps, all green on Linux on 2026-10-13. Not re-done in any phase; P00 replays it into the evidence ledger on the owner's machine. Details: `memory-bank/progress.md`.

- **Foundation**: monorepo, config (`ARBITER_*`), `contracts.py`, state machines, SQLAlchemy models, Alembic migrations 0001 to 0011 in one chain, append-only provenance trigger, `alembic upgrade head` equals `create_all` check (D-037).
- **Module `tms`**: file formats (docx, xlsx, pptx, html, md, json, po, txt, csv, tsv, xliff, IDML, SRT, VTT, ASS, XML with ITS, DITA, Android and iOS strings, ARB, properties, resx, YAML, AsciiDoc) with handler options (D-076); segmentation, TM, glossaries; workbench editor, comments and client queries, TM tools, LQA scorecards (D-063 to D-066).
- **Module `engine`**: Anthropic, OpenAI, DeepL, Google, Bedrock, Vertex, OpenAI-compatible, mock; keys in the database with BYOK (D-056); EU route without fallback (D-057); routing rules and budgets (D-058); own models (D-059). Add-ons `eu_processing`, `byok`, `custom_models`.
- **Module `ai`**: hard QA, MQM-Core QE judge, review and translation senates, AI editor, calibration with control samples.
- **Module `pm`**: Agency OS (CRM, price lists, workflows, dashboards, setup assistant), own vendors, assignments, purchase orders, vendor invoices, capacity, PM copilot (D-067 to D-071).
- **Module `auditor`**: standalone QA and LQA of bilingual files on the work queue (D-064).
- **Module `strings`**: keys, branches, releases, OTA bundles, push/pull CLI (D-060 to D-062).
- **Module `community`**: reviewer apply, tests, task queue and cockpit, second review, pay, score, disputes, payouts.
- **Billing and payouts**: plans, subscriptions, entitlements (one writer, D-077), credits, overage, Paddle, Stripe (off), manual invoices, Payoneer, PayPal and bank-file rails, platform fee (D-072 to D-075). Mocks only.
- **Platform**: module gating (D-052), custom roles and team (D-053), audit log (D-054), OIDC SSO (D-055), one secrets helper and one invite flow (D-078).
- **Ops**: presigned uploads to local or S3 storage, queued email (D-051), PostHog and OpenTelemetry, worker heartbeat, `/healthz` with commit, Kamal configs, `release.yml` with attestation, `backup.yml` with the restore drill, Compose fallback, runbook.
- **Web**: Next.js 16 app for `/app`, `/reviewer`, `/admin`, public `/pricing`, `/checkout/paddle`, vendor workbench; httpOnly cookie proxy (D-036); English catalog with database locales (D-046).

## Mapping from the earlier plans

The 2026-10-09 plan (D-048) had P00 to P08. Older notes that use it:

| 2026-10-09 plan | Now |
| --- | --- |
| P00 install and verify | P00 (now also J-10 to J-18) |
| P01 measurement | P01 (plus the EU route) |
| P02 staging deploy on one Hetzner box with Compose | P02 production-grade staging on the Kamal stack |
| P03 money and legal (provider undecided) | P03 (Paddle, Payoneer, PayPal decided) |
| P04 self-serve launch | P04 |
| P05 integrations | P05 (plus Slack) |
| P06 Okapi formats | dropped from the numbered plan; ROADMAP backlog (D-090) |
| P07 enterprise | P07 |
| P08 white-label | P08 |
| none | P06 own models in production, P09 enterprise region and US cell |

Checkpoints INT-01 to INT-06 of the 2026-10-09 plan had no evidence; they are renumbered INT-01 to INT-11 in `ACCEPTANCE.md`. The plan before that (`docs/phases/phase-0..6.md`, ROADMAP P0 to P6) is mapped in D-048.
