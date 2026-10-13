# Subprocessors (draft)

Status: **draft, pending legal review before public launch** (D-086, P03). Not published. Lists every third party that may process customer personal data or customer content for Arbiter once the planned stack is live (D-079 to D-085). Nothing is deployed today, so no vendor below processes customer data yet.

Rules for this list:
- A vendor appears here before it receives customer data, and the public version is updated before the change takes effect.
- "Location" is where the vendor processes the data for Arbiter's configuration. Where it is not yet confirmed from the vendor's DPA or console it says "to confirm", and P02 or P03 fills it in. Nothing here is a legal statement until reviewed.
- AI and MT providers receive segment text only for organizations that enabled AI processing (`ai_subprocessors_opt_in`), and organizations with the `eu_processing` add-on reach only engines that process in the EU (D-057, D-079).
- No vendor receives customer content for its own training through Arbiter; provider settings that allow it stay off (confirmed per provider in P03).

## Infrastructure

| Vendor | Purpose | Data | Location |
| --- | --- | --- | --- |
| Hetzner Online | Compute (VMs, load balancer), object storage for customer files | All customer content and account data processed by the app; uploaded files | The Hetzner location chosen in P02 (Hetzner's ISO 27001:2022 certificate names its German datacenter parks, research) |
| Ubicloud | Managed PostgreSQL database | All structured customer data: accounts, segments, TM, glossaries, provenance, billing records | Same region as the VMs, chosen in P02 (Ubicloud runs in Germany and the US, research) |
| Cloudflare | DNS, WAF, rate limiting, TLS proxy in front of the app | Request metadata (IP addresses, headers) and request and response bodies in transit, including segment text sent through the web app and API; file bytes do not pass (presigned uploads go straight to object storage) | Global edge network; to confirm in the DPA review |
| Backblaze | Off-provider backups | Encrypted database dumps (encrypted before upload with a key Backblaze does not hold) | EU region chosen at account creation (P02) |
| GitHub (Microsoft) | Source code, CI, container registry, the backup and restore-drill jobs | No customer data in code or images; the nightly backup job streams the database dump through a GitHub-hosted runner before encrypting it, and the monthly drill decrypts and restores a dump on a runner | Runner location to confirm; P02 decides whether backups move to a runner on the tailnet instead |
| Tailscale | Private network for SSH and deploys | Device and operator identities, connection metadata; no customer content | To confirm |
| Transactional email provider (to be chosen in P02) | Account emails: invites, password reset, job and payout notices, vendor offers | Recipient email addresses, names, job names and links; no segment text | To confirm with the choice |

## Observability

| Vendor | Purpose | Data | Location |
| --- | --- | --- | --- |
| PostHog (Cloud EU) | Error tracking, logs, product and LLM usage analytics | Pseudonymous user and org ids, error stack traces, request metadata, LLM call metadata (model, tokens, cost) with privacy mode on; never segment text, prompts or completions | EU (Frankfurt), research ([PostHog GDPR](https://posthog.com/docs/privacy/gdpr-compliance)) |
| Better Stack | Uptime checks, worker heartbeat, status page, on-call alerts | Public endpoint responses, heartbeat pings, the operator's phone number; no customer content | To confirm |

## AI and machine translation (only for organizations that enabled AI processing)

| Vendor | Purpose | Data | Location |
| --- | --- | --- | --- |
| Anthropic | Default LLM for translation, QE judge, senate, AI editor, setup assistant | Segment text with minimal context, glossary terms | Global inference geography (Anthropic's API offers "global" or "us", not EU, as of October 2026, research) |
| Amazon Web Services (Bedrock) | Claude for organizations with EU processing | Segment text with minimal context | EU geographic inference profile, EU regions only (research) |
| Google Cloud (Vertex AI) | Claude for organizations with EU processing | Segment text with minimal context | Vertex "eu" multi-region (research) |
| DeepL | Machine translation | Segment text | EU (D-057); to confirm in the DPA review |
| Google Cloud (Cloud Translation) | Machine translation, if configured | Segment text | To confirm |
| OpenAI | LLM and embeddings, if configured | Segment text (embeddings: source text of TM entries) | To confirm |
| Together AI, Fireworks AI | Fine-tuning and serving of per-client models, only for organizations that gave training consent (D-059) | Human-approved segment pairs of that organization only | To confirm; EU organizations use only the manual provider and EU-declared models |
| Customer-supplied providers (BYOK, OpenAI-compatible endpoints) | Engines the customer configures with its own keys | Segment text | Chosen by the customer; Arbiter records the declared region per call |

## Payments and payouts

| Vendor | Purpose | Data | Location |
| --- | --- | --- | --- |
| Paddle | Merchant of record: checkout, subscriptions, tax, invoices, refunds | Billing contact, company and tax details, payment data (held by Paddle, not by Arbiter) | To confirm |
| Payoneer | Reviewer payouts | Payee identity and payout details (held by Payoneer), payout amounts | To confirm |
| PayPal | Reviewer payouts | Payee email, payout amounts | To confirm |
| Stripe | Not active. Listed here only when a Stripe rail is switched on (D-084) | | |

## Open items for the legal review

- Transfer mechanism per vendor outside the EU: DPA plus EU-US Data Privacy Framework certification or Standard Contractual Clauses (D-079).
- Whether Cloudflare's TLS termination of API traffic needs specific DPA language.
- Whether the GitHub-hosted backup runner is acceptable or the dump must run on Arbiter's own host.
- Reviewer data (identity, tax documents, payouts) and the questions in P03 item 7 (W-8BEN or W-9, DAC7).
