# Deploying Arbiter

Two paths. **Primary (staging from P02, production from P04): Kamal 2 on Hetzner Cloud** with managed Postgres, decided in D-080 to D-083 and described in `docs/infrastructure.md`. **Fallback: one box with Docker Compose and Caddy**, used for local development, demos and as the emergency path if the Kamal stack is down (D-013 kept for that role only). Kubernetes is not used.

Status 2026-10-13: nothing is deployed. The configs and workflows exist; accounts and secrets come in P02 (`phases/phase-02-staging-deploy.md`).

## A. Primary path: Kamal on Hetzner

```
Browser -> Cloudflare (DNS, WAF, rate limits; Full strict)
        -> Hetzner Load Balancer (TLS, health checks) -> :80 kamal-proxy on each VM (private network)
             app.<domain> -> arbiter-web  (Next.js, :3000, /api/health)
             api.<domain> -> arbiter api   (FastAPI, :8000, /healthz)
                             arbiter worker (same image, no proxy, heartbeat to Better Stack)
Browser -- presigned PUT/GET --> Hetzner Object Storage (never through Cloudflare or the app)
VMs -> Ubicloud Postgres 16 (pgvector, pg_trgm, TLS, PITR)
CI  -> GHCR (build, attest) -> Tailscale -> VMs (kamal deploy)     CI -> Backblaze B2 EU (nightly dump, monthly drill)
```

| Piece | Where |
| --- | --- |
| Kamal configs, destinations, pre-deploy migration hook, secrets reader | `deploy/kamal/` and its `README.md` (one-time owner setup, GitHub environment secrets and variables) |
| Build, push, attest, deploy, verify | `.github/workflows/release.yml` (staging on green `main`, production on a `v*` tag with approval) |
| Nightly dump and monthly restore drill | `.github/workflows/backup.yml` |
| Architecture, environments, network, secrets, costs | `docs/infrastructure.md` |
| Incidents | `docs/runbook.md` |

### A1. Everyday operations (from `deploy/kamal`, connected to the tailnet)

```bash
kamal deploy -d staging --version <sha> --skip-push                          # api + worker (pre-deploy hook migrates)
kamal deploy -c config/deploy.web.yml -d staging --version <sha> --skip-push   # web
kamal rollback -d staging <previous sha>                                       # last 5 images stay on each host
kamal app logs -d staging --roles=worker -f
kamal app exec -d staging --roles=api --reuse "python -m arbiter.cli create-admin ..."
```

CI does the deploy; run these by hand only for rollback or diagnosis. Kamal does not run natively on Windows: use the official Kamal Docker image or WSL (P02 records which). After every deploy `npm run verify:deployed` must pass (it compares `/healthz` `commit` with HEAD).

### A2. Migrations

Run once per deploy by `.kamal/hooks/pre-deploy` on the primary api host, in a container of the new image, before traffic moves; `ARBITER_MIGRATE_ON_START=0` on the containers. Migrations are additive and backward compatible with the previous release (expand, deploy, contract), which is what makes `kamal rollback` safe. Never edit an applied migration.

### A3. Backups and restore

- Ubicloud point-in-time recovery (restore into a new instance from the Ubicloud console or API).
- Nightly `pg_dump -Fc`, GPG AES256 with `BACKUP_PASSPHRASE`, uploaded with a row-count manifest to Backblaze B2 EU (`backup.yml`, 02:17 UTC); retention by B2 lifecycle rule (35 daily copies).
- Monthly restore drill in CI (04:41 UTC on the 3rd): restore into a scratch pgvector Postgres, checksum, alembic version, no populated table emptied; artifact `restore-drill.json` (400 days).

Real restore from a dump into production (only after a PITR restore is ruled out):

```bash
# on an operator machine on the tailnet, with the B2 and database secrets exported (never typed on a command line)
aws s3 cp "s3://$B2_BUCKET/pg/arbiter-<STAMP>.dump.gpg" . --endpoint-url "$B2_ENDPOINT"
aws s3 cp "s3://$B2_BUCKET/pg/arbiter-<STAMP>.manifest.json" . --endpoint-url "$B2_ENDPOINT"
sha256sum arbiter-<STAMP>.dump.gpg          # compare with the manifest's sha256
gpg -d arbiter-<STAMP>.dump.gpg > arbiter.dump
# stop traffic: kamal app stop -d production (both services), then restore into a NEW Ubicloud database,
# CREATE EXTENSION vector, pg_trgm; pg_restore --no-owner --no-privileges -d <new url> arbiter.dump
# point ARBITER_DATABASE_URL at the new database, deploy, check alembic current and row counts, start traffic
```

Record every restore (drill or real) with date and duration in `docs/runbook.md`.

### A4. Queue health and logs

```bash
kamal app logs -d production --roles=api,worker --since 30m
# work_items by status (through any psql client on the tailnet):
#   select kind, status, count(*), min(run_at) from work_items group by 1,2 order by 1,2;
```

Errors and logs also go to PostHog EU (privacy mode); uptime, heartbeat and the status page are in Better Stack.

## B. Fallback path: one box with Compose and Caddy

For local development, demos, and the emergency path when the Kamal stack cannot serve. Postgres runs on a local volume here, so this path carries the operational duties the primary stack hands to Ubicloud (backups, restores, upgrades).

```
Internet -> Caddy :443 -> app.<DOMAIN> -> web:3000   (Next.js)
                        -> api.<DOMAIN> -> api:8000   (FastAPI)
                           worker (same image as api, Postgres-backed queue)
                           postgres (pgvector/pgvector:pg16, volume pgdata)
```

### F1. Server

| Stage | Hetzner type | vCPU / RAM / disk | Notes |
|---|---|---|---|
| Emergency fallback or a local demo box | 4 vCPU / 8 GB class | 80-160 GB | enough for one org, a few thousand segments a day; read the current types and prices with `hcloud server-type list` |

- Location: the same region as the primary stack, so restored data stays where customers expect it.
- Image: Ubuntu 24.04.
- Add your SSH key at create time. Enable Hetzner backups (snapshots) as a second safety net, they do not replace `backup.sh`.

### F2. Firewall

Create a Hetzner Cloud Firewall and attach it to the server:

| Direction | Port | Source | Why |
|---|---|---|---|
| in | 22/tcp | your IP(s) only | SSH |
| in | 80/tcp | any | ACME HTTP challenge + redirect |
| in | 443/tcp | any | HTTPS |
| in | 443/udp | any | HTTP/3 |

Postgres is never published. On the host also run `ufw` with the same rules if you want defense in depth (note: Docker-published ports bypass ufw, which is why only Caddy publishes ports).

SSH hardening: `PasswordAuthentication no`, `PermitRootLogin prohibit-password`, create a deploy user in the `docker` group.

### F3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy   # your deploy user
docker compose version            # must be v2+
sudo apt-get install -y rclone git
```

### F4. DNS

At your DNS provider create (TTL 300 while setting up):

| Name | Type | Value |
|---|---|---|
| `app.<DOMAIN>` | A (and AAAA) | server IPv4 (IPv6) |
| `api.<DOMAIN>` | A (and AAAA) | server IPv4 (IPv6) |
| `<DOMAIN>` | A (and AAAA) | server IP (redirects to app) |

Wait until `dig +short app.<DOMAIN>` returns the server IP before the first start, otherwise Let's Encrypt fails and rate-limits you.

### F5. Code and `.env`

```bash
sudo mkdir -p /opt/arbiter && sudo chown deploy: /opt/arbiter
git clone git@github.com:<owner>/arbiter.git /opt/arbiter
cd /opt/arbiter/deploy
cp ../.env.example .env
chmod 600 .env
```

Fill in at minimum:

- `DOMAIN` (e.g. `example.com`, no `app.` prefix) and `ACME_EMAIL`
- `POSTGRES_PASSWORD`: `openssl rand -base64 32 | tr -d '/+='`
- `ARBITER_JWT_SECRET`: `openssl rand -hex 48`
- `ARBITER_SECRETS_KEY`: a Fernet key, `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (encrypts SSO client secrets at rest; keep a copy, losing it means re-entering every IdP secret)
- `ARBITER_ENV=prod`
- provider keys you actually use (`ARBITER_ANTHROPIC_API_KEY`, `ARBITER_OPENAI_API_KEY`, `ARBITER_DEEPL_API_KEY`, `ARBITER_GOOGLE_API_KEY`) and set `ARBITER_DEFAULT_MT_ENGINE` / `ARBITER_DEFAULT_JUDGE_ENGINE` away from the mock engines
- `RCLONE_REMOTE` for backups (step 8)

Leave `NEXT_PUBLIC_API_URL` empty to get `https://api.<DOMAIN>`. It is baked into the web bundle at build time, so changing it means rebuilding `web`.

### F6. First deploy

```bash
cd /opt/arbiter/deploy
docker compose config -q              # validates .env interpolation
docker compose up -d --build
docker compose ps                     # postgres healthy, api healthy, worker/web/caddy running
curl -fsS https://api.<DOMAIN>/healthz
```

### F7. Migrations

The `api` container runs `alembic upgrade head` on start because `ARBITER_MIGRATE_ON_START=1` (worker has it at 0, so two containers never race).
To run them by hand, or with auto-migrate turned off:

```bash
docker compose run --rm --no-deps api alembic upgrade head
docker compose run --rm --no-deps api alembic current
```

Rule: migrations are additive and backward compatible with the previous release (expand, deploy, contract). Never edit an applied migration.

### F8. Backups

`backup.sh` dumps Postgres (`pg_dump -Fc`), verifies the dump with `pg_restore --list`, archives the file storage volume, writes sha256 sums, uploads with rclone, and prunes (7 days local, 30 days remote by default).

Set up the remote once:

```bash
rclone config
#  Hetzner Storage Box: type "sftp", host uXXXXX.your-storagebox.de, port 23, user uXXXXX, key auth
#  Hetzner Object Storage / any S3: type "s3", provider "Other", endpoint e.g. fsn1.your-objectstorage.com
# then in deploy/.env:  RCLONE_REMOTE=storagebox:arbiter-backups
```

Cron as root:

```
30 2 * * * /opt/arbiter/deploy/backup.sh >> /var/log/arbiter-backup.log 2>&1
```

Run it once by hand and check the remote: `rclone ls $RCLONE_REMOTE`.

### F9. Restore drill on the fallback box

On a throwaway server or locally, never on production first:

```bash
rclone copy $RCLONE_REMOTE/arbiter-db-<STAMP>.dump .
rclone copy $RCLONE_REMOTE/arbiter-<STAMP>.sha256 . && sha256sum -c --ignore-missing arbiter-<STAMP>.sha256
docker compose up -d postgres
docker compose exec -T postgres dropdb -U arbiter --if-exists arbiter_restore
docker compose exec -T postgres createdb -U arbiter arbiter_restore
docker compose exec -T postgres pg_restore -U arbiter -d arbiter_restore --no-owner < arbiter-db-<STAMP>.dump
docker compose exec -T postgres psql -U arbiter -d arbiter_restore -c "select count(*) from jobs; select count(*) from provenance_events;"
```

Real restore on production: stop `api worker web`, restore into `arbiter` (drop + create), restore the storage tarball into the `storage` volume, start again, run `alembic current`. Record the date and duration in `docs/runbook.md`. On the primary stack the drill runs monthly in CI (`backup.yml`).

### F10. Updating

```bash
cd /opt/arbiter && git pull
cd deploy
./backup.sh                                   # fresh backup before every release
docker compose build api web
docker compose up -d                          # api migrates, then worker restarts
docker compose ps && curl -fsS https://api.<DOMAIN>/healthz
```

Rollback: `git checkout <previous tag> && docker compose up -d --build`. Only possible if the migration was backward compatible, which is why the F7 rule exists.

### F11. Logs

```bash
docker compose logs -f --tail=200 api worker
docker compose logs caddy | grep -i error
docker compose exec postgres psql -U arbiter -d arbiter -c \
  "select kind, status, count(*) from work_items group by 1,2 order by 1,2;"   # queue health
```

Docker's default json-file logs grow forever. Add to `/etc/docker/daemon.json` and restart docker:

```json
{ "log-driver": "json-file", "log-opts": { "max-size": "50m", "max-file": "5" } }
```

Operational incidents (provider outage, drift alarm, escaped-error spike, webhook disabling, payout failures) are in `docs/runbook.md`.
