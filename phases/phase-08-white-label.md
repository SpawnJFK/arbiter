# P08: White-label for agencies

## Goal

Language service providers run their own branded instance on Arbiter: custom domain, branding, their clients as sub-tenants, their own vendors and reviewer pools next to the marketplace, their own pricing and invoicing, with data isolation verified by test.

## Already built (not re-done here)

The Agency OS (CRM, price lists, workflow templates, dashboards, setup assistant), own vendors with assignments, purchase orders and vendor invoices, capacity planning, the PM copilot (D-067 to D-071), the vendor workbench without login, modules and plans per org, custom roles.

## Scope

1. **Custom domains and TLS** per tenant on the current edge (Cloudflare in front of the load balancer). Decision entry at phase start comparing Cloudflare custom hostnames for SaaS, certificates on the load balancer, and kamal-proxy host routing, with the domain allow-list and verification flow.
2. **Branding**: logo, colours within the token system (`docs/DESIGN.md`), email templates, evidence pack template.
3. **Sub-tenants**: an agency and its clients, with isolation across agency boundaries (404 across tenants, as everywhere).
4. **Agency-owned reviewer pools** alongside the marketplace; agencies pay their own vendors (D-078, D-085).
5. **Agency pricing and invoicing** to its own clients (builds on price lists and the manual invoice provider; the agency is the seller of record, decision entry).
6. **Isolation tests** across agency boundaries, as new journeys (numbered at phase start).

## Human-only steps

A pilot agency's domain DNS (a CNAME the agency adds at its own DNS provider; exact record given by the agent) and branding assets. No agency is named in the repo; fixtures stay fictional.

## Declared spend

None expected. If the custom-domain decision needs a paid Cloudflare feature, it is declared with its price at phase start.

## Acceptance

Isolation journeys PROVEN; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P08 --product` exits 0 and the P08 bead reads back closed.

## Out of scope

Other regions (P09). Anything not listed above needs a new phase.
