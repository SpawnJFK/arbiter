# P09: Enterprise region and US cell

## Goal

Two triggered expansions, each started only by its trigger. **Enterprise region:** when a contract requires a hyperscaler or a specific region, Arbiter runs as a separate cell on AWS (the "AWS profile"): same images, a Kamal or managed-container destination, managed Postgres with pgvector, S3, and Claude through Bedrock in the same region. **US cell:** when US demand appears, a second independent deployment in a US region, with the region chosen at signup and never migrated, following the pattern of comparable products (research: Phrase, Linear, PostHog run separate regional deployments; accounts cannot be moved, see `docs/infrastructure.md` section 9).

## Already built (not re-done here)

Region-aware engines and the EU filter (D-057), Bedrock and Vertex clients, attested images, Kamal destinations as files, backups and drills as workflows, observability through OpenTelemetry (vendor-neutral).

## Scope

1. **Trigger recorded.** A signed contract (enterprise region) or a demand signal the owner names (US cell), as a decision entry. Without it the phase does not start.
2. **Region model.** An immutable `region` on the org chosen at signup, region-specific hostnames (for example `app.<domain>` and `us.app.<domain>`), the signup and login routing, and a migration for existing orgs (all in the first cell). Decision entry: the reviewer marketplace as one global service or a pool per cell (research leans per-cell for residency).
3. **AWS profile** (enterprise region): infrastructure as code for one cell (VPC, compute for the `api`, `worker` and `web` roles, RDS or Aurora Postgres with pgvector verified first, S3 with presigned uploads, Bedrock model access in the region), secrets in the provider's secret store, the same release workflow with a new destination. Price read from the AWS pricing API before creation.
4. **US cell**: either Hetzner US locations with Ubicloud US (research: Ubicloud runs in Germany and the US) or the AWS profile in a US region; decision entry weighing cost against questionnaire strength (Hetzner's named ISO scope covers the German parks only, research). Claude through Anthropic's API with US geography or Bedrock US.
5. **Billing stays global** (Paddle holds no customer content); per-cell backups, drills, monitoring and status page components.
6. **Subprocessor list and DPA** updated per cell; trust page shows the cells.
7. **Journeys** J-01 to J-18 replayed in the new cell; a new journey proves a US-region org never touches the EU cell's data and vice versa.

## Human-only steps

AWS account and organization setup with billing alerts (exact click paths at phase start), Bedrock model access in the chosen region, the contract or demand decision, DNS for the new hostnames (through the Cloudflare API, nothing to click).

## Declared spend

Declared with amounts at phase start from the provider pricing APIs; the AWS profile is expected to cost several times the Hetzner cell (owner's estimate of 3 to 5 times, D-080), which is why it is triggered by a contract that covers it.

## Acceptance

The new cell's journeys PROVEN with replayable records, cross-cell isolation journey PROVEN, backups and drill passing in the new cell; `npm run verify` and `npm run hp -- verify` clean.

## Exit gate

`npm run hp -- gate P09 --product` exits 0 and the P09 bead reads back closed.

## Out of scope

Moving an existing org between cells (not offered, research pattern). Kubernetes unless the AWS profile decision proves a managed container service cannot serve.
