# Kamal deploy (staging and production)

Target architecture (owner approved): Hetzner Cloud VMs behind a Hetzner Load Balancer,
containers deployed with Kamal 2 from images in GHCR, managed Postgres from Ubicloud on
Hetzner, Hetzner Object Storage for customer files, Backblaze B2 EU for backups,
Cloudflare in front, Tailscale for SSH. The single-box compose stack in `deploy/` stays as
the local and fallback path.

```
Browser -> Cloudflare (DNS, WAF) -> Hetzner LB (TLS) -> :80 kamal-proxy on each VM
             app.<domain> -> arbiter-web (Next.js, :3000)
             api.<domain> -> arbiter api  (FastAPI, :8000)
                             arbiter worker (same image, no proxy)
Browser -- presigned PUT/GET --> Hetzner Object Storage (bucket), never through Cloudflare
VMs -> Ubicloud Postgres (TLS)      CI -> Tailscale -> VMs (SSH for kamal)
```

Two Kamal configs because Kamal deploys one image per service:

| Config | Service | Image | Roles |
|---|---|---|---|
| `config/deploy.yml` (+ `deploy.staging.yml`, `deploy.production.yml`) | `arbiter` | `ghcr.io/spawnjfk/arbiter-api` | `api` (proxy, `/healthz`), `worker` |
| `config/deploy.web.yml` (+ `deploy.web.staging.yml`, `deploy.web.production.yml`) | `arbiter-web` | `ghcr.io/spawnjfk/arbiter-web` | `web` (proxy, `/api/health`) |

- `.kamal/secrets-common` only reads environment variables; no value is ever committed.
- `.kamal/hooks/pre-deploy` runs `alembic upgrade head` once, on the primary api host, in a
  container of the new image, before traffic moves. A failed migration stops the deploy.
- CI (`.github/workflows/release.yml`) builds, pushes and attests the images, then runs
  `kamal deploy -d <dest> --version <sha> --skip-push` for both configs and finally
  `scripts/verify-deployed-version.mjs` against `/healthz`.

## One-time setup (owner, browser steps)

1. **Tailscale**: in the admin console create a tag `tag:ci` and `tag:arbiter`, an OAuth
   client with the `auth_keys` write scope for `tag:ci`, and an ACL rule letting `tag:ci`
   reach `tag:arbiter` on port 22. Install Tailscale on each VM with `--ssh=false
   --advertise-tags=tag:arbiter` and name the machines `arbiter-stg-1`, `arbiter-prd-1`,
   `arbiter-prd-2`. Then close port 22 in the Hetzner firewall.
2. **Hetzner Load Balancer**: one per environment, targets = the VMs (private network),
   service HTTPS 443 -> 80 with a Hetzner managed certificate for `app.` and `api.`
   hostnames, health check HTTP `/healthz` with host header `api.<domain>`.
3. **Cloudflare**: proxied A/AAAA records for `app.` and `api.` pointing at the LB, SSL
   mode Full (strict). Proxied request bodies are capped by plan, which is why uploads
   use presigned URLs straight to the bucket.
4. **Hetzner Object Storage**: one bucket per environment, an access key, and a CORS rule:
   AllowedOrigins `https://app.<domain>`, AllowedMethods `PUT, GET, HEAD`, AllowedHeaders
   `Content-Type`, ExposeHeaders `ETag`, MaxAgeSeconds `3600`. Add a lifecycle rule that
   aborts incomplete multipart uploads after 1 day.
5. **Ubicloud Postgres 16**: create the database, allow the VMs' egress IPs, copy the
   connection URL as `postgresql+psycopg://...?sslmode=require`. Enable the extensions
   `vector` and `pg_trgm`.
6. **GitHub**: Settings, Environments: create `staging` and `production` (production with
   "Required reviewers" = the owner). Add the secrets and variables listed below.

## GitHub environment secrets and variables

Secrets (per environment): `KAMAL_REGISTRY_PASSWORD` (a PAT with `read:packages`, or leave
it to the workflow's `GITHUB_TOKEN`), `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, and every
name in `.kamal/secrets-common` (`ARBITER_DATABASE_URL`, `ARBITER_JWT_SECRET`,
`ARBITER_S3_*`, `ARBITER_SMTP_*`, `ARBITER_MAIL_FROM`, provider keys, `ARBITER_POSTHOG_KEY`,
`ARBITER_HEARTBEAT_URL`, ...). Optional ones may be empty.

Variables (per environment): `ARBITER_DOMAIN` (root domain), `API_URL` (for example
`https://api.staging.<domain>`, used by the deployed-version check). Repository variables:
`NEXT_PUBLIC_POSTHOG_KEY` (public key baked into the web image, may be empty).

Until these exist the deploy jobs print the list of what is missing and skip; the image
build and attestation still run.

## Manual operation

```bash
cd deploy/kamal
export ARBITER_DOMAIN=example.com KAMAL_REGISTRY_PASSWORD=... ARBITER_DATABASE_URL=...  # etc.
kamal deploy -d staging --version <sha> --skip-push
kamal deploy -c config/deploy.web.yml -d staging --version <sha> --skip-push
kamal rollback -d staging <previous sha>          # instant: the old image is still on the host
kamal app logs -d staging --roles=worker -f
```
