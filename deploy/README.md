# Deploying Arbiter on Hetzner

One server, Docker Compose, Caddy for TLS, Postgres on a local volume, nightly off-site backups.
Everything stays in the EU (Hetzner Germany or Finland). Kubernetes is deliberately not used (see D-013 in `docs/decisions.md`).

```
Internet -> Caddy :443 -> app.<DOMAIN> -> web:3000   (Next.js)
                        -> api.<DOMAIN> -> api:8000   (FastAPI)
                           worker (same image as api, Postgres-backed queue)
                           postgres (pgvector/pgvector:pg16, volume pgdata)
```

## 1. Server

| Stage | Hetzner type | vCPU / RAM / disk | Notes |
|---|---|---|---|
| P01 measurement and P02 staging, private beta | CX32 or CPX31 | 4 / 8 GB / 80-160 GB | enough for one org, a few thousand segments a day |
| P04 public self-serve | CPX41 or CCX23 (dedicated vCPU) | 8 / 16 GB / 240 GB | dedicated vCPU once LLM traffic and file conversion overlap |
| Later | split Postgres to its own CCX host or Hetzner managed option | | when DB CPU is the bottleneck |

- Location: `fsn1`/`nbg1` (Germany) or `hel1` (Finland). Pick one and keep data there.
- Image: Ubuntu 24.04.
- Add your SSH key at create time. Enable Hetzner backups (snapshots) as a second safety net, they do not replace `backup.sh`.

## 2. Firewall

Create a Hetzner Cloud Firewall and attach it to the server:

| Direction | Port | Source | Why |
|---|---|---|---|
| in | 22/tcp | your IP(s) only | SSH |
| in | 80/tcp | any | ACME HTTP challenge + redirect |
| in | 443/tcp | any | HTTPS |
| in | 443/udp | any | HTTP/3 |

Postgres is never published. On the host also run `ufw` with the same rules if you want defense in depth (note: Docker-published ports bypass ufw, which is why only Caddy publishes ports).

SSH hardening: `PasswordAuthentication no`, `PermitRootLogin prohibit-password`, create a deploy user in the `docker` group.

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy   # your deploy user
docker compose version            # must be v2+
sudo apt-get install -y rclone git
```

## 4. DNS

At your DNS provider create (TTL 300 while setting up):

| Name | Type | Value |
|---|---|---|
| `app.<DOMAIN>` | A (and AAAA) | server IPv4 (IPv6) |
| `api.<DOMAIN>` | A (and AAAA) | server IPv4 (IPv6) |
| `<DOMAIN>` | A (and AAAA) | server IP (redirects to app) |

Wait until `dig +short app.<DOMAIN>` returns the server IP before the first start, otherwise Let's Encrypt fails and rate-limits you.

## 5. Code and `.env`

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
- `ARBITER_ENV=prod`
- provider keys you actually use (`ARBITER_ANTHROPIC_API_KEY`, `ARBITER_OPENAI_API_KEY`, `ARBITER_DEEPL_API_KEY`, `ARBITER_GOOGLE_API_KEY`) and set `ARBITER_DEFAULT_MT_ENGINE` / `ARBITER_DEFAULT_JUDGE_ENGINE` away from the mock engines
- `RCLONE_REMOTE` for backups (step 8)

Leave `NEXT_PUBLIC_API_URL` empty to get `https://api.<DOMAIN>`. It is baked into the web bundle at build time, so changing it means rebuilding `web`.

## 6. First deploy

```bash
cd /opt/arbiter/deploy
docker compose config -q              # validates .env interpolation
docker compose up -d --build
docker compose ps                     # postgres healthy, api healthy, worker/web/caddy running
curl -fsS https://api.<DOMAIN>/healthz
```

## 7. Migrations

The `api` container runs `alembic upgrade head` on start because `ARBITER_MIGRATE_ON_START=1` (worker has it at 0, so two containers never race).
To run them by hand, or with auto-migrate turned off:

```bash
docker compose run --rm --no-deps api alembic upgrade head
docker compose run --rm --no-deps api alembic current
```

Rule: migrations are additive and backward compatible with the previous release (expand, deploy, contract). Never edit an applied migration.

## 8. Backups

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

## 9. Restore drill (do it monthly, and before the P04 launch)

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

Real restore on production: stop `api worker web`, restore into `arbiter` (drop + create), restore the storage tarball into the `storage` volume, start again, run `alembic current`. Record the drill date and duration in `docs/runbook.md`.

## 10. Updating

```bash
cd /opt/arbiter && git pull
cd deploy
./backup.sh                                   # fresh backup before every release
docker compose build api web
docker compose up -d                          # api migrates, then worker restarts
docker compose ps && curl -fsS https://api.<DOMAIN>/healthz
```

Rollback: `git checkout <previous tag> && docker compose up -d --build`. Only possible if the migration was backward compatible, which is why rule 7 exists.

## 11. Logs

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
