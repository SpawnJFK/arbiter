# P08: White-label for agencies

## Goal

Language service providers run their own branded instance on Arbiter: custom domain, branding, their clients as sub-tenants, their own reviewer pools next to the marketplace, their own pricing and invoicing, with data isolation verified by test.

## Scope

1. Custom domain and TLS per tenant (Caddy on-demand TLS with an allow-list).
2. Branding: logo, colours within the token system, emails, evidence pack template.
3. Sub-tenants: an agency and its clients, with isolation across agency boundaries.
4. Agency-owned reviewer pools alongside the marketplace.
5. Agency pricing and invoicing to its own clients (builds on the Agency OS price lists and P03 billing).
6. Isolation tests across agency boundaries, as new journeys (numbered at phase start).

## Human-only steps

A pilot agency's domain and branding assets. No agency is named in the repo; fixtures stay fictional.

## Declared spend

None expected.

## Acceptance

Isolation journeys PROVEN; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P08 --product` exits 0 and the P08 bead reads back closed.

## Out of scope

Anything not listed above needs a new phase.
