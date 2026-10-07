# Arbiter web

Next.js 16 (App Router, React 19, TypeScript, Tailwind CSS 4) front end for the Arbiter API.
It implements `docs/api-contract.md` (v1) for three audiences: customers (`/app`), reviewers
(`/reviewer`) and platform operators (`/admin`).

## Run

```bash
cd apps/web
npm install
cp .env.example .env.local        # set NEXT_PUBLIC_API_URL to the API origin
npm run dev                       # http://localhost:3000
```

Demo without a backend (fixtures from `src/lib/mock/`):

```bash
npm run dev:mock
# or a production build:
NEXT_PUBLIC_API_MOCK=1 npm run build && NEXT_PUBLIC_API_MOCK=1 npm start
```

In mock mode any password works; the email picks the role: `pm@demo.test`, `client@demo.test`,
`reviewer@demo.test`, `admin@demo.test` (the login page has one-click buttons). Mock state lives
in server memory and resets on restart.

Checks: `npm run lint`, `npm run typecheck`, `npm run build`.

Screenshots (server must be running in mock mode on port 3100; uses the Playwright Chromium
already on the machine): `BASE_URL=http://localhost:3100 npm run screenshots` writes to
`screenshots/`. `EXTRA=1` also captures every other screen, dark mode and mobile.

## End-to-end test (real backend)

`e2e/real-flow.mjs` drives the whole product in Chromium against a running API and worker:
register a company, upload a `.md` and a `.docx` (generated with python-docx from the API
venv), check the quote shows 4 tiers, order Auto (delivered, download, evidence PDF), order
Full (the demo reviewer clears the queue in the cockpit with `A` and `E` + `Ctrl+Enter`, the job
gets delivered), add glossary terms and see a blocked segment in Exceptions, check the admin
screens, and let a new applicant take a qualification test. Screenshots go to
`screenshots/real-*.png`.

```bash
# backend (from services/api), demo data seeded with `python -m arbiter.cli seed-demo`
ARBITER_ENV=dev ARBITER_DATABASE_URL=postgresql+psycopg://arbiter:arbiter@localhost:5432/arbiter \
  .venv/bin/uvicorn arbiter.api.app:app --port 8000 &
ARBITER_ENV=dev ARBITER_DATABASE_URL=... .venv/bin/python -m arbiter.pipeline.worker &

# web (from apps/web), NOT in mock mode
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build && npm start -- -p 3000 &
npm run e2e        # BASE_URL, PYTHON, SHOTS_DIR, DEMO_PASSWORD can be overridden
```

It then runs the Agency OS flow: the Serbian assistant prompt is applied in full, the accounts,
pharma workflow and dashboard are checked, a deal is dragged across the board, and a project
for "Beta Pharma" runs through two human reviews and client approval to delivery.
`e2e/ensure_reviewer.py` creates the second (senior) demo reviewer that `second_review` needs,
through the backend's own service functions (the seed has only one reviewer).

The script exits non-zero on any failed step, uncaught page error or HTTP 5xx; on failure it
saves `screenshots/failure-*.png`.

`npm start` works with `output: "standalone"` but Next prints a warning; production (and the
Dockerfile) runs `node .next/standalone/server.js`.

## Environment

| Variable | Where | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | build | API origin, default `http://localhost:8000` (`/v1` is appended) |
| `API_URL` | runtime, server | Overrides the origin at runtime (Docker: `http://api:8000`) |
| `NEXT_PUBLIC_API_MOCK` | build | `1` serves fixtures instead of calling the API |

## Auth model

- `POST /api/session` (route handler) proxies `/auth/login`, `/auth/register` or
  `/reviewers/apply`, stores the JWT in an **httpOnly** cookie (`arbiter_token`) plus the role
  (`arbiter_role`), and returns only `{ user, redirect }`. `DELETE /api/session` signs out.
- Server Components read the cookie and call the API directly with `Authorization: Bearer`
  (`src/lib/server-api.ts`).
- Client Components call `/api/proxy/<path>`, which forwards to `<API>/v1/<path>` with the
  cookie token (`src/app/api/proxy/[...path]/route.ts`). The token never reaches browser JS.
  Downloads (file, XLIFF, evidence, exports) are plain links to the same proxy.
- `src/proxy.ts` (Next 16's replacement for `middleware.ts`) redirects signed-out users from
  `/app`, `/reviewer`, `/admin` to `/login?next=…` and sends signed-in users to their role's
  area (client/pm → `/app`, reviewer → `/reviewer`, admin → `/admin`). It only routes; the API
  stays the authority. A 401 from the API sends the user through `/logout`, which clears the
  cookies.

## Layout

```
src/app/(public)/        landing, /login, /register, /reviewers/apply
src/app/app/             customer app: dashboard (home), projects, wizard, jobs, assets, quality, settings,
                         Agency OS: crm (accounts, deals board, tasks), price-lists, workflows, assistant
src/app/reviewer/        dashboard, tests, cockpit, earnings, disputes
src/app/admin/           reviewers, disputes, payouts, orgs
src/app/api/             session + proxy route handlers
src/components/ui/       Button, Input/Select/Checkbox/Field, Table, Badge, Card, Dialog, Toast, Kbd, EmptyState
src/components/          shell, tag editor, tagged text, error annotator, …
src/lib/api.ts           typed client for every contract endpoint (shared by both transports)
src/lib/types.ts         contract types
src/lib/tags.ts          tagged-text model (⟦1⟧…⟦/1⟧, ⟦2/⟧, escaped ⟦⟦ ⟧⟧)
src/lib/mock/            fixtures and in-memory mock API
```

## Agency OS

PM-only business layer (contract addendum "Agency OS"): `/app` is the dashboard (KPIs, SVG
charts, deal pipeline, tables, 30/90/365-day periods, editable widget list from the metric
catalogue; projects moved to `/app/projects`), `/app/crm` accounts with contacts, deals,
activity timeline, projects and defaults, `/app/crm/deals` kanban (HTML5 drag and drop plus a
stage select per card), `/app/crm/tasks`, `/app/price-lists`, `/app/workflows` (step editor
with live validation mirroring `agency/workflows.py`, boxes-and-arrows pipeline) and
`/app/assistant` (chat; the assistant answers with a plan that is applied all at once or per
action; nothing changes before that). The project wizard takes an account and a workflow; the
job page shows the workflow position, the senate count and the client-approval step.

## Tag-aware editing

Inline tags render as atomic chips (`contenteditable=false`). Deleting or overwriting a tag
required by the source is blocked at `beforeinput`; if a browser path slips through, the last
valid content is restored. Missing tags can be re-inserted with one click, extra tags show in
red, and Save stays disabled until the target has exactly the source's tags. The API validates
again on `PATCH`.

## Docker

```bash
docker build -t arbiter-web --build-arg NEXT_PUBLIC_API_URL=https://api.example.com apps/web
docker run -p 3000:3000 -e API_URL=http://api:8000 arbiter-web
```
