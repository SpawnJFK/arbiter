# P02: Staging deploy on Hetzner

## Goal

Arbiter runs on one Hetzner server in the EU at a staging domain, deployed by Docker Compose behind Caddy exactly as `deploy/README.md` describes, deploys automatically from `main` after CI through a restricted SSH key, backs up nightly to encrypted off-site object storage, has passed one restore drill, and `npm run verify:deployed` proves the running commit equals HEAD. J-01 to J-03 pass against the public staging URL.

## Already built (not re-done here)

`services/api/Dockerfile` (API and worker), `apps/web/Dockerfile`, `deploy/docker-compose.yml` (CORS, seller country, VAT rate and web `API_URL` wired), `deploy/Caddyfile`, `deploy/backup.sh` (pg_dump, verify, storage tarball, sha256, rclone, prune), the Hetzner guide in `deploy/README.md`, the runbook in `docs/runbook.md`, and CI that builds both images and validates compose.

## Scope

1. **Domain.** The owner picks the domain (human step A). Staging lives at `app.staging.<domain>` and `api.staging.<domain>` (or the names the owner chooses). Write it into `hyperpower.json` `domain` and `shipped.staging`.
2. **Hetzner server through the API.** With the owner's Hetzner Cloud API token (human step B) the agent uses the `hcloud` CLI: read current prices for the candidate types (`hcloud server-type describe`), pick the smallest type that fits the P01 measurement load per `deploy/README.md` (CX32 or CPX31 class, 4 vCPU / 8 GB), write the exact monthly price into `hyperpower.json` `spend` before creating anything, then create the server (Ubuntu 24.04, `fsn1`, `nbg1` or `hel1`), the cloud firewall from `deploy/README.md` section 2 and the SSH key (generated on `E:`, private key never leaves the owner's machine and the GitHub secret).
3. **Server setup.** Docker, the `deploy` user in the `docker` group, SSH hardening, `ufw`, `/opt/arbiter` checkout, `deploy/.env` from `.env.example` with production values (new `ARBITER_JWT_SECRET` of at least 32 characters, provider keys from P01, `ARBITER_CORS_ORIGINS` for the staging web origin). Secrets go to the server only, over SSH, never through a command line the guard would see.
4. **DNS.** A records for the staging hosts to the server IP through the DNS provider's API when one is available (Cloudflare, Hetzner DNS); otherwise human step C with the exact records.
5. **Compose up.** `docker compose up -d` with migrations on start, Caddy obtaining TLS, `python -m arbiter.cli create-admin` for the owner's operator account (he sets the password through the app).
6. **Deployed commit.** `/healthz` returns `commit` from an `ARBITER_GIT_COMMIT` build argument (API Dockerfile and compose), with a test. `npm run verify:deployed` reads `hyperpower.json` `shipped.staging.apiUrl` and compares with HEAD. Append a replayable `cli` record.
7. **Deploy path.** `.github/workflows/deploy.yml`: on push to `main`, after the `ci` workflow succeeds, SSH with a key whose `authorized_keys` entry has `command="/opt/arbiter/deploy/deploy.sh",no-pty,no-port-forwarding,no-agent-forwarding`. `deploy.sh` (new, in `deploy/`): `git fetch`, check out the exact commit from CI, run `backup.sh`, `docker compose build --build-arg ARBITER_GIT_COMMIT=<sha>`, `up -d`, wait for `/healthz`. The agent sets the GitHub secrets with `gh secret set`. Prove: a push to `main` deploys and `verify:deployed` passes for that commit.
8. **Backups.** EU object storage bucket (Hetzner Object Storage, human step D for the keys), an encrypted rclone remote (`crypt` over `s3`), `backup.sh` in root cron at 02:30, one manual run, `rclone ls` shows the objects.
9. **Restore drill.** Per `deploy/README.md` section 9 into `arbiter_restore`, row counts compared with production, duration recorded in `docs/runbook.md` and in `evidence/p02/restore-drill.json` (INT-05).
10. **Error tracking and uptime.** Pick an EU-hosted error tracker and an uptime check on free tiers (decision entry with the rejected options; no new subprocessor that sees segment text). Wire API and web; prove one test error arrives and one uptime alert fires.
11. **e2e against staging.** Make `scripts/verify-e2e.mjs` and `real-flow.mjs` runnable against a remote stack: the second reviewer that `e2e/ensure_reviewer.py` creates locally is created through `docker compose exec` on the server (or an admin endpoint if one exists). Run J-01 to J-03 with `BASE_URL` and `API_URL` set to staging (INT-04), replayable record.

## Human-only steps

**A. Domain.** Tell the agent which domain to use. If it must be bought first, that is a separate "apply" (registration is not in this phase's declared spend). If the domain's DNS is at a provider with an API (Cloudflare, Hetzner DNS), also create an API token scoped to that zone (step C explains Cloudflare) so the agent can write records itself.

**B. Hetzner Cloud API token.**
1. Open https://console.hetzner.cloud and sign in (create the account first if needed: https://accounts.hetzner.com/signUp, with payment method).
2. Create a project named `arbiter` ("+ New project").
3. Open the project, left menu "Security", tab "API tokens", "Generate API token", description `arbiter-agent`, permission "Read & Write", click "Generate".
4. Copy the token and paste it into the Cursor chat as `HCLOUD_TOKEN=...`. The agent stores it in a gitignored env file only.
5. Success looks like: the agent prints the list of server types with current prices and the one it proposes.

**C. DNS (only if the agent cannot write records through an API).** Cloudflare token: https://dash.cloudflare.com/profile/api-tokens, "Create Token", template "Edit zone DNS", Zone Resources "Include, Specific zone, <your domain>", "Continue to summary", "Create Token", paste as `CLOUDFLARE_API_TOKEN=...`. Without an API: the agent gives the exact A records (name, type, value, TTL) to enter at the registrar.

**D. Object storage keys.** Hetzner Console, project `arbiter`, "Object Storage", "Create Bucket" (location same as the server, name `arbiter-backups-<random>`, private). Then "Security", "S3 credentials", "Generate credentials", copy the access key and secret, paste them into the chat as `S3_ACCESS_KEY=...` and `S3_SECRET_KEY=...`.

## Declared spend

One Hetzner server of the CX32 or CPX31 class and Hetzner Object Storage for backups. The agent reads the current prices from the Hetzner API, writes them into `hyperpower.json` `spend` and the activeContext report before creating anything; "apply" for P02 authorises up to 25 EUR per month combined. Not authorised: domain registration, any paid error-tracking or monitoring plan, a second server.

## Acceptance

- INT-04: J-01 to J-03 pass against the public staging URL; `npm run verify:deployed` exit 0 for the deployed commit. CI build provenance (attested tier) is declared for later; core 1.0.0 cannot write attested records, so this phase uses replayable records.
- INT-05: one restore drill logged with row counts and duration.
- Commands: `npm run verify` exit 0, `npm run verify:deployed` exit 0, `npm run hp -- verify` 0 broken.

## Exit gate

`npm run hp -- gate P02 --product` exits 0 and the P02 bead reads back closed.

## Out of scope

Real customer traffic, payments and payouts (P03). Production domain and launch (P04). Kubernetes or a second host (D-013).
