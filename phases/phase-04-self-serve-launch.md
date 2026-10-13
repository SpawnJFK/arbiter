# P04: Self-serve launch

## Goal

Production runs as the second Kamal destination on two or more Hetzner VMs behind a load balancer with Ubicloud Postgres, deploys only through approved tags, has a public status page and phone alerts, carries the live plan catalog and live Paddle keys, and the first paying customers can sign up, upload, get a quote, pick a tier, pay and download the result without the operator, in at least 3 calibrated target languages, with reviewer capacity that does not limit the tiers sold.

## Already built (not re-done here)

`deploy/kamal/config/deploy.production.yml` and `deploy.web.production.yml` (hosts `arbiter-prd-1`, `arbiter-prd-2`, api and worker on both), the `deploy-production` job in `release.yml` (runs on a `v*` tag inside the GitHub `production` environment), everything P02 proved on staging and everything P03 proved for money and legal.

## Scope

1. **Production infrastructure by API.** Read prices first and write them into `hyperpower.json`. Two VMs (dedicated vCPU once LLM traffic and file conversion overlap, per the P02 measurements), a load balancer, firewall and private network, Tailscale tags, Ubicloud Postgres on its HA option if offered (confirmed in P02), bucket `arbiter-prd-*` with CORS and lifecycle, Cloudflare records `app` and `api` proxied with Full (strict), WAF and rate limits copied from staging. Region: the same as staging.
2. **Manual approval deploys.** Production deploys only from a `v*` tag. If the GitHub plan supports required reviewers on the `production` environment, the owner is the required reviewer; otherwise the P02 fallback (tag pushes restricted to the owner, deploy job refuses other actors) is in place and tested. One release deployed, `npm run verify:deployed` against production, attestation verified (or the recorded fallback).
3. **Backups on production.** The `backup` environment points at production (read-only role), the drill passes on a production dump, PITR window confirmed; durations in `docs/runbook.md`.
4. **Status and alerts.** Better Stack monitors and heartbeat for production, a public status page on `status.<domain>`, one responder seat with phone alerts on the owner's phone, PostHog EU production project with privacy mode. Log retention set.
5. **Seed production.** `seed-plans` with the live catalog mapped to live Paddle prices, the owner's operator account, no demo data. Platform fee default confirmed by the owner.
6. **Calibrate 3 target languages** with the P01 method (reference set, human MQM labels, sweep, thresholds, report in `docs/measurements/`). Target languages chosen by the owner from demand; a decision entry per language.
7. **Reviewer capacity.** Recruit and qualify reviewers for each launch pair through the existing apply and test flow; wait-time monitoring per pair against the `hybrid` target, with an alert. New pairs are sold only when the target holds.
8. **Journeys on production.** J-01 to J-18 against production with replayable records, using a fictional test org that is deleted afterwards (J-08's second reviewer and J-09's locale import use the production admin flows, not fixtures; J-15 uses a live checkout refunded at once, or the owner's own card under the declared spend).
9. **First customers.** Public sign-up open. The first customers come from the owner's own outreach; no customer names in the repo. Support and incident steps in `docs/runbook.md` updated.

## Human-only steps

1. **Production domain DNS.** Same Cloudflare zone as staging; nothing to do unless production uses a different domain (then repeat P02 step A for it).
2. **Better Stack responder seat.** Open Better Stack, Settings, "Billing", add a payment method, add one responder seat for yourself; confirm your phone number on the on-call schedule the agent creates. Success: a test call or SMS arrives.
3. **Status page domain.** Nothing to do: the agent adds the `status` CNAME through Cloudflare.
4. **Reviewer contracts** under the reviewed contractor terms (P03): reviewers accept them in the app; you approve qualified reviewers in `/admin`.
5. **Launch "apply"**, after the agent has written the read production prices into `hyperpower.json`.
6. **Production deploy approvals**: when GitHub asks for a review on the `production` environment, open the link in the email or the Actions run, click "Review deployments", tick `production`, "Approve and deploy".

## Declared spend

"apply" for P04 authorises, monthly recurring, with exact prices read first and written into `hyperpower.json`:
- Production infrastructure combined (2 VMs, load balancer, object storage, Ubicloud HA Postgres, B2 backups): up to **200 EUR per month** (**estimate**, confirmed by the provider APIs before creation).
- Better Stack: one responder seat, 34 USD per month or 29 USD yearly (research, [Better Stack](https://betterstack.com/pricing.md)).
- Provider usage for calibration under a budget the owner names with "apply" (suggested 100 EUR for three languages).
- Paddle fees on real sales (5 % + 50 cents, research).
Not authorised: a third VM, AWS, paid PostHog tiers beyond free usage, a US cell.

## Acceptance

- Three languages calibrated with reports and decision entries.
- J-01 to J-18 PROVEN on production.
- Public status page live; one alert proven by phone.
- Commands: `npm run verify`, `npm run verify:deployed` (production URL), `npm run hp -- verify` all clean.

## Exit gate

`npm run hp -- gate P04 --product` exits 0 and the P04 bead reads back closed.

## Out of scope

Connectors (P05), own models for customers (P06), certifications and SAML (P07), white-label (P08), other regions (P09).
