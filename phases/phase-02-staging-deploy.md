# P02: Production-grade staging on the chosen stack

## Goal

Staging runs on exactly the stack production will use (D-080 to D-083): a Hetzner Cloud VM behind a Hetzner Load Balancer, deployed by Kamal 2 from attested GHCR images, Ubicloud Postgres with pgvector, Hetzner Object Storage with presigned 1 GB uploads, Cloudflare in front, Tailscale as the only SSH path, nightly encrypted backups to Backblaze B2 EU with a passing restore drill, PostHog EU and Better Stack wired. All 30 e2e steps (J-01 to J-18) pass against the public staging URL and `npm run verify:deployed` proves the running commit equals HEAD. Every resource is created by the agent through an API or CLI; the owner only creates accounts and pastes tokens.

## Already built (not re-done here)

`services/api/Dockerfile` (api and worker, `ARBITER_GIT_SHA` baked in, `/healthz` returns `commit`), `apps/web/Dockerfile` (`/api/health`), `deploy/kamal/` (services `arbiter` and `arbiter-web`, staging and production destinations, pre-deploy migration hook, `.kamal/secrets-common`), `.github/workflows/release.yml` (build, push to GHCR, attest, Kamal deploy over Tailscale, verify deployed commit; skips cleanly while secrets are missing), `.github/workflows/backup.yml` (nightly encrypted dump to B2, monthly restore drill with a JSON artifact), `storage.py` and `/v1/uploads` (presigned S3 uploads, D-051), `observability.py` (PostHog, OpenTelemetry, worker heartbeat), queued email with an SMTP mailer, the Compose fallback in `deploy/`. Long form: `docs/infrastructure.md`.

## Scope

1. **Accounts and GitHub plan check.** Human steps A to J done (the agent asks only for the ones it cannot do through an API). The agent reads the GitHub account plan (`gh api /users/SpawnJFK` and the repo settings) and checks the current GitHub documentation for what a private repository on that plan supports: environment secrets, required reviewers, artifact attestations. Outcome written as a decision entry: either a plan upgrade (human step K, declared below) or the fallbacks in `docs/infrastructure.md` section 5.
2. **Prices first.** Read current prices through the provider APIs and pages (`hcloud server-type list`, `hcloud load-balancer-type list`, Hetzner Object Storage price page, Ubicloud price page, B2 price page) and write the exact monthly figures into `hyperpower.json` `spend.planned` before creating anything. Stop if the total exceeds the ceiling below.
3. **Verify pgvector on Ubicloud first (INT-04).** From Ubicloud's documentation (Context7 if indexed, else the docs site, logged), confirm Postgres 16 with `vector` and `pg_trgm`, PITR, HA options and the SOC 2 report the owner cited. Then create the smallest staging database, run `CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;` and one vector query, and record the result. If it fails: delete the instance, write a superseding decision, and use the D-081 fallback order. Record which role creates extensions.
4. **Domain and Cloudflare.** The owner's domain (human step A) is a Cloudflare zone. Through the Cloudflare API: proxied records `app.staging` and `api.staging` to the load balancer, SSL mode Full (strict), a Cloudflare Origin CA certificate for the staging hosts, WAF managed rules on, a rate-limit rule for `/v1/auth/*` and the public forms. Write the domain into `hyperpower.json` `domain` and `shipped.staging`.
5. **Hetzner by `hcloud`.** In project `arbiter`: a private network, a Cloud Firewall (80 and 443 from the load balancer and the private network only; 22 open only until Tailscale is proven, then closed), one VM (Ubuntu 24.04, smallest type that fits, location chosen with the owner, cloud-init that installs Docker, creates the `deploy` user in the `docker` group, hardens SSH, enables `ufw`, installs Tailscale and joins with `--advertise-tags=tag:arbiter`, hostname `arbiter-stg-1`), and a load balancer (private-network target, service HTTPS 443 to 80, health check `/healthz` with host `api.staging.<domain>`). Check whether a Hetzner managed certificate works with a zone at Cloudflare; if not (expected), upload the Origin CA certificate. Correct `deploy/kamal/README.md` step 2 to what was proven.
6. **Object storage.** With the S3 credentials (human step B5) create bucket `arbiter-stg-<random>` through the S3 API, CORS (`https://app.staging.<domain>`, `PUT, GET, HEAD`, `Content-Type`, expose `ETag`, max age 3600) and a lifecycle rule aborting incomplete multipart uploads after one day. Decide the copy policy for customer files (versioning or nightly sync to B2) and record it.
7. **Secrets and the Kamal gaps.** Generate `ARBITER_JWT_SECRET`, `ARBITER_SECRETS_KEY` (Fernet) and `BACKUP_PASSPHRASE` locally under `E:/.artifacts/arbiter/secrets/` (gitignored, outside the repo), set every GitHub environment secret and variable with `gh secret set --env staging` and `gh variable set --env staging` reading from stdin or a file, never a literal on a command line. Close the gaps listed in `docs/infrastructure.md` section 5: add `ARBITER_SECRETS_KEY` (and the Bedrock and Vertex names if P01 configured them) to `deploy/kamal/config/deploy.yml` `env.secret`, `.kamal/secrets-common` and `release.yml`; add a startup check that refuses the dev default `ARBITER_JWT_SECRET` and `ARBITER_SECRETS_KEY` when `ARBITER_ENV` is `staging` or `prod`, with a test and a decision entry.
8. **Email.** Pick a transactional SMTP provider (EU data location preferred, no segment text in emails; decision entry with the rejected options), human step L for the account, then SPF, DKIM and DMARC records through the Cloudflare API, one password-reset email received by the owner.
9. **Kamal validated with real env.** Run Kamal from the official Kamal Docker image or WSL on the owner's machine (Kamal does not run natively on Windows; log which), connected to the tailnet: `kamal config -d staging` and `kamal config -c config/deploy.web.yml -d staging` print the resolved config without errors; first-time `kamal setup` boots kamal-proxy on the VM. Fix anything Kamal 2.7 rejects (Context7 or the Kamal docs, logged).
10. **Release workflow and attestation.** Push to `main`; `release.yml` builds both images, pushes them to GHCR, attests them, deploys staging over Tailscale and verifies the commit. Prove the attestation with `gh attestation verify oci://ghcr.io/spawnjfk/arbiter-api:<sha> --owner SpawnJFK` (INT-08), or record the plan-dependent fallback from item 1.
11. **Seed staging.** `create-admin` for the owner's operator account (he sets the password through the reset email), `seed-plans`, and the fictional demo org (`seed-demo`) used by the e2e. Never customer data on staging.
12. **Observability.** PostHog EU project key in the staging environment, privacy mode confirmed by inspecting one LLM event; Better Stack monitors for `https://api.staging.<domain>/healthz` and `https://app.staging.<domain>/api/health`, a heartbeat monitor whose URL becomes `ARBITER_HEARTBEAT_URL`, a staging status page (private). Prove one test exception arrives in PostHog and one alert fires (stop the worker briefly, the heartbeat alert arrives).
13. **Presigned 1 GB upload (INT-06).** Generate a 1 GB file of a supported format on `E:`, upload it through the browser flow against staging (Playwright, `lib/upload.ts` with the `s3` backend), confirm the bytes went browser to bucket (not through Cloudflare or the API), `complete` registers it with matching size and checksum, and record the time. If processing a file that size exceeds a limit, record the limit and add a decision with the supported maximum.
14. **Backups and restore drill (INT-07).** Fill the `backup` GitHub environment (B2 from human step G, a read-only Postgres role for `ARBITER_BACKUP_DATABASE_URL`, `BACKUP_SSH_HOST` if the database only accepts the VMs), set the B2 lifecycle rule (35 daily copies), dispatch `backup.yml` with `both`, keep `restore-drill.json` in `evidence/p02/`. Also restore once from Ubicloud PITR into a new instance, record the duration, delete it. Update `docs/runbook.md` with both durations. Decide whether the plaintext dump may pass through GitHub-hosted runners (it does today, before encryption) or whether dump and drill move to a self-hosted runner on the tailnet; decision entry, and `docs/subprocessors.md` follows it.
15. **e2e against staging (INT-05).** Make `scripts/verify-e2e.mjs` and `real-flow.mjs` work against a remote stack: the second reviewer that `e2e/ensure_reviewer.py` creates locally is created through an admin endpoint or `kamal app exec` on staging. Run all 30 steps with `BASE_URL` and `API_URL` set to staging; replayable record.
16. **Deployed commit.** Set `hyperpower.json` `shipped.staging` (`appUrl`, `apiUrl`, `server`, `deploy`), run `npm run verify:deployed`, append a replayable `cli` record.
17. **Docs.** `deploy/README.md`, `docs/infrastructure.md` and `memory-bank/` updated with what was proven; actual prices moved from `spend.planned` to `spend.items`.

## Human-only steps

**A. Domain and Cloudflare.**
1. Tell the agent which domain to use. If it must be bought first, that is a separate "apply" (registration is not in this phase's declared spend).
2. Open https://dash.cloudflare.com/sign-up and create the account (or sign in).
3. Click "Add a domain" (older UI: "Add a site"), type the domain, choose the Free plan, continue. Cloudflare shows two nameservers.
4. At the registrar, replace the domain's nameservers with those two. Back in Cloudflare click "Check nameservers". Success: the domain shows "Active" (can take up to a few hours).
5. Open https://dash.cloudflare.com/profile/api-tokens, "Create Token", "Create Custom Token", name `arbiter-agent`, permissions: Zone, DNS, Edit; Zone, Zone Settings, Edit; Zone, SSL and Certificates, Edit; Zone, Zone WAF, Edit; Zone resources: Include, Specific zone, your domain. "Continue to summary", "Create Token", copy it.
6. Paste it as `CLOUDFLARE_API_TOKEN=...`. Success: the agent lists the zone's DNS records.

**B. Hetzner Cloud.**
1. Open https://accounts.hetzner.com/signUp and create the account with a payment method (or sign in at https://console.hetzner.cloud).
2. Click "+ New project", name it `arbiter`.
3. Open the project, left menu "Security", tab "API tokens", "Generate API token", description `arbiter-agent`, permission "Read & Write", "Generate". Copy it and paste it as `HCLOUD_TOKEN=...`.
4. Success: the agent prints the server and load balancer types with current prices and the ones it proposes.
5. Object storage credentials: in the project, left menu "Object Storage", "Generate credentials" (or "Security", "S3 credentials"), description `arbiter-staging`, copy the access key and secret, paste as `S3_ACCESS_KEY=...` and `S3_SECRET_KEY=...`. The agent creates the bucket itself.

**C. Ubicloud.**
1. Open https://console.ubicloud.com and create the account (or sign in), add a payment method under Billing.
2. Create a project `arbiter` if one is not created for you.
3. In the project open the token page ("Tokens" or "Personal access tokens"; if the label differs, the agent reads the current Ubicloud docs and tells you the exact path), create a token named `arbiter-agent`, copy it, paste as `UBICLOUD_TOKEN=...`.
4. Success: the agent lists the Postgres locations and sizes available to the project.

**D. Tailscale.**
1. Open https://login.tailscale.com/start and sign up (a GitHub login is fine).
2. Open https://login.tailscale.com/admin/acls, replace the policy with the JSON the agent gives you (it defines `tag:ci` and `tag:arbiter`, and lets `tag:ci` reach `tag:arbiter` on port 22), click "Save".
3. Open https://login.tailscale.com/admin/settings/oauth, "Generate OAuth client", scope "Auth Keys: Write", tags `tag:ci` and `tag:arbiter`, "Generate client". Copy the client id and secret.
4. Paste as `TS_OAUTH_CLIENT_ID=...` and `TS_OAUTH_SECRET=...`. The agent mints the VM auth keys through the API and stores the client in the GitHub environments.
5. Install Tailscale on your Windows machine from https://tailscale.com/download/windows and sign in to the same tailnet, so the agent's local Kamal can reach the VM.
6. Success: the admin console Machines page shows `arbiter-stg-1` with tag `tag:arbiter`.

**E. GitHub (only if the agent asks).** The agent creates the `staging`, `production` and `backup` environments and every secret through `gh`. If `gh` is not logged in on this machine: run nothing yourself; the agent starts `gh auth login --web`, you open the URL it shows, enter the code, click "Authorize".

**F. Better Stack.**
1. Open https://betterstack.com/users/sign-up and create the account.
2. Open Uptime, left menu "Integrations" or Settings, "API tokens", create a token for the team, copy it, paste as `BETTERSTACK_API_TOKEN=...`. The agent creates the monitors, the heartbeat and the status page through the API.
3. Open your profile, add your phone number, confirm the SMS code (phone alerts are tested here, paid on-call seats are not part of this phase).
4. Success: the agent shows the monitors as "Up" and you receive one test alert.

**G. Backblaze B2 (EU region).**
1. Open https://www.backblaze.com/sign-up/cloud-storage. On the sign-up form open the region selector and choose "EU Central" before you click sign up. The region cannot be changed later.
2. Confirm the email. In the B2 web app open "Buckets", "Create a Bucket", name `arbiter-backups-<random letters>`, Files in Bucket "Private", Default Encryption "Enable", "Create a Bucket". Note the "Endpoint" shown on the bucket (for example `s3.eu-central-003.backblazeb2.com`).
3. Open "Application Keys", "Add a New Application Key", name `arbiter-backup`, "Allow access to Bucket(s)" = that bucket only, type "Read and Write", "Create New Key". Copy keyID and applicationKey (shown once).
4. Paste as `B2_KEY_ID=...`, `B2_APP_KEY=...`, `B2_BUCKET=...`, `B2_ENDPOINT=https://...`.
5. Success: the agent lists the empty bucket.

**H. PostHog EU.**
1. Open https://eu.posthog.com/signup (the EU cloud, not app.posthog.com) and create the account.
2. Create an organization and a project named `arbiter-staging`.
3. Open Project settings, copy the "Project API key" (starts with `phc_`), paste as `POSTHOG_KEY=...`.
4. Success: the agent shows one test event in the project's Activity view.

**I. Location choice.** Tell the agent which Hetzner location to use (it lists the ones where Ubicloud also runs Postgres, so app and database sit together).

**J. "apply" for P02** after the agent has written the read prices into `hyperpower.json`.

**K. GitHub plan upgrade (only if item 1 decides it).** Open https://github.com/settings/billing/plans, choose the plan the decision names, confirm with your payment method. Success: the agent re-reads the plan through `gh`.

**L. Email provider account (after the item 8 decision).** The agent gives the exact sign-up path for the chosen provider; you create the account and paste the SMTP credentials as `SMTP_HOST=...`, `SMTP_USERNAME=...`, `SMTP_PASSWORD=...`.

## Declared spend

"apply" for P02 authorises, as monthly recurring ceilings with the exact prices read in item 2 written into `hyperpower.json` before creation:
- Staging infrastructure combined (Hetzner VM, Hetzner Load Balancer, Hetzner Object Storage, Ubicloud smallest Postgres, Backblaze B2): up to **60 EUR per month** (**estimate**; Ubicloud starts at 19.54 USD per month per research, the rest is read from the providers).
- The one-off pgvector check instance in item 3 if it has to be created separately: up to **5 EUR**.
- A GitHub plan upgrade only if item 1's decision requires it: up to **25 EUR per month** (**estimate**, confirmed on the GitHub billing page first).
- Transactional email: the provider's free tier; anything paid needs a new "apply".
Not authorised: domain registration, Cloudflare paid plans, Better Stack responder seats, PostHog paid usage beyond free tiers, any production resource, a second VM.

## Acceptance

- INT-04: pgvector and pg_trgm proven on Ubicloud (or the fallback, with its superseding decision).
- INT-05: all 30 e2e steps (J-01 to J-18) pass against the public staging URL; `npm run verify:deployed` exit 0 for the deployed commit.
- INT-06: a 1 GB presigned upload on staging, bytes browser to bucket, size and checksum match.
- INT-07: `restore-drill.json` with `ok: true` from `backup.yml`, plus one PITR restore duration.
- INT-08: `gh attestation verify` passes for both images of the deployed SHA, or the recorded plan fallback.
- Commands: `npm run verify` exit 0, `npm run verify:e2e` against staging exit 0, `npm run verify:deployed` exit 0, `npm run hp -- verify` 0 broken.

## Exit gate

`npm run hp -- gate P02 --product` exits 0 and the P02 bead reads back closed.

## Out of scope

Live payments and payouts (P03). Production destination, public status page, paid alerting (P04). A US cell or AWS profile (P09). Kubernetes (D-080).
