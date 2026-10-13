# Arbiter system design

Status: living document. Decisions referenced as D-0NN are in `docs/decisions.md`.

## 1. What the system does

Arbiter takes a customer file, translates it, decides segment by segment whether the translation can ship without a human, routes the rest to the right reviewer (human or AI editor depending on tier), rebuilds the file in its native format, and hands back an evidence pack showing why each segment shipped.

It replaces three separately bought systems:

| Layer | Comparable products | In Arbiter |
|---|---|---|
| Business / PM | Plunet, XTRF | quotes, projects, jobs, usage, invoices, reviewer payouts, ledger |
| CAT / TMS | Trados, Phrase, memoQ, XTM, Crowdin, Lokalise | file formats, segmentation, TM, termbase, MT routing, hard QA, XLIFF export |
| Reviewer marketplace | Smartcat, Gengo | reviewer sign-up, qualification tests, task routing, per-decision pay, disputes |
| Original | (ModelFront, Unbabel do parts of QE) | QE judge + multi-agent senate + calibrated thresholds + evidence |

Service tiers:

| Tier | Who touches a segment | Allowed for regulated verticals |
|---|---|---|
| `auto` | nobody if QE + senate pass, else per `no_reviewer_policy` | no |
| `ai_review` | AI editor on segments below threshold | no |
| `hybrid` | human reviewer on segments below threshold, auto above | yes |
| `full` | human reviewer on every segment | yes |

`no_reviewer_policy` (org setting) when a human is required but none is available: `wait` (job waits), `ai_fallback` (AI editor, disclosed in provenance and evidence), `partial` (deliver approved segments, hold the rest). Never silent substitution (D-012).

## 2. Components

```mermaid
flowchart LR
  subgraph Clients
    B[Browser: client / PM / reviewer / vendor / admin]
    INT[API clients, webhook consumers, OTA clients]
  end
  CF[Cloudflare: DNS, WAF]
  subgraph Cell["Hetzner Cloud cell (one region; 2+ VMs in production)"]
    LB[Load balancer, TLS]
    W[web: Next.js 16]
    A[api: FastAPI]
    K[worker: pipeline steps, email, payouts, training polls]
    S[(Object storage: files, presigned)]
  end
  P[(Ubicloud Postgres 16\npgvector + pg_trgm\nwork_items queue, PITR)]
  subgraph Providers["AI and MT providers (keys: env, platform DB, org BYOK)"]
    AN[Anthropic: global default]
    EU[Bedrock EU / Vertex eu / DeepL: eu_processing]
    OT[OpenAI, Google, own models]
  end
  OBJ[(Backblaze B2 EU\nnightly encrypted dumps)]

  B --> CF --> LB --> W
  LB --> A
  INT --> CF
  W --> A
  B -- presigned PUT/GET --> S
  A --> P
  A --> S
  K --> P
  K --> S
  K --> AN & EU & OT
  K -- webhooks --> INT
  P -. pg_dump in CI .-> OBJ
```

Deployment: Kamal 2 services `arbiter` (api, worker) and `arbiter-web` (web) from attested GHCR images, SSH over Tailscale only (D-080 to D-083, `docs/infrastructure.md`). Locally and as the emergency fallback the same images run under Docker Compose with Caddy and a Postgres volume (`deploy/docker-compose.yml`).

- **api** and **worker** are the same image (D-002). The API never calls a provider on the request path except for cheap synchronous checks; anything slow is a `work_items` row.
- **Postgres** is the only stateful service besides file storage: relational data, TM vectors (pgvector, D-003), fuzzy search (pg_trgm), queue, idempotency records, provenance.
- **Okapi Framework** sidecar (D-004) is in the ROADMAP backlog (D-090); file handling is pure Python behind `FormatHandler` and covers 25+ formats.

## 3. Pipeline

```mermaid
flowchart TD
  U[Upload file] --> X[Extract: FormatHandler -> tagged text ⟦n⟧]
  X --> SG[Segment: SRX-style rules, R-SEG]
  SG --> TM[TM lookup: context / exact / fuzzy / semantic, R-TM]
  TM -->|context or exact match| QA
  TM -->|no usable match| MT
  subgraph MT[Machine translation, R-MT]
    SB{Scoreboard has data\nfor pair + content type?}
    SB -->|yes| EC[Engine choice from scoreboard]
    SB -->|no| DEF[default_mt_engine]
    EC --> TS[Translation senate: optional\nmulti-engine candidates]
    DEF --> TS
  end
  MT --> QA[Hard QA: tags D-009, numbers, glossary R-GL,\nDNT, forbidden terms, length]
  QA -->|blocking error| BL[blocked -> review]
  QA --> QE[QE judge: LLM score 0-100, MQM-Core D-010]
  QE --> D{Decide vs threshold\nper org/content_type/target_lang}
  D -->|score >= threshold + band| AUTO[auto_approve]
  D -->|inside band| SEN[Senate: accuracy, fluency,\nterminology, consistency judges\n+ overlap arbitration]
  D -->|score <= threshold - band| REV[review]
  SEN -->|ships| AUTO
  SEN -->|does not ship| REV
  AUTO --> CS{2% blind control sample?}
  CS -->|yes| HQ
  CS -->|no| M
  REV --> T{Tier}
  T -->|hybrid / full| HQ[Human review queue\nreviewer marketplace]
  T -->|ai_review| AE[AI review editor]
  T -->|auto| POL[no_reviewer_policy]
  POL --> HQ
  POL --> AE
  HQ --> M[Merge: rebuild native file from tagged targets]
  AE --> M
  BL --> HQ
  M --> DL[Deliver: download, XLIFF, webhook job.delivered]
  DL --> EV[Evidence pack JSON + PDF from provenance]
```

Every arrow that changes a segment writes a provenance event. Every step is a `work_items` kind (e.g. `job.prepare`, `job.translate`, `job.score`, `job.merge`, `webhook.deliver`), enqueued in the same transaction as the state change that requires it.

Thresholds (D-011): one row per org + content_type + target_lang, starting at `ARBITER_DEFAULT_THRESHOLD`. Calibration moves a threshold by at most 3 points per week, driven by control samples (2% of auto-approved segments, reviewed blind) and reported escaped errors. A safety offset is added while a provider is degraded (runbook).

## 4. Data model overview

| Area | Tables | Notes |
|---|---|---|
| Tenancy | `organizations`, `users`, `api_keys` | org settings: tier default, `no_reviewer_policy`, regulated, vertical, AI subprocessor opt-in, data retention |
| Content | `projects`, `files`, `jobs`, `segments` | one job per target language; segment holds source/target tagged text, origin, engine, tm_match, qe_score, decision |
| Linguistic assets | `tm_entries`, `glossaries`, `terms`, `style_cards`, `term_questions` | terms temporal (`valid_from`/`valid_to`), job freezes glossary version; TM has embedding (pgvector) + trigram index |
| Quality | `thresholds`, `senate_runs`, `engine_scores`, `control_samples`, `escaped_errors`, `quality_metrics` | engine_scores is the scoreboard |
| Reviewers | `reviewer_profiles`, `reviewer_pairs`, `reviewer_tests`, `test_attempts`, `review_tasks`, `reviewer_score_events`, `disputes` | |
| Money | `quotes`, `usage_records`, `invoices`, `payouts`, `ledger_entries` | Decimal everywhere; ledger is double-entry style |
| Integrations | `work_items`, `webhooks`, `webhook_deliveries`, `idempotency_records` | |
| Provenance | `provenance_events` | append-only by trigger (D-015); no FK so history outlives retention deletes |

State machines for segments, jobs, review tasks and payouts are defined only in `arbiter/domain/states.py`.

## 5. Queue design (D-002)

- Table `work_items(kind, payload, status ready|running|done|dead, run_at, attempts, max_attempts, locked_by, locked_until, last_error, idempotency_key unique)`.
- Claim: `SELECT ... WHERE status='ready' AND run_at <= now() ORDER BY run_at FOR UPDATE SKIP LOCKED LIMIT n`, set `running`, `locked_by`, `locked_until`. Multiple workers never take the same row.
- Lease expiry: rows `running` past `locked_until` are returned to `ready` (crashed worker).
- Retry: exponential backoff with jitter via `run_at`; after `max_attempts` the row is `dead` and surfaces on the PM exceptions screen.
- Idempotency: enqueuing a step with an existing `idempotency_key` is a no-op, so retries and double clicks are safe. Handlers must also be idempotent (re-running a step converges to the same state).
- Transactions: "change job state + enqueue next step" commit together. No dual-write to a broker.
- Upgrade path: Temporal if workflows outgrow this (long human waits are already modelled as states, not as sleeping workers).

## 6. Security and tenancy

- Auth: JWT (HS256, `ARBITER_JWT_SECRET`, TTL `ARBITER_JWT_TTL_MINUTES`) for browser sessions; API keys `ak_<prefix>.<secret>` stored as argon2 hash, shown once, scoped (D-014).
- Roles: `admin` (platform operator), `pm`, `client`, `reviewer`. Reviewers have no org; they see only the segment and context of the task they hold, plus the relevant terms.
- Every customer query is filtered by `org_id`; tests cover cross-org access returning 404.
- Webhooks signed: `Arbiter-Signature: t=<unix>,v1=<hmac sha256 of "t.body">`; receivers dedupe on `event_id`.
- POST creates accept `Idempotency-Key` (24 h).
- Files: per-org storage keys, presigned direct uploads with size checked on `complete` (D-051), size limits at the API and kamal-proxy, format sniffing, XML parsers with entity expansion disabled (lxml `resolve_entities=False`).
- Secrets only via env (GitHub environment secrets through Kamal in staging and production); stored engine keys and SSO secrets Fernet-encrypted (D-056); Postgres reachable only from the VMs; no public SSH (Tailscale). Details: `SECURITY.md`.
- Provider data: orgs that have not opted in to AI subprocessors (`ai_subprocessors_opt_in=false`) are not sent to external LLM providers; the quote shows which tiers are available.

## 7. Data residency and processing region

- Market is global; GDPR transfers rest on DPAs with the EU-US Data Privacy Framework or SCCs, not on EU hosting (D-079). Hosting is one Hetzner region per cell (chosen in P02); a US cell or an AWS enterprise region is a separate deployment chosen at signup, never a migration (P09, `docs/infrastructure.md` section 9).
- Processing region per org: `global` (default, Claude through Anthropic's API) or `eu` (add-on `eu_processing`): only engines that declare `region = eu` (Bedrock EU inference profiles, Vertex `eu`, DeepL); no fallback outside the EU (D-057). Region, engine and model are recorded per call in provenance and in the evidence pack.
- Subprocessors: external providers receive segment text only for orgs that opted in, and only the minimum context needed. Draft list: `docs/subprocessors.md`, published after legal review before public launch.
- Retention: `data_retention_days` per org deletes content (files, segment text, TM if requested); provenance keeps hashes and decisions, not text, after retention.
- Legal review before public launch (DPA, subprocessor list, terms, reviewer contractor terms).

## 8. Observability

- Structured JSON logs (one line per request and per work item) with `org_id`, `job_id`, `segment_id`, `work_item_id`, `engine`, latency, cost.
- `/healthz` (process, with the deployed `commit`) for kamal-proxy, the load balancer and `npm run verify:deployed`; web `/api/health`; queue health from `work_items` counts by status and oldest `ready` age; worker heartbeat (`ARBITER_HEARTBEAT_URL`).
- Quality signals (in `quality_metrics`, shown on `/quality/dashboard`): auto-approve rate, escaped-error rate vs `ARBITER_ESCAPED_ERROR_TARGET`, control-sample disagreement, drift alarm when the auto rate moves more than `ARBITER_DRIFT_ALARM_RATIO` against its baseline.
- Provider health: error rate and latency per engine; the router skips unhealthy engines and the decide step adds a safety offset (runbook).
- Money signals: per job revenue, cost, margin; payouts failed.
- Error tracking, logs and LLM usage go to PostHog EU with privacy mode (never segment text); uptime checks, heartbeat, status page and phone alerts in Better Stack; OpenTelemetry in code so either can be swapped (D-083). Built in `observability.py`, all off when unset; wired on staging in P02 and production in P04.
