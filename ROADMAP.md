# Roadmap

Status 2026-10-13: **P00 next** (install and verify on the owner's Windows machine). All seven product modules, billing and payout rails, platform features and the deploy configs are built and tested locally far ahead of the plan, at the owner's request (D-089); no measurement on a real pair yet, no account created, nothing deployed. Details: `memory-bank/progress.md`. Working plan with scope, human steps and declared spend per phase: `phases/` (order table in `phases/README.md`). Infrastructure: `docs/infrastructure.md`.

Phases run in order. A phase is done when its gate passes: `npm run hp -- gate P0x --product` re-verifies the phase's evidence records, runs `npm run verify` and closes the phase bead with a read-back (`HYPERPOWER.md`). The plan was rewritten on 2026-10-13 (D-090); `phases/README.md` maps the earlier numbers.

| Phase | Goal | Exit criteria (all required) |
|---|---|---|
| **P00** Install and verify | The cloud-built system runs on the owner's Windows machine with every check and guard proven. | `npm run verify` and the 30-step `npm run verify:e2e` green on Windows; J-01 to J-18 replayed into the evidence ledger; tools installed from the registry with SHA256; git and Cursor hooks proven through real invocations; Context7 re-check of the libraries and provider APIs used; Beads holds one bead per phase (P00 to P09); doctor clean. |
| **P01** Measurement harness | Prove the QE + senate decision on one real language pair before selling anything. English to Serbian is the first measurement pair: a test instrument, not the target market. | Real provider keys with caps; human-labelled reference set; escaped-error rate on auto-approved segments measured with a confidence interval and at or below `escaped_error_target`, or the gap documented; auto-approve rate and cost per word measured; evidence pack for every job; EU route measured if Bedrock or Vertex access exists. |
| **P02** Production-grade staging | Staging runs on exactly the production stack. | Hetzner VM behind a load balancer, Kamal deploys of attested GHCR images over Tailscale, Ubicloud Postgres with pgvector proven, Cloudflare Full (strict), presigned 1 GB upload, nightly encrypted B2 backups and a passing restore drill, PostHog EU and Better Stack wired, all 30 e2e steps against the public URL, deployed commit equals HEAD. |
| **P03** Money and legal | Money moves for real in both directions and the documents a launch needs are reviewed. | Paddle sandbox checkout to entitlement proven and live account with domain approval; Payoneer or PayPal sandbox payout and one real small payout; reconciliation to the cent; DPA, subprocessor list, terms, privacy policy, contractor terms and trust page with legal review before public launch; tax questions answered; entity question for Stripe put to the owner; security pass done. |
| **P04** Self-serve launch | Paying customers sign up, buy and receive work without the operator. | Production as the second Kamal destination on 2+ VMs, approved tag deploys, public status page and phone alerts, live plan catalog, at least 3 calibrated target languages, reviewer capacity within the `hybrid` wait target, J-01 to J-18 on production, first customers. |
| **P05** Integrations | Content flows in and out without manual upload. | GitHub, Figma, at least one headless CMS and Slack connectors on the public API and webhooks only, each with a sandbox journey. |
| **P06** Own models in production | A per-client fine-tune earns its place on the scoreboard. | First LoRA training on consented, human-approved segments of a real customer, held-out evaluation, scoreboard comparison, activation only when better; consent withdrawal and deletion proven. |
| **P07** Enterprise | Sell to companies with procurement checklists. | SAML next to OIDC, SCIM, audit export and retention proven, ISO 27001 or SOC 2 Type I (by the buyer's region) with the Type II window started, pen test closed, BYOK and EU processing sold under contract. |
| **P08** White-label for agencies | Language service providers run their own branded instance on Arbiter. | Custom domain and branding per tenant, sub-tenants, agency-owned vendor and reviewer pools, agency pricing and invoicing, isolation verified by test. |
| **P09** Enterprise region and US cell | Serve contracts that need a hyperscaler or another region. | Triggered only by a contract (AWS profile) or US demand (US cell); region chosen at signup and never migrated; journeys and cross-cell isolation proven in the new cell. |

## Backlog (not scheduled)

- Okapi Framework sidecar for formats the Python handlers cannot serve (was P06 in the 2026-10-09 plan; dropped from the numbered plan by D-090 because the handlers now cover IDML, DITA, XML with ITS, subtitles and resource files). Triggered by a customer format request.
- COMET as an extra quality signal (D-005).
- ISO/IEC 42001 for AI management (D-086).
- Lago or another usage engine if the in-house ledger becomes a burden (D-084).
- Langfuse for prompt management and judge eval datasets (D-083).

Rules:
- No phase claims a metric that was not measured. No customer names or revenue in this file.
- Anything moved between phases is a `docs/decisions.md` entry.
