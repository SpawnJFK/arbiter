# Security policy

## Reporting a vulnerability

Do not open a public issue. Email the security contact listed on the product website (to be published before public launch) with:
- what you found and where (URL, endpoint, file),
- steps to reproduce,
- impact as you understand it.

We acknowledge within 3 business days and keep you updated until it is fixed. Please give us reasonable time to fix before disclosure. Do not access other customers' data, degrade the service, or run automated scanners against production.

## Scope

In scope: the Arbiter web app, API, webhooks, OTA endpoints, the vendor workbench and file processing. Out of scope: third-party providers (LLM and MT vendors, hosting), social engineering, denial of service.

## How the platform protects data

Status 2026-10-13: built and tested locally; nothing is deployed. Hosting items describe the planned stack (`docs/infrastructure.md`, D-079 to D-083).

**Hosting and network (planned, P02 and P04)**
- App on Hetzner Cloud VMs behind a Hetzner Load Balancer, database on Ubicloud managed Postgres, customer files in Hetzner Object Storage, all in one region chosen in P02. Backups at a different provider (Backblaze B2, EU region), encrypted before upload.
- Cloudflare in front (DNS, WAF managed rules, rate limits), TLS Full (strict) from Cloudflare to the load balancer. The VMs accept 80 and 443 only from the load balancer and the private network.
- No public SSH: operators and CI reach the VMs only over Tailscale (`tag:ci` to `tag:arbiter` on port 22). Postgres accepts only the VMs' addresses, TLS required.
- Files go from the browser straight to a private bucket through short-lived presigned URLs; buckets allow only the app origin (CORS).
- Images are built in CI, pushed to GHCR and attested; hosts never build. Deploys are by commit SHA and `/healthz` reports the running commit.
- Local development and the emergency fallback use `deploy/docker-compose.yml` with Caddy; there only Caddy publishes ports.

**Data residency and AI processing**
- GDPR transfers are covered by DPAs with the EU-US Data Privacy Framework or Standard Contractual Clauses (legal review before public launch, D-079); EU hosting is not claimed as a GDPR requirement.
- Segment text goes to external AI providers only for organizations that opted in. By default Claude runs through Anthropic's API (global). Organizations with the `eu_processing` add-on reach only engines that process in the EU (Bedrock EU, Vertex `eu`, DeepL); when none is configured the job fails visibly instead of falling back (D-057). The region of every call is recorded in provenance and the evidence pack.
- Observability never receives segment text: PostHog runs with privacy mode, logs carry ids, not text (D-083).

**Tenancy and access**
- Every customer query is scoped by organization; another org gets 404. Reviewers see only the task they hold; vendors reach only their assignment through a signed workbench token.
- Modules are gated per org (disabled module answers 404 `module_disabled`, D-052). Custom roles cannot grant permissions their creator lacks; `audit.read` is explicit-only (D-053).
- Passwords and API keys stored as argon2 hashes; API keys shown once. Browser sessions use an httpOnly cookie behind the web server's proxy (D-036).
- **SSO**: OpenID Connect code flow with PKCE; ID tokens validated for issuer, audience, expiry and nonce; email domains proven by DNS TXT before an IdP can sign users in; optional enforcement blocks password login for the org; just-in-time provisioning is audited (D-055). SAML and SCIM arrive in P07.

**Audit log**
- `audit_events` is append-only (a database trigger rejects UPDATE and DELETE, like provenance) and written in the same transaction as the change, so rolled-back changes leave no event (D-054). It records actor, target, before and after values, client IP and user agent (forwarded headers only with `ARBITER_TRUST_PROXY_HEADERS`). Secret-looking fields are redacted; the CSV export guards against spreadsheet formula injection. Known gap: failed logins are not audited yet.
- Append-only provenance for every segment change (database trigger).

**Secrets and key rotation**
- Secrets only via environment variables (`ARBITER_*`), never in the repository. In staging and production they live in GitHub environment secrets and reach the containers through Kamal; `.kamal/secrets-common` only reads variables.
- **BYOK and stored secrets**: engine keys entered in the UI (platform keys and customer BYOK) and SSO client secrets are encrypted at rest with Fernet (AES-128-CBC with HMAC-SHA256) under `ARBITER_SECRETS_KEY`, never returned by the API (last 4 characters only) and decrypted only when a client is built (D-056, D-078). Key resolution: org BYOK, then platform key, then environment.
- **Rotation of `ARBITER_SECRETS_KEY`**: the setting is a comma-separated list; the first key encrypts and every key decrypts (MultiFernet). To rotate: put the new key first and keep the old one second, deploy, re-encrypt every stored secret with `platform.secrets.rotate()` (a re-encrypt command is still to be written and is filed for P02), then remove the old key and deploy again. Losing every key means re-entering every stored engine key and IdP secret, so the key is backed up offline by the owner.
- **Gap to close before the first deploy (P02 item 7)**: the Kamal configs do not pass `ARBITER_SECRETS_KEY` yet, and the app does not refuse its dev default; P02 adds both, plus a startup refusal of the dev default `ARBITER_JWT_SECRET` outside dev and test.
- **Other rotations**: `ARBITER_JWT_SECRET` (rotating it signs everyone out), database password (Ubicloud, then the GitHub secret, then a deploy), S3 and B2 keys (new key, deploy, revoke old), provider keys (in the provider console, then the secret or the Engines page), webhook signing secrets for Paddle (Paddle sends more than one signature while a secret rotates), `BACKUP_PASSPHRASE` (new dumps use the new one; keep the old one until the last dump encrypted with it has expired from B2). A secret that was ever pushed or pasted into a command line is rotated, not just removed.

**Other controls**
- Webhooks signed with HMAC SHA-256 and a timestamp; provider webhooks (Paddle, Stripe) verified and stored once per event id.
- XML parsing with entity resolution and network access disabled.
- Backups: Ubicloud point-in-time recovery, nightly encrypted dumps to Backblaze B2 EU, a monthly restore drill in CI with a JSON evidence artifact (D-082).

## For contributors and agents

- Never commit `.env` files, keys, customer files or real translation data. Keys only via `ARBITER_*` env vars; `.env.example` holds names with empty or dev-only values.
- `.cursor/mcp.json` is gitignored (it carries the Context7 key); only `.cursor/mcp.json.example` with placeholders is tracked.
- Evidence artifacts (`evidence/`) and measurement manifests never contain keys, connection strings or customer text. Reference documents for measurements stay outside git under the artifact root.
- Never paste a token into a shell command. The Cursor shell guard (`scripts/cursor-shell-guard.mjs` over `.hyperpower/core/guard.mjs`) blocks literal credential-shaped tokens, `git reset --hard`, forced `git clean`, force push, recursive deletes at a root and download-and-execute pipes.
- The pre-commit hook (`.githooks/pre-commit`) warns on staged env files and runs Betterleaks over the staged diff when it is installed; `/end` runs it again before a push. A secret that was ever pushed is rotated, not just removed.
- Tool binaries come only from `.hyperpower/tools/registry.json` with their SHA256 checked; a mismatch stops the install.
- Tests use mock providers only.
- Dependency updates go through CI; OSV-Scanner runs on both dependency sets before a phase gate that adds dependencies.
- Deploys run from CI over Tailscale with an OAuth client limited to `tag:ci`; there is no public SSH and no long-lived deploy key on a laptop. Production deploys need a `v*` tag and manual approval (P04).
- Legal and compliance documents (DPA, subprocessor list draft in `docs/subprocessors.md`, terms, privacy policy) receive legal review before public launch.
