# Security policy

## Reporting a vulnerability

Do not open a public issue. Email the security contact listed on the product website (to be published before public launch) with:
- what you found and where (URL, endpoint, file),
- steps to reproduce,
- impact as you understand it.

We acknowledge within 3 business days and keep you updated until it is fixed. Please give us reasonable time to fix before disclosure. Do not access other customers' data, degrade the service, or run automated scanners against production.

## Scope

In scope: the Arbiter web app, API, webhooks and file processing. Out of scope: third-party providers (LLM and MT vendors, hosting), social engineering, denial of service.

## How the platform protects data

- Hosting in the EU (Hetzner, Germany or Finland); database, files and backups stay in the EU.
- TLS everywhere via Caddy (HSTS); Postgres never exposed to the internet.
- Tenancy: every customer query is scoped by organization; reviewers only see the task they hold.
- Passwords and API keys stored as argon2 hashes; API keys shown once.
- Webhooks signed with HMAC SHA-256 and a timestamp.
- XML parsing with entity resolution and network access disabled.
- Segment text goes to external AI providers only for organizations that opted in.
- Append-only provenance for every segment (database trigger).
- Secrets only via environment variables, never in the repository.
- Nightly off-site backups (EU object storage) with periodic restore drills. Use an encrypted rclone remote (crypt) for backups.

## For contributors and agents

- Never commit `.env` files, keys, customer files or real translation data. Keys only via `ARBITER_*` env vars; `.env.example` holds names with empty or dev-only values.
- `.cursor/mcp.json` is gitignored (it carries the Context7 key); only `.cursor/mcp.json.example` with placeholders is tracked.
- Evidence artifacts (`evidence/`) and measurement manifests never contain keys, connection strings or customer text. Reference documents for measurements stay outside git under the artifact root.
- Never paste a token into a shell command. The Cursor shell guard (`scripts/cursor-shell-guard.mjs` over `.hyperpower/core/guard.mjs`) blocks literal credential-shaped tokens, `git reset --hard`, forced `git clean`, force push, recursive deletes at a root and download-and-execute pipes.
- The pre-commit hook (`.githooks/pre-commit`) warns on staged env files and runs Betterleaks over the staged diff when it is installed; `/end` runs it again before a push. A secret that was ever pushed is rotated, not just removed.
- Tool binaries come only from `.hyperpower/tools/registry.json` with their SHA256 checked; a mismatch stops the install.
- Tests use mock providers only.
- Dependency updates go through CI; OSV-Scanner runs on both dependency sets before a phase gate that adds dependencies.
- The deploy key (from P02) is restricted to a forced command that only runs the deploy script; it cannot open a shell.
- Legal and compliance documents (DPA, subprocessor list) receive legal review before public launch.
