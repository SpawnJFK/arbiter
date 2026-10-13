# Arbiter API contract (v1)

The route code in `services/api/arbiter/api/routes/*.py` is the source of truth; this file describes it. When they disagree, fix this file (or the code, with a decision entry).
Interactive schema: `GET /docs` and `GET /openapi.json` on the API host.

## Conventions

- Base URL `/v1` (except `GET /healthz` -> `{ok: true}`). JSON everywhere except uploads (multipart) and downloads (binary).
- Auth: `Authorization: Bearer <jwt>` (from register/login/apply) or `Authorization: Bearer ak_<prefix>.<secret>` (API key, acts with role `api` for its org).
- Ids are prefixed strings (`job_01J...`). Money is a decimal string (`"12.40"`). Times are ISO 8601 UTC. Naive input times are rejected (`due_at`) or read as UTC (CRM `due_at`).
- Lists: `{"items": [...], "next_offset": int|null}`; query `offset` (>= 0), `limit` (default 50, capped at 200).
- Errors: `{"error": {"code": "string", "message": "string", "details": {}}}`.
- Tenancy: an object of another organization is always a 404, never a 403.

### Roles

| Tag | Who | Typical use |
|---|---|---|
| **public** | no token | register, login, reviewer apply |
| **pm** | `pm` user or API key | every write on the customer side, CRM, workflows, price lists, assistant, webhooks |
| **cust** | `pm`, `client` or API key | reads; file upload; quotes; segment edit/approve; report errors; client approval |
| **rev** | `reviewer` user | `/reviewer/*` |
| **admin** | platform operator | `/admin/*` |

The `client` role sees money fields (`revenue`, `cost`, `margin`, dashboard money) as `null`.

### Error codes

| Status | Code | When |
|---|---|---|
| 401 | `unauthorized` | missing/invalid token or API key, wrong login |
| 403 | `forbidden` | role not allowed; reviewer not active (details carry `status`) |
| 404 | `not_found` | unknown id or another org's object |
| 409 | `conflict` | generic state conflict (segment in review, question already answered...) |
| 409 | `illegal_state` | transition not allowed by `domain/states.py` (e.g. cancel a delivered job) |
| 409 | `idempotency_conflict` | Idempotency-Key reused with a different body or on another endpoint |
| 409 | `quote_expired` | project from a quote past `valid_until` |
| 409 | `quote_not_open` | project from a quote already accepted or expired |
| 409 | `not_delivered` | download before the job is delivered |
| 409 | `not_awaiting_client` | client-approve on a job that is not waiting for it |
| 422 | `validation_error` | request body/query invalid (`details.errors`) |
| 422 | `invalid` | generic business rule (archived account, same source and target language...) |
| 422 | `unsupported_file` | upload cannot be read or format not supported |
| 422 | `tier_not_allowed` | tier unavailable for the quote/org (regulated: no `auto`/`ai_review`) |
| 422 | `tag_error` | edit/approve would break inline codes (D-009 error severity; `details.issues`) |
| 422 | `rights_not_confirmed` | TM import without `rights_confirmed=true` (R-TM-01) |
| 422 | `workflow_invalid` | workflow template fails validation |
| 404 | `module_disabled` | the org has not enabled the module the route belongs to |
| 409 | `upload_missing` | complete called before the bytes reached storage |
| 409 | `upload_expired` | the upload URL expired before the bytes arrived, or the upload was rejected |
| 422 | `size_mismatch` | stored object size differs from the declared size (object deleted) |
| 413 | `too_large` | local signed PUT body larger than the declared size |
| 403 | `invalid_signature` | local signed upload URL forged or expired |
| 422 | `invalid_token` | password reset or invitation link unknown, used or expired |
| 500 | `internal_error` | unhandled error (reported to error tracking without the request body) |

### Idempotency

`Idempotency-Key` header (max 150 chars) is honoured on these creating POSTs: `/files`, `/uploads`, `/uploads/{id}/complete`, `/quotes`, `/projects`, `/glossaries`, `/webhooks`, `/crm/accounts`, `/crm/accounts/{id}/contacts`, `/crm/deals`, `/crm/activities`, `/price-lists`, `/workflows`, `/dashboards`, `/assistant/threads`, `/assistant/threads/{id}/messages`.
One key space per organization, kept 24 h. Same key + same body on the same endpoint replays the stored response; anything else is 409 `idempotency_conflict`. Concurrent requests with one key are serialised.

### Score scales

| Score | Range |
|---|---|
| `qe_score` (segment, task) | 0-100 |
| `tm_match` (segment), TM search `score` | 0-101 (101 = in-context match, 100 = exact) |
| reviewer `score`, pair `score`, test `score`, `pass_mark` | 0-100 |
| `progress`, `auto_rate`, `escaped_rate`, `est_auto_rate` | 0-1 |

---

## Auth and account

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| POST | /auth/register | public | `{org_name, name?, email, password(>=8)}` | 201 `{token, user, org}` (creates org + pm user); 409 if email exists |
| POST | /auth/login | public | `{email, password}` | `{token, user}`. `email` is any string (demo accounts use reserved domains) |
| POST | /auth/password/forgot | public | `{email}` | 202 `{ok: true}` always (never reveals whether the address exists). Queues the `password_reset` email; at most 5 links per user per hour |
| POST | /auth/password/reset | public | `{token, password(>=8)}` | `{token, user}` (signed in). Accepts reset and invitation links; single use, expiring; every other open link of the user is revoked. 422 `invalid_token` |
| GET | /me | any | | `{user\|null, org\|null}` (org null for reviewers/admin; user null for API keys) |
| GET | /org | cust | | `Org` |
| PATCH | /org | pm | `{name?, default_tier?, no_reviewer_policy?, ai_subprocessors_opt_in?, regulated?, vertical?, data_retention_days?(1..3650), processing_region?: global\|eu, training_consent?}` | `Org`. `processing_region: eu` needs the `eu_processing` add-on (422 otherwise); regulated orgs may set it |
| GET | /api-keys | pm | | list of `{id, name, prefix, scopes, created_at, last_used_at}` (not revoked) |
| POST | /api-keys | pm (users only) | `{name, scopes[]}` | 201 key view + `key` (shown once). An API key cannot create keys (422) |
| DELETE | /api-keys/{id} | pm | | 204 (revokes) |

`User`: `{id, email, name, role, org_id}`.
`Org`: `{id, name, slug, plan, default_tier, no_reviewer_policy: wait|ai_fallback|partial, ai_subprocessors_opt_in, regulated, vertical, data_retention_days, processing_region: global|eu, training_consent}`.

## Files, quotes, projects, jobs

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| POST | /files | cust | multipart `file`, `source_lang` | 201 `File`. Extracted once to validate; 422 `unsupported_file` otherwise. Limit 1 GB. Small files and fallback only: browsers use `/uploads` |
| POST | /uploads | cust, module `tms` | `{filename, size(1..1 GB), content_type, source_lang}` | 201 `{upload_id, url, method: PUT, headers, expires_at, max_bytes, size, backend: local\|s3}`. Extension checked first (422 `unsupported_file`). PUT the raw bytes to `url` with `headers` |
| GET | /uploads/{id} | cust, module `tms` | | `{upload_id, filename, size, status: pending\|completed\|rejected, file_id, expires_at}` |
| POST | /uploads/{id}/complete | cust, module `tms` | | 201 `File` (same as POST /files; completing twice returns the same file). 409 `upload_missing` / `upload_expired`, 422 `size_mismatch` / `unsupported_file` |
| PUT | /uploads/{id}/blob | signed URL | `?expires=&token=` raw body | 204. Only with the local storage backend: the HMAC in the query is the authorization (no bearer). 404 with s3 |
| POST | /quotes | cust | `{file_id, target_langs[1..50], content_type="general", account_id?}` | 201 `Quote` (account's price list when `account_id` given) |
| GET | /quotes/{id} | cust | | `Quote` (`status` reads `expired` once past `valid_until`) |
| POST | /projects | pm | `{name, quote_id, tier?, due_at?, account_id?, workflow_template_id?}` | 201 `Project` with `jobs[]` (one per target language, started) |
| GET | /projects | cust | `?account_id=` | list of `Project` |
| GET | /projects/{id} | cust | | `Project` with `jobs[]` |
| GET | /jobs | cust | `?state=&project_id=&account_id=` | list of `Job` |
| GET | /jobs/{id} | cust | | `Job` |
| GET | /jobs/{id}/segments | cust | `?state=&decision=&offset=&limit=` | list of `Segment` ordered by `seq` |
| PATCH | /jobs/{id}/segments/{seg_id} | cust | `{target_tagged}` | `Segment`. Counts as a human decision (provenance `human`), learned into the TM |
| POST | /jobs/{id}/segments/{seg_id}/approve | cust | | `Segment` (`needs_review` -> `reviewed`; repeat is a no-op) |
| POST | /jobs/{id}/cancel | pm | | `Job` (repeat is a no-op; delivered/failed -> 409 `illegal_state`) |
| POST | /jobs/{id}/client-approve | cust | | `Job` (repeat is a no-op; 409 `not_awaiting_client` otherwise) |
| GET | /jobs/{id}/download | cust | | translated file; 409 `not_delivered` before `delivered`/`settled`/`disputed`. With the s3 backend: 302 to a presigned GET (5 min) |
| GET | /jobs/{id}/xliff | cust | | XLIFF 2.1 (units whose segments all have a target carry it) |
| GET | /jobs/{id}/evidence | cust | `?format=json\|pdf` | stored pack for delivered jobs, live pack otherwise. Stored pack with the s3 backend: 302 to a presigned GET |
| POST | /jobs/{id}/report-error | cust | `{segment_id, note?}` | 201 `{id}` (escaped error, feeds calibration). Only on `delivered` segments, else 409 |
| GET | /exceptions | pm | | list of `{kind, job_id, segment_id, reason, created_at, term_question_id?}` |

Segment edits: 409 when the job is `cancelled`, `failed` or `merging`, when the segment is still `pending`/`translated`, or when a reviewer holds it (`in_review`). A tag-breaking target is 422 `tag_error`.
Exception kinds: `job_failed`, `segment_blocked`, `term_question`, `client_review`, `overdue`.

**Project tier and workflow resolution** (most explicit first):
1. `workflow_template_id` given: that template, and its tier wins over `tier`.
2. `tier` not given: the account's workflow template, else the org's default template.
3. No template: `tier`, else the account's `default_tier`, else the org's `default_tier`.
The tier must be available in the quote and allowed for the org now (regulated: never `auto`/`ai_review`), else 422 `tier_not_allowed`. `account_id` defaults to the quote's account. Quote revenue is split across jobs to the cent. Each job freezes its workflow snapshot (`job.workflow`).

`File`: `{id, filename, format, source_lang, size, segment_count, word_count, warnings[], created_at}`.

`Quote`: `{id, file_id, source_lang, target_langs, content_type, word_count, currency, status: open|accepted|expired, valid_until, created_at, account_id, price_list_id, analysis, tiers}`.
- `analysis`: `{tm_context, tm_exact, tm_fuzzy, new, repetitions, bands{}, weighted_words, by_lang: {<lang>: {bands, weighted_words, est_auto_rate, auto_rate_source: prior|history}}, note}` (word counts summed across target languages).
- `tiers`: `{auto|ai_review|hybrid|full: {price, rate_per_word (null when languages differ), est_auto_rate, eta_hours, available, blocked_reason?, rates_by_lang?: {<lang>: {per_word, rule: pair|target|tier|org_default}}}}`. `rates_by_lang` only with a price list.

`Project`: `{id, name, quote_id, source_lang, target_langs, tier, content_type, due_at, account_id, workflow_template_id, created_at, jobs?: Job[]}`.

`Job`: `{id, project_id, file_id, filename, source_lang, target_lang, tier, content_type, state, segment_count, word_count, auto_approved_count, review_count, ai_reviewed_count, progress, threshold, est_auto_rate, revenue, cost, margin, no_reviewer_fallback_used, failure_reason, account_id, senate_count, workflow, client_approved_at, awaiting_client_approval, due_at, started_at, delivered_at, created_at}`.
- `review_count` = segments routed to humans. `senate_count` = segments the senate deliberated on.
- `no_reviewer_fallback_used`: the org's `no_reviewer_policy` fallback was applied (disclosed in evidence).
- Client review: when the workflow has `client_review`, a finished job stays in state `review` with `awaiting_client_approval=true` until `client-approve`; there is no separate job state.

Job states (authority `services/api/arbiter/domain/states.py`): `draft, quoted, running, review, ready, merging, delivered, settled, failed, cancelled, disputed`. `running` covers extraction, TM, MT, QA, QE and senate; `review` = waiting for humans (or the client); `ready` = every segment approved, about to merge.

`Segment`: `{id, seq, source_tagged, target_tagged, state, origin, engine, tm_match, qe_score, decision, reasons[], signals{}, reviewer_id, is_control_sample, context, max_length, updated_at}`. `seq` starts at 0.
Segment states (authority states.py): `pending, translated, auto_approved, needs_review, in_review, reviewed, delivered`. Blocked segments are `needs_review` with decision `blocked`.
Decisions: `auto_approve, senate, review, blocked, reviewed, ai_reviewed, ai_fallback, unreviewed` (`unreviewed` = delivered under `no_reviewer_policy=partial` deadline rules, flagged in evidence).

## Linguistic assets

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /glossaries | cust | | list of `Glossary` |
| POST | /glossaries | pm | `{name, content_type?}` | 201 `Glossary` |
| GET | /glossaries/{id}/terms | cust | `?q=&source_lang=&target_lang=` | list of current `Term` |
| POST | /glossaries/{id}/terms | pm | `{source_lang, target_lang, source_term, target_term?, kind="mandatory", case_sensitive?, note?}` | 201 `Term` |
| PATCH | /terms/{id} | pm | any Term field | successor `Term` (new id; old row closed, history kept). 409 if already retired |
| DELETE | /terms/{id} | pm | | 204 (retires; bumps version) |
| POST | /glossaries/{id}/import | pm | multipart `file` (.csv/.tsv/.tbx), `source_lang?`, `target_lang?` | `{imported, skipped, errors[]}`; TBX source language from form or root `xml:lang`. Limit 100 MB |
| GET | /glossaries/{id}/export | cust | `?format=csv\|tbx` | file |
| POST | /tm/import | pm | multipart `file` (.tmx), `rights_confirmed=true`, `source_lang?`, `content_type?` | `{imported, skipped, ...}`; 422 `rights_not_confirmed` without the flag |
| GET | /tm/search | cust | `?q=&source_lang=&target_lang=&limit<=50` | `{items: [{entry_id, kind, score, source_tagged, target_tagged}], next_offset: null}` |
| GET | /tm/export | cust | `?source_lang=&target_lang=` | TMX |
| GET | /term-questions | cust | `?status=open\|answered\|dismissed` | list of `TermQuestion` |
| POST | /term-questions/{id}/answer | pm | `{answer, add_to_glossary_id?}` | `TermQuestion` (optionally adds a mandatory term) |

`Glossary`: `{id, name, content_type, version, term_count, created_at}`. `version` is the org-wide glossary version (D-016).
`Term`: `{id, glossary_id, source_lang, target_lang, source_term, target_term, kind: mandatory|preferred|forbidden|do_not_translate, case_sensitive, note, valid_from, valid_to}` (`valid_from`/`valid_to` are glossary version numbers). For `forbidden`, `target_term` is the forbidden target word; null means the source term itself is forbidden in the target (D-017).
`TermQuestion`: `{id, source_term, source_lang, target_lang, options[], status, answer, job_id, segment_id, created_at}`.

## Quality

| Method | Path | Role | Returns |
|---|---|---|---|
| GET | /quality/dashboard | cust | `{window_days: 30, segments, auto_approved, auto_rate, escaped_errors, escaped_rate, control_samples: {total, pending, ok, escaped}, thresholds[], engines[]}` |
| GET | /quality/thresholds | cust | list of `Threshold` |

Rates are `null` when there is nothing to divide by.
`Threshold`: `{id, content_type, target_lang, value, band_width, safety_offset, auto_approval_suspended, suspended_reason, last_calibrated_at}`.
Engine row: `{engine, source_lang, target_lang, domain, segments_measured, mean_qe, mean_edit_distance, term_adherence, updated_at}` (only pairs the org uses).

## Reviewers (community)

| Method | Path | Role | Body | Returns |
|---|---|---|---|---|
| POST | /reviewers/apply | public | `{name, email, password, country(2), pairs: [{source_lang, target_lang}], domains[]}` | 201 `{token, user, profile}` |
| GET | /reviewer/me | rev | | `ReviewerProfile` |
| PATCH | /reviewer/me | rev | `{legal_name?, tax_id?, address?, date_of_birth?, country?, payout_method?: sepa\|wise\|paypal, payout_details?}` | `ReviewerProfile` |
| GET | /reviewer/tests | rev | | list of `{id, kind: language\|practical, source_lang, target_lang, domain, time_limit_min, pass_mark, item_count, status: available\|passed\|failed\|locked, retest_after}` |
| POST | /reviewer/tests/{id}/start | rev (applied/active) | | `{attempt_id, test_id, kind, items: [{index, source, target}], time_limit_min, expires_at}` |
| POST | /reviewer/attempts/{id}/submit | rev (applied/active) | `{answers: [{index, target?, errors: [{span, category, severity}]}]}` | `{score, passed, late?}` |
| POST | /reviewer/tasks/next | rev (active) | `{source_lang?, target_lang?}` | `Task`, or 204 when none |
| POST | /reviewer/tasks/{id}/submit | rev (active) | `{decision: accept\|edit\|escalate\|skip, target_tagged?, errors?: [{dimension, severity, span, explanation}], comment?, time_ms}` | `{ok, pay_amount, state}` |
| POST | /reviewer/tasks/{id}/release | rev (active) | | 204 |
| GET | /reviewer/earnings | rev | | `{currency, balance, pending, paid, payout_threshold, entries: [{id, kind, amount, currency, ref, created_at}], rejected_tasks: [{task_id, state, submitted_at}]}` |
| POST | /reviewer/disputes | rev (not banned) | `{task_id, reason}` | 201 `{id, due_at, status}` |

Reviewer statuses: `applied, active, suspended, banned`. Levels: `candidate, reviewer, senior, domain_expert`. Error `span` is a string (the quoted text).
`ReviewerProfile`: `{id, user_id, name, email, level, status, score, pairs: [{source_lang, target_lang, status, score}], domains, country, balance, payout_threshold, payout_method, tax_info_complete, decisions_total, fraud_flags, created_at}`.
`Task`: `{id, segment_id, source_lang, target_lang, domain, source_tagged, target_tagged, context_before, context_after, terms: [{source_term, target_term, kind}], qe_score, flagged_errors[], word_count, hold_expires_at, pay_estimate, pay_estimate_edit}`. `context_before`/`context_after` are the neighbouring source segments as strings (or null). Control samples are never marked.

## Admin (platform operator)

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /admin/reviewers | admin | `?status=applied\|active\|suspended\|banned` | list of `ReviewerProfile` |
| POST | /admin/reviewers/{id}/status | admin | `{status, level?}` | `ReviewerProfile` |
| GET | /admin/disputes | admin | `?status=open\|upheld\|overturned\|expired` | list of `Dispute` |
| POST | /admin/disputes/{id}/decide | admin | `{outcome: upheld\|overturned, note?}` | `Dispute` |
| GET | /admin/payouts | admin | `?state=accrued\|blocked\|sent\|settled\|failed` | list of `Payout` |
| POST | /admin/payouts/run | admin | | `{created, total, blocked, retried, payouts[], provider, send, note?}` |
| GET | /admin/orgs | admin | | list of `Org` + `{kind, created_at, usage: {period, words, jobs}}` |
| GET | /admin/metrics/queue | admin | | `{at, totals: {ready, running, done, dead}, due_now, oldest_due_age_seconds, expired_leases, by_kind: {kind: {ready, running, done, dead}}, emails: {status: n}}` |
| POST | /admin/tests | admin | `{kind, source_lang, target_lang, domain?, items: [{source, target, errors: [{span, category, severity: neutral\|minor\|major\|critical}], reference?}], pass_mark=80, time_limit_min=45, active=true}` | 201 test |

`Dispute`: `{id, task_id, reviewer_id, reason, status, decided_by, decision_note, due_at, created_at, decided_at}`.
`Payout`: `{id, reviewer_id, amount, currency, state, method, provider_ref, failure_reason, created_at, sent_at}`.
Payouts: in dev/test/staging a mock provider "sends" them. **In production no payout provider is integrated yet: `run` only accrues** (`provider: null`, `send: null`, `note` explains). Real payouts need a provider integration before launch.

## Integrations and billing

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /webhooks | pm | | list of `{id, url, events, active, disabled_reason, created_at}` |
| POST | /webhooks | pm | `{url, events[]}` | 201 webhook + `secret` (shown once). https only outside dev/test; no localhost/private IPs |
| DELETE | /webhooks/{id} | pm | | 204 |
| GET | /usage | cust | `?period=YYYY-MM` | `{period, words, ai_units, review_decisions, storage_gb, amount, currency}` |
| GET | /invoices | cust | | list of `{id, number, period, lines[], subtotal, tax, tax_rate, tax_note, total, currency, status, issued_at, created_at}` |

Webhook events: `job.delivered, job.failed, job.needs_attention, quote.expired`. `job.needs_attention` reasons: `human_review`, `client_review`, `deadline`, `budget_exceeded` (with `providers`). Delivery is at-least-once; receivers dedupe on `event_id`. Signature header `Arbiter-Signature: t=<unix>,v1=<hex hmac sha256 of "t.body">`.

## Engines (module `engine`)

Every route below answers 404 `module_disabled` when the org has not enabled the `engine` module. Writes need the `engines.manage` permission (role pm; API keys do not have it).

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /engines/catalog | cust | | `{items: CatalogEntry[], processing_region, currency, note}` |
| GET | /engines/preview | pm | `?source_lang&target_lang&content_type=general` | `{processing_region, purposes: {mt\|judge\|senate\|editor: {ok, engines[], source, skipped} \| {ok: false, code: no_eu_engine\|budget_exceeded\|no_engine, message}}}` |
| GET | /engines | engines.manage | | list of `Credential` (org BYOK keys) |
| POST | /engines | engines.manage | `{provider, label?, secret: string \| {field: value}, config?: {}, enabled=true}` | 201 `Credential`. Needs the `byok` add-on. The secret is encrypted and never returned |
| PATCH | /engines/{id} | engines.manage | `{label?, secret?, config?, enabled?}` | `Credential`. A new secret clears the last test result |
| DELETE | /engines/{id} | engines.manage | | 204 |
| POST | /engines/{id}/test | engines.manage | | `{ok, error, detail, credential}`. One tiny real call (never in the test environment); result stored on the credential |
| GET | /engines/routes | engines.manage | | list of `Route` (this org's rules) |
| POST | /engines/routes | engines.manage | `{purpose=mt, source_lang?, target_lang?, content_type?, engines[1..10], fallback=true, enabled=true, note?}` | 201 `Route` |
| PATCH | /engines/routes/{id} | engines.manage | same fields, all optional | `Route` |
| DELETE | /engines/routes/{id} | engines.manage | | 204 |
| GET | /engines/budgets | engines.manage | | list of `Budget` |
| PUT | /engines/budgets/{provider} | engines.manage | `{monthly_cap: decimal >= 0, enabled=true}` | `Budget` (upsert) |
| DELETE | /engines/budgets/{provider} | engines.manage | | 204; 404 when none |

`CatalogEntry`: `{provider, name, capabilities: [llm|mt|training], glossary, regions: [eu|us|global], models[], secret_fields[], config_fields[], price: {unit, input, output|null}, model_prices: {model: price}, configured: org|platform|env|none}`. Prices are estimates (pricing.py).
`Credential`: `{id, scope: org|platform, provider, label, secret_hint ("...WXYZ"), config, enabled, engine (provider name, or compat:<id> for openai_compatible), created_at, last_tested_at, last_test_ok, last_test_error}`.
Providers and secret fields: `anthropic`, `openai`, `deepl`, `google` (`api_key`); `bedrock` (`access_key_id`, `secret_access_key`; config `model`, `aws_region`); `vertex` (`service_account_json`; config `model`, `project`, `location`, `endpoint`); `openai_compatible` (`api_key`, may be empty; config `endpoint`, `model`, `region`, `json_mode`, `price_in_per_m`, `price_out_per_m`); `together`, `fireworks` (`api_key`; fireworks config `account_id`). Org endpoints must be public https hosts in prod; platform endpoints may be private.
`Route`: `{id, scope, source_lang, target_lang, content_type, purpose: mt|judge|senate|editor, engines[], fallback, enabled, note}`. Null match fields mean "any".
`Budget`: `{id, provider, monthly_cap, currency, period (YYYY-MM), spent, remaining, exceeded, enabled}` (money as decimal strings).

Engine names (routes, scoreboard, provenance): `mock-mt`, `mock-llm`, `anthropic`, `openai`, `bedrock`, `vertex`, `deepl`, `google`, `compat:<credential id>`, `custom:<custom model id>`, `llm-mt:<llm name>`.

Resolution of a provider key for a call: org BYOK > platform key in the database > environment variable. Routing for a job: org route > platform route (more matching fields first) > scoreboard > settings default > anything available; then the processing-region filter (eu: only `eu` engines, never a fallback outside) and the budget filter. A job of an EU org without an EU engine fails with `no EU engine configured`; a job whose engines are all at their cap stays `running`, gets a `job.needs_attention` webhook (`budget_exceeded`) and retries every hour.

### Platform engines (admin)

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /admin/engines/catalog | admin | | catalog with `configured: platform\|env\|none` |
| GET / POST | /admin/engines | admin | as /engines | platform `Credential`s (scope platform) |
| PATCH / DELETE | /admin/engines/{id} | admin | as /engines/{id} | |
| POST | /admin/engines/{id}/test | admin | | as /engines/{id}/test |
| GET / POST | /admin/engines/routes | admin | as /engines/routes | platform default routes (org_id null) |
| PATCH / DELETE | /admin/engines/routes/{id} | admin | | |

## Own models (module `engine`, add-on `custom_models`)

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| POST | /training/datasets/preview | pm | `{source_lang, target_lang, domain=general}` | `{candidates, examples, train, validation, dropped, train_words, train_tokens_estimate, min_examples, enough, consent, estimated_cost: {provider: decimal}, currency}` (counts only; works without consent) |
| GET | /training/jobs | pm | | list of `TrainingJob` |
| POST | /training/jobs | engines.manage | `{source_lang, target_lang, domain=general, provider: manual\|together\|fireworks, base_model}` | 201 `TrainingJob`. 422 `training_consent_required` without `org.training_consent`; 422 when fewer than `ARBITER_TRAINING_MIN_EXAMPLES` examples; EU orgs only with `manual` |
| GET | /training/jobs/{id} | pm | | `TrainingJob` |
| POST | /training/jobs/{id}/refresh | engines.manage | | `TrainingJob` (polls the provider once; the worker also polls via `training.poll`) |
| GET | /training/jobs/{id}/dataset | engines.manage | `?split=train\|validation` | JSONL file (chat format) |
| GET | /custom-models | pm | | list of `CustomModel` with `scoreboard` |
| POST | /custom-models | engines.manage | `{name, source_lang, target_lang, domain?, endpoint, provider_model_id, credential_id?, region: eu\|us\|global, base_model?, training_job_id?}` | 201 `CustomModel` (with `training_job_id` of an exported job: the job moves to `evaluating`) |
| POST | /custom-models/{id}/activate | engines.manage | | `CustomModel` (active: may compete in routing) |
| POST | /custom-models/{id}/deactivate | engines.manage | | `CustomModel` |

`TrainingJob`: `{id, source_lang, target_lang, domain, provider, base_model, state: created|running|evaluating|ready|exported|failed|cancelled, dataset_stats, cost, currency, result_model_id, endpoint, custom_model_id, error, created_at, finished_at}`.
`CustomModel`: `{id, engine ("custom:<id>"), name, source_lang, target_lang, domain, base_model, provider_model_id, endpoint, region, active, training_job_id, scoreboard: {mean_qe, mean_edit_distance, segments_measured}|null, created_at}`.

---

# Agency OS (PM / CRM / workflows / dashboards / AI assistant)

The business layer an agency or a localization team runs on (the part Plunet-like systems cover), plus an AI assistant that configures it from a plain-language description. Roles: **pm** unless stated. Dashboard reads are open to **cust** (money hidden for `client`).

**DELETE semantics.** Accounts, workflows and price lists are **archived** (returned with archived status; references keep working). Deals and dashboards are **deleted** (response is the object as it was). Contacts are deleted with 204.

## CRM

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /crm/accounts | `?kind=client\|prospect&status=active(default)\|archived&q=` | list of `Account` |
| POST | /crm/accounts | `{name, kind="client", industry?, country?, vat_id?, currency?, default_tier?, workflow_template_id?, price_list_id?, notes?}` | 201 `AccountDetail` |
| GET | /crm/accounts/{id} | | `AccountDetail` |
| PATCH | /crm/accounts/{id} | any Account field incl. `status` | `AccountDetail` |
| DELETE | /crm/accounts/{id} | | `AccountDetail` with `status: archived` |
| GET | /crm/accounts/{id}/contacts | | list of `Contact` |
| POST | /crm/accounts/{id}/contacts | `{name, email?, phone?, role?, is_primary?}` | 201 `Contact` |
| PATCH | /crm/contacts/{id} | Contact fields | `Contact` |
| DELETE | /crm/contacts/{id} | | 204 |
| GET | /crm/deals | `?stage=&account_id=` | list of `Deal` |
| POST | /crm/deals | `{account_id, title, value, currency?, stage="lead", expected_close?, quote_id?}` | 201 `Deal` |
| PATCH | /crm/deals/{id} | `{stage?, value?, title?, expected_close?, lost_reason?}` | `Deal` |
| DELETE | /crm/deals/{id} | | the deleted `Deal` |
| GET | /crm/activities | `?account_id=&deal_id=&open=true\|false` | list of `Activity` (open: by due date) |
| POST | /crm/activities | `{account_id, deal_id?, kind: note\|call\|email\|meeting\|task, body, due_at?}` | 201 `Activity` |
| PATCH | /crm/activities/{id} | `{done?, body?, due_at?}` | `Activity` |

Request bodies reject unknown fields.
`Account`: `{id, name, kind, status: active|archived, industry, country, vat_id, currency, default_tier, workflow_template_id, price_list_id, owner_user_id, notes, created_at}`.
`AccountDetail`: `Account` + `{contacts[], deals[], recent_activities[], stats: {projects, jobs_active, revenue_total, revenue_90d, margin_90d}}`.
`Contact`: `{id, account_id, name, email, phone, role, is_primary, created_at}`.
`Deal`: `{id, account_id, account_name, title, value, currency, stage: lead|qualified|proposal|negotiation|won|lost, expected_close, quote_id, lost_reason, owner_user_id, closed_at, created_at, updated_at}`.
`Activity`: `{id, account_id, deal_id, kind, body, due_at, done, done_at, user_id, created_at}`.

## Price lists

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /price-lists | `?include_archived=false` | list of `PriceList` |
| POST | /price-lists | `{name, currency="EUR", rates: [{source_lang?, target_lang?, tier, per_word}], tm_weights?: {context, exact, fuzzy_95, fuzzy_85, fuzzy_75, new, repetition}, minimum_charge?}` | 201 `PriceList` |
| GET | /price-lists/{id} | | `PriceList` (archived too) |
| PATCH | /price-lists/{id} | same fields, optional | `PriceList` |
| DELETE | /price-lists/{id} | | `PriceList` with `archived: true` |

`PriceList`: `{id, name, currency, rates[], tm_weights, minimum_charge, archived, created_at, updated_at}`. Rates are stored as decimal strings.
Quotes use the account's price list when `POST /quotes` carries `account_id` (archived list: org default rates). Rate lookup per language and tier: exact pair, then target-only, then tier-only, then org default; the matched rule is reported in `rates_by_lang`.

## Workflow templates

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /workflows | `?include_archived=false` | list of `Workflow` (first call seeds the built-in presets) |
| POST | /workflows | `{name, description?, content_type?, tier, steps: Step[], is_default?}` | 201 `Workflow` |
| GET | /workflows/{id} | | `Workflow` (archived too) |
| PATCH | /workflows/{id} | same fields, optional | `Workflow` |
| DELETE | /workflows/{id} | | `Workflow` with `archived: true` (running jobs keep their snapshot) |

`Workflow`: `{id, name, description, content_type, tier, steps: [{kind, params}], is_default, preset, archived, available, blocked_reason, created_at, updated_at}`. `available=false` for humanless tiers in a regulated org.
Presets: `machine_only` (auto), `ai_reviewed` (ai_review), `hybrid`, `full_review` (full).

`Step.kind`: `tm` (TM pre-translation), `mt` (`params.engine?`), `translation_senate` (best-of-N), `qe` (`params.threshold?` 0..100), `senate` (band review), `ai_review` (senate + AI editor), `human_review` (`params.min_level?`: reviewer|senior|domain_expert), `second_review` (a second, senior human, never the first reviewer), `client_review` (job waits for the client's approval), `delivery`.
Validation (422 `workflow_invalid`): contains `tm`, `mt` or `translation_senate` (TM-only needs `human_review`); each kind at most once; `delivery` present and last; translation steps before `qe`; `qe` before any review step; `second_review` after `human_review`; tier consistency (`full` needs `human_review`; `auto` has no human/AI review; `ai_review` has no human review); regulated orgs reject `auto`/`ai_review`.

## Dashboards

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /dashboards | cust | | list of `Dashboard` |
| POST | /dashboards | pm | `{name, widgets: Widget[]}` | 201 `Dashboard` |
| GET | /dashboards/default | cust | | the org's default `Dashboard` (created on first call) |
| GET | /dashboards/{id} | cust | | `Dashboard` |
| PATCH | /dashboards/{id} | pm | `{name?, widgets?}` | `Dashboard` |
| DELETE | /dashboards/{id} | pm | | the deleted `Dashboard` |
| GET | /dashboards/{id}/data | cust | `?period=30d\|90d\|365d` | `DashboardData` |

`Dashboard`: `{id, name, widgets[], is_default, created_at, updated_at}`.
`Widget`: `{id, type: kpi|bar|line|table|pipeline, metric, title?, size: s|m|l}`. Metrics:
- kpi: `revenue`, `margin`, `margin_pct`, `jobs_active`, `jobs_overdue`, `auto_rate`, `escaped_rate`, `open_deals_value`, `words_delivered`, `reviewer_cost`
- bar/line: `revenue_by_month`, `jobs_by_state`, `revenue_by_account`, `words_by_pair`, `auto_rate_by_month`
- pipeline: `deals_by_stage`
- table: `overdue_jobs`, `top_accounts`, `open_activities`, `recent_deliveries`

`DashboardData`: `{period, currency, generated_at, widgets: [{id, type, title, data}]}` where `data` is:
- kpi: `{value, unit, previous}` (previous = same-length period before)
- bar/line: `{unit, points: [{label, value}]}`
- pipeline: `{currency, stages: [{stage, count, value}]}`
- table: `{columns[], rows: [{...}]}`

Revenue is recognised at delivery. Rates are null without data. Money is null for the client role.

## AI assistant

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /assistant/threads | `{title?}` | 201 `Thread` |
| GET | /assistant/threads | | list of `Thread` |
| GET | /assistant/threads/{id} | | `Thread` with `messages[]` |
| POST | /assistant/threads/{id}/messages | `{content, locale?}` | 201 `{user_message, assistant_message}` |
| POST | /assistant/messages/{id}/apply | `{actions?: int[]}` (indices; default all) | `{results: [{index, type, ok, id?, error?, skipped?, note?, warnings?}], message}` |

`Thread`: `{id, title, user_id, created_at, updated_at, messages?}`.
`Message`: `{id, thread_id, role: user|assistant, content, plan: Action[] | null, applied: int[], results: {"<index>": {id}}, created_at}`.
`Action`: `{type, summary, data}` with type in `create_workflow, create_price_list, create_account, create_contact, create_deal, create_activity, create_dashboard, update_org, create_glossary, add_terms, create_webhook, create_assignment, draft_quote` (the last two need the pm module, see "Vendors"). `data` is validated with the same models as the matching endpoint. An id field may reference an earlier action of the same plan as `"@<index>"` (e.g. `account_id: "@0"`).

`locale` is a BCP-47 tag (default `"en"`; the web app sends the UI locale; invalid tag = 422). The reply, every action `summary` and every name the assistant chooses (workflow, price list and dashboard names, descriptions, widget titles) are in that locale, whatever language the user wrote in; proper names the user gave (agency, clients, contacts, e-mails) are kept verbatim. The built-in planner (used when no AI model is configured) understands English and Serbian input but always answers in English; for any other locale its reply ends with a note that only the AI model localizes replies (D-045).

The assistant never changes anything by itself: posting a message only proposes a plan; a human applies all or selected actions. Each action runs in its own savepoint (one failure does not undo the others); already applied indices are skipped; workflows, price lists and dashboards with an existing name are reused (`note` says so). Apply on a message without a plan is 409. The assistant also answers questions about the org's data from a context summary.

PM copilot (module pm, D-071): four project-management questions are answered from the database before the model is asked, and the result is sent to the model as `context.pm.query` (the built-in planner answers from it directly). English and Serbian input:
- capacity: "who is free for EN->DE 20k words by Friday" -> planner rows (no plan)
- risk: "which jobs are at risk" -> deadline risk rows (no plan)
- propose assignments: "propose assignments for job job_..." (or the project name) -> plan `create_assignment {job_id, step, mode: vendor, vendor_ids (best three, ranked), strategy: sequential}`; applying it sends the offer like `POST /jobs/{id}/assignments`
- draft quote: "draft a quote for <client>: 5000 words EN->DE" -> plan `draft_quote {account_id, source_lang, target_langs, words, tier, file_id?}` priced from the client's price list; applying it creates a CRM deal in stage `proposal` with the estimate (and a real quote when `file_id` is given)
Missing pieces (pair, words, client, job) are asked for in the reply.

## Vendors (module pm)

The agency's own translators, reviewers and partner agencies, separate from the reviewer marketplace. Every route needs the `pm` module (404 `module_disabled`) and the pm role or an API key; writes need the permission `vendors.manage` (pm role and admin by default). Objects of another org are 404. Money is decimal strings with the currency next to it.

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /vendors | `?q, status, source_lang, target_lang, service` | list of `Vendor` (+ `open_assignments`) |
| POST | /vendors | `VendorIn` | 201 `Vendor` |
| POST | /vendors/import | multipart `file` (CSV, header row, at most 5 MB) | `{created, updated, errors: [{row, error}]}` |
| GET | /vendors/{id} | | `Vendor` + `absences[]`, `documents[]`, `assignments[]` (last 50) |
| PATCH | /vendors/{id} | `VendorIn` fields, optional | `Vendor` |
| DELETE | /vendors/{id} | | `Vendor` with `status: inactive` (never deleted) |
| POST / DELETE | /vendors/{id}/absences[/{absence_id}] | `{start_date, end_date, note?}` | 201 `Absence` / 204 |
| POST / DELETE | /vendors/{id}/documents[/{document_id}] | `{kind: nda\|contract\|certificate\|other, title, signed, signed_at?, valid_until?}` | 201 `Document` / 204 (a signed NDA sets `nda_signed`) |
| GET | /vendors/{id}/calendar | `?start, days<=62` | `{vendor_id, start, days: [Day], assignments[]}` |
| GET | /jobs/{id}/assignments | | `{job_id, routes: {human_review?, second_review?: {mode, assignment_id, status}}, items: [Assignment + link]}` |
| GET | /jobs/{id}/assignment-suggestions | `?step=human_review\|second_review` | `{job_id, step, words, due_at, items: [CapacityRow]}` |
| POST | /jobs/{id}/assignments | `AssignmentIn` (Idempotency-Key honoured) | 201 `{job_id, step, mode, items: [Assignment + link]}` |
| GET | /assignments | `?status (comma list), vendor_id, job_id` | list of `Assignment` |
| GET | /assignments/{id} | | `Assignment` + `link` |
| POST | /assignments/{id}/approve | | `Assignment` (delivered -> approved; fee added to the job cost) |
| POST | /assignments/{id}/reopen | `{note?}` | `Assignment` (delivered -> in_progress) |
| POST | /assignments/{id}/cancel | | `Assignment`; the step goes back to the marketplace |
| GET | /purchase-orders | `?vendor_id, status, job_id` | list of `PurchaseOrder` |
| GET | /purchase-orders/{id}[/pdf] | | `PurchaseOrder` / PDF |
| GET | /vendor-invoices | `?vendor_id, status, period=YYYY-MM` | list of `VendorInvoice` |
| POST | /vendor-invoices | multipart `file, vendor_id, number, assignment_ids (comma list), total?, note?` | 201 `VendorInvoice` (source `upload`) |
| POST | /vendor-invoices/auto | `{vendor_id?, period?}` | `{items: [VendorInvoice]}` one per vendor and currency from approved, not invoiced assignments |
| GET | /vendor-invoices/{id}[/file] | | `VendorInvoice` / the uploaded file |
| POST | /vendor-invoices/{id}/approve\|reject\|pay | `{note?}` | `VendorInvoice` (reject: the assignments can be invoiced again) |
| GET | /vendor-invoices/export.csv | `?period` | CSV for accounting (number, source, status, period, dates, vendor, legal name, tax id, IBAN, PO numbers, currency, total) |
| GET | /payables | `?period=YYYY-MM` (default this month) | `{period, items: [{vendor_id, vendor_name, currency, accrued, invoiced, paid, open}], totals: [...]}` |
| GET | /capacity | `?source_lang, target_lang, words, by?, service?` | `{items: [CapacityRow]}` ranked |
| GET | /pm/deadline-risk | `?only_at_risk=false` | `{items: [Risk]}` |
| GET | /pm/timeline | `?start, days<=62 (14)` | `{start, days[], vendors: [{vendor_id, name, capacity_words_per_day, days: [Day]}], assignments[], jobs[]}` |

`VendorIn`: `{name, kind: person|company, email?, phone?, country?, status: active|inactive|blocked, pairs: [{source_lang, target_lang, services: [translation|review|post-edit|dtp]}], domains[], rates: [{source_lang?, target_lang?, service, unit: word|hour|page|minimum, rate, currency?}], currency, rating? (0..5), notes, legal_name?, tax_id?, address?, payment_method?, iban?, swift?, payment_terms_days, capacity_words_per_day, working_days: [0=Mon..6=Sun], timezone?, nda_signed, nda_signed_at?}`. Rate lookup: exact pair, then target only, then any pair; a `minimum` rate is the least paid per assignment.

`AssignmentIn`: `{step: human_review|second_review, mode: marketplace|vendor|internal, vendor_ids[] (vendor, ranked, max 10), user_id (internal), strategy: sequential|broadcast, offer_timeout_minutes (5..10080, default 240), due_at?, words?, service?, rate?, unit?, quantity?, note?}`. `mode: marketplace` ends every live assignment of the step (default route). A job without that human step is 422; a delivered assignment must be approved or sent back first (409); the second review never goes to the vendor of the first review (422).

`Assignment`: `{id, job_id, step, service, assignee_kind: vendor|internal, vendor_id, vendor_name, user_id, user_name, offer_group, rank, strategy, words, words_done, unit, quantity, rate, amount, currency, status, due_at, offered_at, offer_expires_at, responded_at, started_at, delivered_at, approved_at, po_id, po_number, note, messages: [{at, to, subject, channel: email|log}], created_at}`. Status: `pending` (later in a sequential list), `offered`, `accepted`, `in_progress`, `delivered`, `approved`, `invoiced`; off ramps `declined`, `expired` (offer timeout), `withdrawn` (someone else accepted or the route changed), `cancelled`.

Routing: while an assignment of a step is live (`pending`..`delivered`) the pipeline creates no marketplace review tasks for that step; open segments carry `signals.route = <assignment id>`. Sequential offers move to the next rank on decline or timeout; when nobody is left the step returns to the marketplace and `job.needs_attention` fires with `reason: vendor_unassigned`. Delivery fires `job.needs_attention` with `reason: vendor_delivered`. Job `cost` (and so `margin`) includes approved vendor fees in the platform currency; a fee in another currency is recorded in provenance, not converted.

`CapacityRow`: `{vendor_id, name, kind, email, capacity_words_per_day, free_words, earliest_finish, can_meet, absent_days[], price: {amount, rate, unit, currency} | null, rating, nda_signed, eligible, rank}`.
`Risk`: `{job_id, project_id, project, source_lang, target_lang, state, due_at, remaining_words, estimated_finish, slack_hours, routes: {step: {route: marketplace|internal|vendor, words, words_per_day, ...}}, at_risk, reasons[]}`. `/exceptions` lists at-risk jobs as kind `deadline_risk`.
`Day`: `{date, capacity, load, free, absent, working, assignments[]}`.
`PurchaseOrder`: `{id, number (PO-YYYY-NNNN per org), vendor_id, vendor_name, assignment_id, job_id, lines: [{description, quantity, unit, rate, amount}], total, currency, status: issued|invoiced|cancelled, due_at, issued_at, vendor_invoice_id}`.
`VendorInvoice`: `{id, vendor_id, vendor_name, number, source: auto|upload, period, assignment_ids[], lines[], total, currency, status: received|approved|rejected|paid, filename, has_file, note, due_date, received_at, approved_at, paid_at}`.

### Vendor workbench (no login)

The offer e-mail carries `{ARBITER_WEB_BASE_URL}/vendor/<token>`; the token (HS256, audience `arbiter-vendor-portal`, revoked when the assignment is withdrawn or cancelled) opens one assignment only. Bad, expired or revoked tokens and orgs without the pm module are 404.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /vendor-portal/{token} | | `{assignment, organization, job, segments: [{id, seq, source_tagged, target_tagged, context_before, context_after, terms, qe_score, flagged_errors, word_count, state, done}], remaining}` (segments once accepted; no client money) |
| POST | /vendor-portal/{token}/accept | | portal view; first to accept wins (409 when taken or expired), issues the PO |
| POST | /vendor-portal/{token}/decline | `{reason?}` | portal view; the next rank is offered |
| POST | /vendor-portal/{token}/segments/{segment_id} | `{decision: accept\|edit, target_tagged?, errors?, comment?}` | `{ok, remaining, status}`; same hook as a reviewer; tag-breaking edits 422 (D-009) |
| POST | /vendor-portal/{token}/complete | | portal view (409 while segments are left or the job is still being scored) |
| GET | /vendor-portal/{token}/po.pdf | | PDF |
| POST | /vendor-portal/{token}/invoice | multipart `number, file` | 201 `{id, number, total, currency, status}` (approved work only) |

# UI string localization (platform-wide)

The product is English-first (D-045). The English UI catalog lives in the web repo and is the source; translations are stored here per locale and edited or imported by the platform admin without a redeploy (D-046). Locales are BCP-47, normalised on input (`pt-br` -> `pt-BR`, `sr-latn` -> `sr-Latn`); a malformed tag is 422.

| Method | Path | Auth | Body | Returns |
|---|---|---|---|---|
| GET | /i18n/locales | none (admin sees disabled too) | | `{items: [Locale]}`, `en` always first |
| GET | /i18n/messages/{locale} | none (admin can read disabled) | | `{locale, messages: {key: value}}`, `Cache-Control: public, max-age=60`; 404 for unknown or disabled; `en` returns `{}` |
| PUT | /admin/i18n/locales/{locale} | admin | `{name, enabled?}` | `Locale` (created disabled unless `enabled: true`) |
| PUT | /admin/i18n/messages/{locale} | admin | `{messages: {key: value}, mode?: merge\|replace, source?: {key: english}}` | `{locale, upserted, deleted, total}` |
| DELETE | /admin/i18n/locales/{locale} | admin | | 204 (messages deleted too) |

`Locale`: `{locale, name, enabled, message_count, updated_at}`; for `en`: `{locale: "en", name: "English", enabled: true, message_count: null, updated_at: null}`.

Messages import rules:
- `merge` (default) upserts the given keys; `replace` leaves the locale with exactly the given keys. An empty string value removes that key. `upserted` counts new or changed values only.
- Key 1-200 characters, value at most 5000 characters, at most 20,000 keys per request (422 otherwise).
- A locale without a row is created on import, disabled, named after its tag.
- `en` cannot be written (422): it is the source catalog.
- Placeholder safety: when `source` is given, every key present in both must use the same set of top-level ICU arguments (`{name}`, and the argument of `{count, plural, ...}` / `{x, select, ...}`; text inside plural branches is not an argument; `'{...}'` is quoted literal text). Otherwise 422 with `details.placeholders: {key: {expected: [...], got: [...]}}` and nothing is written.


# Platform: modules, roles, team, audit log, SSO

None of these routes are module-gated. Permission checks use `require_permission("<area>.<action>")` (built-in role mapping in `arbiter/platform/permissions.py`, or the user's custom role). `user` = a signed-in person; API keys get 403 on these writes.

### Module gating

Every route of a product module carries `require_module("<module>")`; when the org has not enabled it the route answers 404 `module_disabled` (other modules keep working). Current mapping: files, quotes, projects, jobs, glossaries, terms, TM, term questions, exceptions -> `tms`; quality -> `ai`; CRM, price lists, workflows, dashboards, assistant -> `pm`. Auth, org settings, API keys, webhooks, usage, invoices, i18n and everything below are platform routes. `Org.modules` (in `/me`, `/org`, `/admin/orgs`) lists the modules that work for the org (enabled and every dependency enabled).

| Status | Code | When |
|---|---|---|
| 404 | `module_disabled` | the route belongs to a module the org has not enabled |
| 401 | `sso_failed` | SSO callback rejected (state expired or reused, token exchange failed, id_token invalid) |
| 403 | `sso_required` | password login for a member of an org that enforces SSO |

| Method | Path | Auth | Body / query | Returns |
|---|---|---|---|---|
| GET | /org/modules | cust | | `{enabled: [key], catalog: [{key, name, depends_on, enabled}]}` |
| GET | /admin/orgs/{id} | admin | | `Org` + `kind`, `catalog` |
| PUT | /admin/orgs/{id}/modules | admin | `{modules: [key]}` | as GET /org/modules; 422 `details.problems` for unknown keys or missing dependencies |
| GET | /roles | `users.read` | | `{items: [Role], builtin: [{key}], catalog: [{key, description}]}` |
| POST | /roles | `roles.write`, user | `{name, description?, base_role: pm\|client, permissions: [pattern]}` | 201 `Role`; 409 name taken; 422 invalid pattern; 403 granting a permission you do not hold, or a pm-based role when you are not pm |
| PATCH | /roles/{id} | `roles.write`, user | any field of POST | `Role` (base role change moves its members) |
| DELETE | /roles/{id} | `roles.write`, user | | 204; 409 while assigned or SSO default |
| GET | /users | `users.read` | paging | list of `Member` |
| POST | /users/invite | `users.write`, user | `{email, name?, role?: pm\|client, role_id?}` | 201 `{user: Member, expires_at, email_sent, invite_token?, invite_url?}` (token and url only in dev and test); 409 email exists |
| PATCH | /users/{id} | `users.write`, user | `{name?, role?, role_id?\|null, is_active?}` | `Member`; 422 changing your own role or deactivating yourself; 409 would leave no active pm |
| DELETE | /users/{id} | `users.write`, user | | 204 (deactivates; history stays) |
| POST | /auth/invite/accept | public | `{token, password(>=8), name?}` | `{token, user}`; 404 invalid, used or expired |
| GET | /audit | `audit.read` | `actor?` (user/key id or email), `action?` (exact, or prefix ending in `.` or `*`), `since?`, `until?`, paging | list of `AuditEvent`, newest first |
| GET | /audit/export | `audit.read` | same filters | CSV (`text/csv`), at most `ARBITER_AUDIT_EXPORT_MAX_ROWS` rows; the export itself is audited |
| GET | /org/sso | `org.manage` | | `SsoConfig` |
| PUT | /org/sso | `org.manage`, user | `{issuer, client_id, client_secret? (required on create, kept when omitted), allowed_domains: [domain], default_role?, default_role_id?, enforce_sso?, enabled?}` | `SsoConfig`; the issuer must answer OIDC discovery; 409 domain claimed by another org; 422 enforcing without a verified domain |
| DELETE | /org/sso | `org.manage`, user | | 204 (domains released) |
| POST | /org/sso/domains/{domain}/verify | `org.manage`, user | | `SsoConfig`; checks the TXT record `arbiter-verify=<token>` via DNS-over-HTTPS; 422 not found |
| POST | /admin/sso-domains/{domain}/verify | admin | | `SsoConfig` (manual verification) |
| GET | /auth/sso/check | public | `email` | `{sso, enforced}` for the login page |
| GET | /auth/sso/start | public | `email`, `next?` | 302 to the IdP (state, nonce, PKCE S256); 404 when the email domain has no verified SSO |
| GET | /auth/sso/callback | public | `code`, `state` | `{token, user, redirect\|null}`; JIT-provisions unknown users with the default role; 409 email belongs to another org; 403 email domain not verified for the org |

`Role`: `{id, name, description, base_role, permissions, members, created_at}`. `base_role` decides the coarse route guards (pm or client); `permissions` replace the base role's built-in permission set for `require_permission` checks. Patterns: `area.action`, `area.*`, `*.action`, `*`. `audit.read` is only granted by `*`, `audit.read` or `audit.*`, never by `*.read`.
`Member`: `{id, email, name, role, role_id, role_name, status: active|invited|deactivated, created_at}`.
`AuditEvent`: `{id, at, actor: {type: user|api_key|system, id, label}, action, target: {type, id}, ip, user_agent, data}`. The table is append-only (DB trigger). Secrets in `data` are redacted.
`SsoConfig`: `{configured, enabled, issuer, client_id, client_secret_set, default_role, default_role_id, enforce_sso, redirect_uri, domains: [{domain, verified, verified_at, txt_record}]}`. The client secret is never returned; it is stored encrypted with `ARBITER_SECRETS_KEY`.
`/me` also returns `permissions` (granted patterns) and `user.role_id`.

Audited actions so far: `org.created`, `org.updated`, `auth.login`, `auth.sso_login`, `api_key.created|revoked`, `webhook.created|deleted`, `module.changed`, `role.created|updated|deleted`, `user.invited|invite_accepted|updated|deactivated|reactivated|provisioned`, `sso.created|updated|deleted|domain_verified`, `audit.exported`, `glossary.imported`, `tm.imported`, `project.created`, `job.cancelled`, `segment.edited|approved`.


# Software strings (module `strings`)

Key-value localization for apps and websites, on the same engines, TM, glossary, QE and reviewer community as documents (D-060, D-061, D-062). Every `/v1/strings` route requires the `strings` module (404 `module_disabled` otherwise) and a permission: `strings.read` (pm, client, API key), `strings.write` (pm, API key), `strings.publish` (pm, API key; releases and distribution tokens). Branch parameters accept a branch id or name; omitted means `main`. Language codes are BCP-47 (`pt_br` -> `pt-BR`).

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /strings/formats | | `{items: [{name, label, extension, multilingual, bilingual}]}` |
| GET | /strings/projects | `offset, limit` | list of `StringProject` (with `stats`) |
| POST | /strings/projects | `{name, base_lang, target_langs[], platforms[], tier?, settings?}` (Idempotency-Key) | 201 `StringProject` |
| GET / PATCH / DELETE | /strings/projects/{id} | PATCH `{name?, target_langs?, platforms?, tier?, settings?}` | `StringProject`; DELETE archives (204) |
| GET | /strings/projects/{id}/keys | `branch, q, tag, namespace, lang, state (untranslated\|machine\|reviewed\|approved\|blocked\|needs_review), langs (comma list), include_archived, offset, limit<=1000` | `{items: [StringKey], total, next_offset, branch}` |
| POST | /strings/projects/{id}/keys | `?branch`; `{name, namespace?, kind: string\|plural\|array, description?, max_length?, tags?, screenshot_url?, translatable?, value? \| forms?}` | 201 `StringKey` |
| GET / PATCH | /strings/projects/{id}/keys/{key_id} | PATCH `{name?, namespace?, kind?, description?, max_length?, tags?, screenshot_url?, translatable?, archived?}` | `StringKey` |
| GET | /strings/projects/{id}/keys/{key_id}/history | `?lang` | `{items: [{event, lang, version, value, forms, state, actor_type, actor_id, at}]}` (append-only) |
| PUT | /strings/projects/{id}/keys/{key_id}/translations/{lang} | `?branch`; `{value \| forms, state?: machine\|reviewed\|approved}` | `StringKey` (QA runs; a blocking issue sets `blocked`) |
| DELETE | /strings/projects/{id}/keys/{key_id}/translations/{lang} | `?branch` | `StringKey` |
| POST | /strings/projects/{id}/keys/{key_id}/translations/{lang}/suggest | `?branch` | `{outcome, key}`: TM + engine + QA + QE for one empty translation |
| POST | /strings/projects/{id}/translate | `{branch?, langs?, mode: translate\|tm_only, key_ids?}` | 202 `StringBatch` (409 when one is running on the branch) |
| GET | /strings/projects/{id}/batches, /batches/{batch_id} | | `StringBatch` (`progress` 0-100, `counts`) |
| POST | /strings/projects/{id}/bulk | `{action: approve\|clear\|pretranslate_tm\|translate\|archive\|unarchive\|tag\|untag, branch?, key_ids?, langs?, tag?}` | `{action, changed}` or `{action, batch}` |
| GET / POST | /strings/projects/{id}/branches | POST `{name}` | `{items: [StringBranch]}` / 201 `StringBranch` |
| GET | /strings/projects/{id}/branches/{branch}/merge-preview | | `{branch, conflicts: [{key_id, key, lang, branch_value, main_value}]}` |
| POST | /strings/projects/{id}/branches/{branch}/merge | `{resolutions: {"<key_id>:<lang>": "branch"\|"main"}}` | `{applied, keys_moved, conflicts_resolved, branch}`; unresolved conflicts 409 `conflict` with `details.conflicts` |
| DELETE | /strings/projects/{id}/branches/{branch} | | 204 (not main) |
| GET / POST | /strings/projects/{id}/releases | POST `{branch?, version_label?, langs?, formats?: [format], publish=true}` (Idempotency-Key; `publish` needs strings.publish) | list / 201 `StringRelease` |
| GET | /strings/projects/{id}/releases/{release} | id or version label | `StringRelease` |
| POST | /strings/projects/{id}/releases/{release}/publish | | `StringRelease`, emits webhook `strings.release.published` |
| GET | /strings/projects/{id}/releases/{release}/files/{lang}/{format} | `lang` may be `_all` for multilingual formats | the stored file |
| POST | /strings/projects/{id}/distribution-token | | `{token, private: true}` (shown once; the project becomes private) |
| POST | /strings/projects/{id}/push | multipart `file`, `format?` (detected from the extension/content), `lang?` (default base), `branch?`, `namespace?`, `create_keys?` (default true for the base language), `update_changed=true`, `archive_missing=false`, `tag?`, `state=reviewed` | `{format, lang, branch, keys_in_file, created, updated, unchanged, archived, skipped, blocked, warnings[]}` |
| GET | /strings/projects/{id}/pull | `lang?, format?, branch?, namespace?, min_state=machine, fallback=false, include_blocked=false` | the file (multilingual formats without `lang`: every language) |

Public, no auth (mounted at the root, not under `/v1`):

| Method | Path | Notes |
|---|---|---|
| GET | /ota/{public_id}/{version_label\|release_id}/{lang}.json | published releases only; `Cache-Control: public, max-age=31536000, immutable`; `ETag` = bundle SHA-256; `If-None-Match` -> 304 |
| GET | /ota/{public_id}/latest/{lang}.json | newest published release; `Cache-Control: public, max-age=60, stale-while-revalidate=300` |
| GET | /ota/{public_id}/{ref}/manifest.json | `{project, release, version_label, published_at, content_hash, base_lang, langs: {lang: {url, sha256}}}` |

Private projects: send the distribution token as `X-Distribution-Token` or `?token=`; without it every OTA path is 404 and caching is `private`. `Access-Control-Allow-Origin: *` on all OTA responses.

Shapes:
- `StringProject`: `{id, name, public_id, base_lang, target_langs, platforms, tier, settings: {placeholder_style, plural_rules, human_review, release_min_state, fallback_to_base, private, default_format, engine}, has_distribution_token, ota_base, created_at, stats?: {keys, archived, languages: {lang: {untranslated, machine, reviewed, approved, blocked, progress}}}}`.
- `StringKey`: `{id, namespace, name, kind, description, screenshot_url, max_length, tags, translatable, archived, branch_local, placeholders[], plural_forms: {lang: [category]} | null, translations: {lang: StringTranslation | null}}`.
- `StringTranslation`: `{value, forms, state: untranslated|machine|reviewed|approved, origin: import|human|tm|mt|review, engine, qe_score, qa: [{code, severity, message, blocking, form?}], blocked, needs_review, version, updated_by, updated_at, branch_local}`. `forms` holds CLDR plural categories (and explicit `=N` selectors) or array indexes.
- `StringRelease`: `{id, version_label, status: draft|published, branch_id, langs, content_hash, key_count, files: {lang: {format: {sha256, bytes}}}, ota: {manifest, latest_manifest, langs: {lang: {versioned, latest}}} | null, created_at, published_at}`.
- OTA bundle: `{"<key>": "text", "<plural key>": {"one": "...", "other": "..."}, "<array key>": ["..."]}`; keys in a namespace are `"<namespace>:<key>"`.

Formats (`format` names): `json` (flat), `json_nested` (next-intl, vue-i18n), `i18next`, `formatjs`, `arb` (Flutter), `android` (strings.xml), `ios_strings`, `stringsdict`, `xcstrings` (multilingual), `yaml` (Rails), `po`, `pot`, `xliff12`, `xliff21` (bilingual), `csv`, `xlsx` (multilingual).

String QA codes (blocking unless noted): `empty_value`, `placeholder_changed` (a missing placeholder in a plural form is a warning), `icu_syntax`, `icu_structure`, `plural_forms_missing`, `length_exceeded`, `array_length` (warning). Machine output also gets the document hard checks (`tag_missing` etc.; placeholders travel as standalone codes). Blocked translations never ship in pulls (unless `include_blocked`) or releases.

CLI for CI: `cli/arbiter-strings.mjs` (`push`, `pull`, `release`, `status`; zero dependencies), documented in `cli/README.md`.


# Workbench, TM tools, LQA, auditor (modules `tms`, `ai`, `auditor`)

Every route below is gated by its module (`require_module`): a disabled module answers 404 `module_disabled`.

## Segment editor (module `tms`)

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /jobs/{id}/editor/segments | cust | `?state=a,b&decision=&locked=&has_comment=&open_query=&qa=&tm_band=none\|lt75\|75-84\|85-94\|95-99\|100\|101&q=&offset=&limit<=200` | list of `EditorSegment` plus `total` |
| POST | /jobs/{id}/segments/{seg}/check | cust | `{target_tagged}` | `{issues[], blocking, terms[], term_violations[]}`. Hard QA on a draft, nothing saved |
| GET | /jobs/{id}/segments/{seg}/assist | cust | | `{tm_matches: [{entry_id, kind, score, source_tagged, target_tagged, diff: [{op: equal\|delete\|insert, text}]}], terms[]}`; diff runs from the match source to this source |
| POST | /jobs/{id}/segments/{seg}/mt | pm | `{engine?}` | `{target_tagged, engine, model_version}`; org routing (scoreboard, default, workflow engine); not saved, cost added to the job |
| POST | /jobs/{id}/segments/{seg}/split | pm | `{source_offset, target_offset?}` (offsets in the tagged strings) | `{segments: [EditorSegment, EditorSegment], segment_count}`; 422 inside a code, an escape or an open pair, or without `target_offset` when the segment has a target; 422 `tag_error` when a half loses its codes |
| POST | /jobs/{id}/segments/{seg}/merge-next | pm | | `{segment, segment_count}`; only the next segment of the same unit, else 409 |
| POST | /jobs/{id}/segments/lock | pm | `{segment_ids[], locked=true}` | `{changed, locked}` |
| POST | /jobs/{id}/find-replace | cust | `{find, replace?, regex, case_sensitive, whole_word, scope: target\|source\|both, states?, segment_ids?, apply=false, force=false}` | `{items: [{segment_id, seq, state, locked, source_matches, target_matches, source_tagged, before, after, skip_reason}], total_matches, segments, changed, skipped, applied}`. Text runs only; `skip_reason`: `locked`, `approved`, `state`, `tag_error`, `unchanged`; `force` (PM only) includes locked and approved segments |
| GET | /jobs/{id}/comments | cust | `?segment_id=&kind=comment\|query&resolved=` | list of `Comment` (client: queries only) |
| POST | /jobs/{id}/comments | cust | `{body, kind=comment\|query, segment_id?, parent_id?, mentions?}` | 201 `Comment`. Clients only reply to queries (403 on a new thread). A new query emits webhook `job.query.opened` |
| PATCH | /comments/{id} | cust | `{resolved}` | the thread root `Comment` |
| GET | /queries | cust | | open query threads of the org: `Comment` + `{filename, segment_seq, source_tagged, target_tagged, replies[]}` |
| GET | /jobs/{id}/preview | cust | | `text/html` of the target document (html, markdown, docx rendered; other formats side by side); header `X-Preview-Mode: rich\|side_by_side`, CSP `sandbox` |
| GET | /tm/concordance | cust | `?q=&source_lang=&target_lang=&side=both\|source\|target&limit<=100` | `{items: [{entry_id, source_tagged, target_tagged, score, origin, updated_at}]}` |

Locks: PATCH `/jobs/{id}/segments/{seg}` and `/approve` answer 409 `segment_locked` for a locked segment unless the caller is a PM or an API key. `Segment` gains `locked`.

`EditorSegment` = `Segment` + `{unit_id, seg_index, word_count, locked, locked_by, locked_at, qa_count, comment_threads, open_queries, slots}`. `slots` maps editor splits (0 = second half of a split) and merges (k = covers k extracted segments) back onto the file (pipeline/units.py).

`Comment`: `{id, job_id, segment_id, thread_id, parent_id, kind, author_id, author_role, body, mentions[], resolved, resolved_by, resolved_at, created_at}`.

## TM tools (module `tms`)

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| GET | /tm/entries | cust | `?q=&source_lang=&target_lang=&origin=review\|import\|client&status=approved\|imported\|stale&created_from=&created_to=` | list of `TmEntry` |
| PATCH | /tm/entries/{id} | pm | `{source_tagged?, target_tagged?, status?: approved\|stale}` | `TmEntry` (source edits rehash and re-embed) |
| DELETE | /tm/entries/{id} | pm | | 204 |
| POST | /tm/entries/bulk | pm | `{ids[], action: delete\|mark_stale\|mark_approved}` | `{changed, action}` |
| POST | /tm/align | pm | multipart `source_file`, `target_file`, `source_lang`, `target_lang`, `content_type?` | 201 `Alignment` (review grid, nothing stored yet) |
| GET | /tm/align/{id} | cust | | `Alignment` |
| POST | /tm/align/{id}/commit | pm | `{rights_confirmed: true, pairs?: [{index, accepted, source?, target?}]}` | `{imported, skipped, alignment}`; 422 `rights_not_confirmed`, 409 when already committed |
| POST | /glossaries/{id}/extract | pm | multipart: `job_id` or `file` + `source_lang`, `target_lang?`, `min_freq=2`, `limit=50` | `{source_lang, target_lang, job_id, filename, items: [{source_term, frequency, words, variants[], target_candidates: [{term, score, count}]}]}` |
| POST | /glossaries/{id}/extract/accept | pm | `{terms: [{source_term, target_term?, kind, source_lang, target_lang, note?}]}` | 201 list of `Term` |
| GET | /tm/qa | cust | `?source_lang=&target_lang=&glossary_id=&limit=` | `{inconsistent: [{source_tagged, variants: [{target_tagged, entry_ids[], origins[], updated_at}]}], glossary_violations: [{entry_id, source_tagged, target_tagged, violations[]}]}` |

`TmEntry`: `{id, source_lang, target_lang, content_type, source_tagged, target_tagged, status, origin, job_id, has_context, rights_confirmed_by, created_at, updated_at}`.
`Alignment`: `{id, source_lang, target_lang, source_filename, target_filename, content_type, status: review|committed, committed_count, pairs: [{index, src[], tgt[], source, target, confidence 0..1, accepted}], stats: {pairs, one_to_one, unaligned, low_confidence}, created_at, committed_at}`.

## LQA scorecards (module `ai`)

| Method | Path | Role | Returns |
|---|---|---|---|
| GET | /jobs/{id}/lqa | cust | `Scorecard` + `{job_id, segments_with_errors, sources: {reviewer, senate}, errors: [{segment_id, seq, dimension, severity, span, explanation, source, source_text, target_text}]}` |
| GET | /jobs/{id}/lqa.pdf | cust | PDF |
| GET | /jobs/{id}/lqa.xlsx | cust | XLSX (sheets Summary, Errors) |
| GET | /lqa/settings | cust | `{threshold, weights{dimension: factor}, dimensions[]}` |
| PUT | /lqa/settings | pm | body `{threshold?, weights?, reset?}`; 422 on an unknown dimension or out-of-range value |

`Scorecard`: `{word_count, error_count, by_dimension: {dimension: {neutral, minor, major, critical, penalty}}, by_severity, penalty, score, threshold, passed, weights}`. Score = 100 - penalty*100/words, penalty = sum(severity weight 0/1/5/25 x dimension weight). Default threshold 95.

## Auditor (module `auditor`)

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| POST | /audits | pm | multipart `file` (XLIFF 1.2/2.x, TMX, CSV/TSV, XLSX) or `file` + `target_file` (any supported document format, aligned), `source_lang`, `target_lang`, `name?`, `glossary_id?`, `ai_mode=none\|sample\|full`, `ai_sample_pct=10`, `threshold?`, `consistency=true`, `content_type?` | 201 `Audit` (state `queued`; worker steps `audit.parse`, `audit.check` per 100 segments, `audit.finish`) |
| GET | /audits | cust | | list of `Audit` |
| GET | /audits/{id} | cust | | `Audit` (poll `progress` 0..1) |
| GET | /audits/{id}/segments | cust | `?severity=a,b&min_severity=&dimension=&code=&with_issues=` | list of `AuditSegment` plus `total` |
| GET | /audits/{id}/stats | cust | | `{by_max_severity}` |
| GET | /audits/{id}/report.pdf | cust | | PDF; 409 before `done` |
| GET | /audits/{id}/report.xlsx | cust | | XLSX; 409 before `done` |
| GET | /audits/{id}/annotated.xlf | cust | | the uploaded XLIFF with one note per finding (`from`/`category` `arbiter-auditor`); a fresh XLIFF 2.1 for other inputs; 409 before `done` |
| POST | /audits/{id}/retry | pm | | `Audit` back to `queued`; 409 unless `failed` |

`Audit`: `{id, name, source_lang, target_lang, input_format: xliff|tmx|csv|xlsx|pair, filename, target_filename, glossary_id, settings, state: queued|running|done|failed, progress, segments_total, segments_done, word_count, mqm_score, verdict: pass|fail|null, ai_units (decimal string), summary: {segments, words, segments_with_issues, issues_by_code, issues_by_severity, ai: {mode, sample_pct, checked, failed, units}, consistency: {inconsistent_translations, inconsistent_sources}, scorecard, notes}, error, created_at, started_at, finished_at}`.
`AuditSegment`: `{id, seq, ref, source_tagged, target_tagged, word_count, issues: [{code, severity, message, blocking, kind: qa|term|consistency, dimension, mqm_severity}], mqm_errors[], ai_checked, score, max_severity, dimensions[]}`.
AI judge calls are metered as `ai_unit` usage (0.05 per judged segment, key `<audit id>:ai`).
