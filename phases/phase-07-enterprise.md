# P07: Enterprise

## Goal

Arbiter can be sold to companies with procurement checklists: SAML next to the existing OIDC SSO, SCIM provisioning, audit log export and retention controls proven, ISO 27001 or SOC 2 Type I (chosen by the first enterprise buyer's region) with the Type II window started, a closed penetration test, and the BYOK and EU processing add-ons sold under contract with their DPA annex.

## Already built (not re-done here)

OIDC SSO with PKCE, domains proven by DNS TXT, just-in-time provisioning and enforced SSO (D-055, tested with a fake IdP), custom roles and team management (D-053), append-only audit log with export (D-054), per-org `data_retention_days`, BYOK engine keys encrypted at rest (D-056), the EU processing route with no silent fallback (D-057), evidence packs with the processing block.

## Scope

1. **Trigger.** This phase starts when a named enterprise deal asks for it (D-086); the buyer's region picks the first certificate (ISO 27001 leans EU, SOC 2 leans US, research).
2. **SSO.** Prove OIDC against at least two real IdPs (test tenants), add SAML 2.0 per org (decision entry for the library, Context7 first), enforced SSO tested.
3. **SCIM 2.0** user and group provisioning, tested against an IdP's SCIM client.
4. **Audit and retention.** Audit export per org proven on production, retention and deletion controls with deletion evidence in the ledger.
5. **Certification.** Compliance platform and auditor chosen (decision entry with the rejected options and the quotes); controls mapped to what exists (provenance, evidence ledger, org scoping, regulated-vertical blocks, Tailscale-only SSH, backups and drills). Type I or ISO 27001 audit; Type II window started after it.
6. **Penetration test** by an external vendor; every finding closed or accepted with a decision entry.
7. **Security questionnaire pack** and trust page update (certificate, pen-test summary, subprocessors).
8. **Add-ons under contract.** BYOK and EU processing priced in the enterprise plan, a DPA annex describing the EU route (D-079) and the evidence pack as proof.
9. New journeys for SAML login, SCIM provisioning and audit export (numbered at phase start).

## Human-only steps

IdP test tenants (for example Microsoft Entra ID and Okta developer tenants; exact click paths at phase start), choosing and contracting the compliance platform, the auditor and the pen-test vendor, signing the enterprise contract.

## Declared spend

Declared with amounts at phase start; "apply" covers only what is declared then. Research ranges for planning only (compliance vendors, numbers do not cleanly sum): compliance platform 7,500 to 25,000 USD a year, SOC 2 Type II audit 12,000 to 50,000 USD, pen test 4,000 to 15,000 USD ([Strac](https://www.strac.io/blog/soc-2-cost)); specialist auditors cost a third to a fifth of the Big 4 ([Agency](https://blog.getagency.com/articles/soc-2-audit-cost-for-startups)). ISO 27001 cost at this company size was not sourced.

## Acceptance

New journeys PROVEN; certificate or report and pen-test closure dated in `evidence/p07/`; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P07 --product` exits 0 and the P07 bead reads back closed.

## Out of scope

White-label (P08). Other regions (P09). ISO/IEC 42001 (noted for later, D-086).
