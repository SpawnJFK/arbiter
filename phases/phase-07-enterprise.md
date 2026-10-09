# P07: Enterprise

## Goal

Arbiter can be sold to companies with procurement checklists: SSO, user provisioning, audit log export, retention controls, a SOC 2 Type I report with the Type II window started, and a closed penetration test.

## Scope

1. SAML and OIDC SSO per org.
2. User provisioning (SCIM or equivalent).
3. Audit log export (provenance and admin actions) per org.
4. Per-org retention and deletion controls with proof (deletion evidence in the ledger).
5. SOC 2 Type I report; Type II observation window started.
6. External penetration test, every finding closed or accepted with a decision entry.
7. Security questionnaire pack.
8. New journeys for SSO login, provisioning and audit export (numbered at phase start).

## Human-only steps

Identity-provider test tenants, choosing and contracting the auditor and the pen-test vendor. Exact steps at phase start.

## Declared spend

Auditor and pen-test fees, declared with amounts at phase start; "apply" covers only what is declared then.

## Acceptance

New journeys PROVEN; report and pen-test closure dated in `evidence/p07/`; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P07 --product` exits 0 and the P07 bead reads back closed.

## Out of scope

White-label (P08).
