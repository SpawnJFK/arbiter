# P1 MVP self-serve

Status 2026-10-07: product features largely built ahead of phase (not yet in production). Also built: Agency OS (CRM, price lists, workflow templates, dashboards, AI setup assistant), web E2E test.

- [x] Web: sign-up, org settings (tier default, no_reviewer_policy, regulated, vertical, AI subprocessor opt-in, retention)
- [x] Upload, quote with TM analysis and per-tier price/ETA/availability
- [x] Project creation, job progress, segment view, client edits, approve
- [x] Download, XLIFF export, evidence pack download
- [x] PM exceptions screen (only what needs a human)
- [x] Glossary UI + CSV/TBX import/export; TMX import/export with rights confirmation
- [x] API keys, webhooks with signing, retries and auto-disable
- [x] Usage metering and invoices (Decimal, currency per org)
- [ ] Payment provider integration
- [ ] Compose/config sync (CORS, seller country, VAT rate, web API_URL) and one web Dockerfile
- [x] Regulated-vertical rules enforced in API (no auto / ai_review)
- [ ] Calibrate at least 3 target languages with the P0 method
- [ ] Error tracking, uptime monitoring, log retention
- [ ] Legal review before public launch: terms, DPA, subprocessor list, privacy policy
- [ ] Tax review of the invoice VAT rule (D-029)
- [ ] Security pass: tenancy tests, rate limits, upload limits, dependency audit

Exit criteria: ROADMAP.md P1.
