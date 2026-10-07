# Roadmap

Status 2026-10-07: **P0 in progress**. Foundation is built (and many P1/P2 product features ahead of phase); no measurement on a real pair yet, nothing deployed. Details: `memory-bank/progress.md`.

Phases run in order. A phase is done when every exit criterion is met and written down in `memory-bank/progress.md`. Checklists per phase: `docs/phases/`.

| Phase | Goal | Exit criteria (all required) |
|---|---|---|
| **P0** Measurement harness | Prove the QE + senate decision on one real language pair before selling anything. English to Serbian is the first measurement pair: a test instrument, not the target market. | Full pipeline runs end to end on real documents for the pair with real providers. A human-labelled reference set exists for the pair. Escaped-error rate on auto-approved segments is measured with a confidence interval and is at or below `escaped_error_target`, or the gap is understood and documented. Auto-approve rate and cost per word are measured. Evidence pack (JSON + PDF) generated for every job. Restore drill done once. |
| **P1** MVP self-serve | A paying customer can sign up, upload, get a quote, pick a tier and download the result without the operator. | Register, quote, project, delivery, invoice work in production for the supported formats. Tiers and regulated-vertical rules enforced in the API. At least 3 target languages calibrated with the P0 method. Webhooks, API keys, usage and invoices live. Payments integrated. Legal review before public launch completed (terms, DPA, subprocessor list, privacy policy). Error tracking and uptime monitoring on. |
| **P2** Reviewer community at scale | Human review capacity no longer limits the tiers sold. | Reviewer onboarding, qualification tests, task routing, per-decision pay, disputes and payouts run without manual steps. Reviewer quality scores and levels drive routing. Payout runs reconcile with the ledger to the cent. Median wait for a review task within the target agreed for `hybrid` in the supported pairs. Reviewer contractor terms reviewed. |
| **P3** Integrations | Content flows in and out without manual upload. | GitHub connector (repo files to jobs, PR back). Figma connector. At least one headless CMS connector. Connectors use the public API and webhooks only. Each connector has an end-to-end test against a sandbox. |
| **P4** More formats via Okapi | Long-tail file formats. | Okapi Framework sidecar running behind `FormatHandler`. IDML, DITA and at least three more formats round-trip in tests. Python handlers and Okapi produce the same tagged text for overlapping formats or the difference is documented. |
| **P5** Enterprise | Sell to companies with procurement checklists. | SAML/OIDC SSO, SCIM or equivalent user provisioning, audit log export, data retention controls per org. SOC 2 Type I report (Type II window started). Penetration test done and findings closed. |
| **P6** White-label for agencies | Language service providers run their own branded instance on Arbiter. | Custom domain and branding per tenant, sub-tenants (agency to its clients), agency-owned reviewer pools, agency pricing and invoicing to their clients, data isolation verified by test. |

Rules:
- No phase claims a metric that was not measured. No customer names or revenue in this file.
- Anything moved between phases is a `docs/decisions.md` entry.
