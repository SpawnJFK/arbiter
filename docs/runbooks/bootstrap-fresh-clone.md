# Bootstrap a fresh clone (Windows)

For the owner's machine, a second Cursor window on another machine, or a temp clone. The agent runs every command here; nothing is for the owner to type. Repo root on the owner's machine: `E:\arbiter`. Caches and big artifacts stay on `E:` (`hyperpower.json` `storagePolicy`).

Binaries are gitignored and reinstalled per machine from `.hyperpower/tools/registry.json`. The SHA256 there is for the extracted binary, not the archive. A mismatch stops the install; never skip the check.

## 1. Clone and runtimes

```powershell
git clone https://github.com/SpawnJFK/arbiter.git E:\arbiter
cd E:\arbiter
fnm install 24
fnm use                   # reads .node-version
node --version            # v24.x
npm config set cache E:/.caches/npm
[Environment]::SetEnvironmentVariable("PLAYWRIGHT_BROWSERS_PATH", "E:\.caches\ms-playwright", "User")
[Environment]::SetEnvironmentVariable("UV_CACHE_DIR", "E:\.caches\uv", "User")
[Environment]::SetEnvironmentVariable("UV_PYTHON_INSTALL_DIR", "E:\.caches\uv-python", "User")
[Environment]::SetEnvironmentVariable("IMPECCABLE_HOME", "E:\.caches\impeccable", "User")
git config core.hooksPath .githooks
```

The hooks are `#!/bin/sh` and run under Git Bash, which does not see fnm's Node on PATH. `scripts/githook-locate-node.sh` finds it under `%APPDATA%\fnm\node-versions`. Prove the hooks with a real `git commit` and `git push`, not by running the scripts.

## 2. API (Python 3.13 with uv)

```powershell
uv python install 3.13
uv venv --python 3.13 services\api\.venv
uv pip install --python services\api\.venv\Scripts\python.exe -e "services/api[dev]"
Copy-Item .env.example services\api\.env      # dev defaults; provider keys stay empty until P01
npm run check:runtime
```

## 3. Web

```powershell
cd apps\web
npm ci
npx playwright install chromium
Copy-Item .env.example .env.local
cd ..\..
```

## 4. Local Postgres (Docker Desktop)

```powershell
docker compose -f deploy/docker-compose.dev.yml up -d --wait   # Postgres 16 + pgvector, dbs arbiter and arbiter_test
cd services\api
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m arbiter.cli seed-demo
cd ..\..
npm run verify
```

If Docker Desktop is missing, P00 human step A installs it with its disk image on `E:\.caches\docker`.

## 5. Tools from the registry

### Beads (`bd`)

| Field | Value |
| --- | --- |
| Version | 1.3.1 |
| Release asset | https://github.com/gastownhall/beads/releases/download/v1.3.1/beads_1.3.1_windows_amd64.zip |
| Binary SHA256 | `AC5B60114E5E7EF9DE8878B45FC35941937341D3447366C99BC91C81557BE7A4` |
| Install path | `.hyperpower/tools/bin/bd.exe` |
| Licence | MIT |

```powershell
$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$ver = "1.3.1"
$zip = "E:\.caches\beads_$ver.zip"
$out = "E:\.caches\beads-extract"
Invoke-WebRequest -Uri "https://github.com/gastownhall/beads/releases/download/v$ver/beads_${ver}_windows_amd64.zip" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $out -Force
New-Item -ItemType Directory -Force -Path "$root\.hyperpower\tools\bin" | Out-Null
Copy-Item "$out\bd.exe" "$root\.hyperpower\tools\bin\bd.exe"
$hash = (Get-FileHash "$root\.hyperpower\tools\bin\bd.exe" -Algorithm SHA256).Hash
if ($hash -ne "AC5B60114E5E7EF9DE8878B45FC35941937341D3447366C99BC91C81557BE7A4") { throw "bd.exe SHA256 mismatch: $hash" }
& "$root\.hyperpower\tools\bin\bd.exe" version
```

First install (P00): `.beads/issues.jsonl` is empty, so run `bd init --prefix arbiter` once and log it in `memory-bank/activeContext.md`. Every later clone: `bd bootstrap --yes` imports the tracked `issues.jsonl`. After any bead change: `bd export -o .beads/issues.jsonl` and commit it; the pre-push hook warns when you forget.

Verify: the ids and statuses from `bd list --all --json` match `.beads/issues.jsonl` line for line, and `npm run hp -- beads health` exits 0 (after P00 has written the bead ids).

### Graphify

| Field | Value |
| --- | --- |
| Package | `graphifyy==0.9.28` (PyPI) |
| Binary SHA256 | `F9D336E7C17818D9B76A790E6F503E16387A4729E567F5D12A63CCCA18E8818B` |
| Install path | `.hyperpower/tools/bin/graphify.exe` |
| Licence | Apache-2.0/MIT |

```powershell
uv venv --python 3.13 "$root\.hyperpower\tools\graphify-venv"
uv pip install --python "$root\.hyperpower\tools\graphify-venv\Scripts\python.exe" "graphifyy==0.9.28"
Copy-Item "$root\.hyperpower\tools\graphify-venv\Scripts\graphify.exe" "$root\.hyperpower\tools\bin\graphify.exe"
$hash = (Get-FileHash "$root\.hyperpower\tools\bin\graphify.exe" -Algorithm SHA256).Hash
if ($hash -ne "F9D336E7C17818D9B76A790E6F503E16387A4729E567F5D12A63CCCA18E8818B") { throw "graphify.exe SHA256 mismatch: $hash" }
& "$root\.hyperpower\tools\bin\graphify.exe" extract . --code-only --no-viz
& "$root\.hyperpower\tools\bin\graphify.exe" query "no_reviewer_policy" --dfs --budget 1500
```

`.graphifyignore` limits the index to `services/api/arbiter/`, `services/api/migrations/`, `apps/web/src/` and `scripts/`. Output goes to `graphify-out/` (gitignored). The registry hash was recorded for the launcher pip built on the pilot machine with `pip`; if `uv` builds a launcher with a different hash, record the new hash in `registry.json` with a decision entry; never skip the check.

### OSV-Scanner and Betterleaks

| Tool | Version | Binary SHA256 | Install path |
| --- | --- | --- | --- |
| osv-scanner | 2.6.0 | `E0ED7644118B717B028C249EE9D3515024E55E8510747CA08906EB96765354D6` | `.hyperpower/tools/bin/osv-scanner.exe` |
| betterleaks | 1.9.0 | `41A3DC5E75712D52D25AA7203B0B6BC2FA9C796FE5109D3835C60226A9A69352` | `.hyperpower/tools/bin/betterleaks.exe` |

Download the Windows amd64 asset from each project's GitHub release page for that version, extract, copy to the install path, and check the hash the same way as `bd.exe`. Then confirm the pre-commit flags in `scripts/githook-pre-commit.mjs` against `betterleaks.exe git --help` and fix them if they differ.

### Impeccable engine

```powershell
& .cursor\skills\impeccable\scripts\impeccable.cmd context
```

The launcher downloads the engine version in `.cursor/skills/impeccable/scripts/VERSION`, verifies it against its `.sha256` sidecar and caches it under `IMPECCABLE_HOME`. Only then wire `scripts/impeccable-pre-edit-hook.mjs` into `.cursor/hooks.json` (P00 item 13).

## 6. MCP

Copy `.cursor/mcp.json.example` to `.cursor/mcp.json`, fill the Context7 key, then the owner fully quits and reopens Cursor (`phases/phase-00-install-and-verify.md`, human step B).

## 7. Prove it

```
npm run verify
npm run verify:e2e            # with API, worker and web running (P00 item 9)
npm run hp -- doctor          # exit 0, no BROKEN
npm run hp -- beads health
git push                      # output shows "[graphify] pre-push: index fresh" and "[beads] pre-push: export in sync"
```
