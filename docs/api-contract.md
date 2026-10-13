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

### Idempotency

`Idempotency-Key` header (max 150 chars) is honoured on these creating POSTs: `/files`, `/quotes`, `/projects`, `/glossaries`, `/webhooks`, `/crm/accounts`, `/crm/accounts/{id}/contacts`, `/crm/deals`, `/crm/activities`, `/price-lists`, `/workflows`, `/dashboards`, `/assistant/threads`, `/assistant/threads/{id}/messages`.
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
| GET | /me | any | | `{user\|null, org\|null}` (org null for reviewers/admin; user null for API keys) |
| GET | /org | cust | | `Org` |
| PATCH | /org | pm | `{name?, default_tier?, no_reviewer_policy?, ai_subprocessors_opt_in?, regulated?, vertical?, data_retention_days?(1..3650)}` | `Org` |
| GET | /api-keys | pm | | list of `{id, name, prefix, scopes, created_at, last_used_at}` (not revoked) |
| POST | /api-keys | pm (users only) | `{name, scopes[]}` | 201 key view + `key` (shown once). An API key cannot create keys (422) |
| DELETE | /api-keys/{id} | pm | | 204 (revokes) |

`User`: `{id, email, name, role, org_id}`.
`Org`: `{id, name, slug, plan, default_tier, no_reviewer_policy: wait|ai_fallback|partial, ai_subprocessors_opt_in, regulated, vertical, data_retention_days}`.

## Files, quotes, projects, jobs

| Method | Path | Role | Body / query | Returns |
|---|---|---|---|---|
| POST | /files | cust | multipart `file`, `source_lang` | 201 `File`. Extracted once to validate; 422 `unsupported_file` otherwise. Limit 1 GB |
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
| GET | /jobs/{id}/download | cust | | translated file; 409 `not_delivered` before `delivered`/`settled`/`disputed` |
| GET | /jobs/{id}/xliff | cust | | XLIFF 2.1 (units whose segments all have a target carry it) |
| GET | /jobs/{id}/evidence | cust | `?format=json\|pdf` | stored pack for delivered jobs, live pack otherwise |
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

Webhook events: `job.delivered, job.failed, job.needs_attention, quote.expired`. Delivery is at-least-once; receivers dedupe on `event_id`. Signature header `Arbiter-Signature: t=<unix>,v1=<hex hmac sha256 of "t.body">`.

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

