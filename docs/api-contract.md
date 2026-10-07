# Arbiter API contract (v1)

Base URL: `/v1`. JSON everywhere except uploads (multipart) and downloads (binary).
Auth: `Authorization: Bearer <jwt>` (from login) or `Authorization: Bearer ak_<prefix>.<secret>` (API key).
Errors: `{"error": {"code": "string", "message": "string", "details": {}}}` with a proper HTTP status.
Lists: `{"items": [...], "next_offset": int|null}`; query `offset`, `limit` (max 200).
POST endpoints that create things accept `Idempotency-Key` header (24 h).
Ids are prefixed strings (`job_01J...`). Money is a decimal string (`"12.40"`). Times are ISO 8601 UTC.

Roles: `admin` (platform operator), `pm` and `client` (customer org users), `reviewer`.

## Auth and account
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /auth/register | `{org_name, name, email, password}` | `{token, user, org}` (creates org + pm user) |
| POST | /auth/login | `{email, password}` | `{token, user}` |
| GET | /me | | `{user, org}` (org null for reviewers/admin) |
| GET/PATCH | /org | `{name?, default_tier?, no_reviewer_policy?, ai_subprocessors_opt_in?, regulated?, vertical?, data_retention_days?}` | `Org` |
| GET/POST | /api-keys | `{name, scopes}` | POST returns `{id, name, prefix, key}` once (key shown only once) |
| DELETE | /api-keys/{id} | | 204 |

`User`: `{id, email, name, role, org_id}`. `Org`: `{id, name, slug, plan, default_tier, no_reviewer_policy, ai_subprocessors_opt_in, regulated, vertical, data_retention_days}`.

## Files, quotes, projects, jobs
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /files | multipart `file`, `source_lang` | `File {id, filename, format, segment_count, word_count, warnings[]}` |
| POST | /quotes | `{file_id, target_langs[], content_type}` | `Quote` |
| GET | /quotes/{id} | | `Quote` |
| POST | /projects | `{name, quote_id, tier, due_at?}` | `Project` (jobs created and started) |
| GET | /projects | | list of `Project` |
| GET | /projects/{id} | | `Project` with `jobs[]` |
| GET | /jobs | `?state=&project_id=` | list of `Job` |
| GET | /jobs/{id} | | `Job` |
| GET | /jobs/{id}/segments | `?state=&decision=&offset=&limit=` | list of `Segment` |
| PATCH | /jobs/{id}/segments/{seg_id} | `{target_tagged}` | `Segment` (client/PM edit, counts as human) |
| POST | /jobs/{id}/segments/{seg_id}/approve | | `Segment` |
| POST | /jobs/{id}/cancel | | `Job` |
| GET | /jobs/{id}/download | | translated file (binary) — only when state `delivered` |
| GET | /jobs/{id}/xliff | | XLIFF 2.1 export |
| GET | /jobs/{id}/evidence | `?format=json\|pdf` | evidence pack |
| POST | /jobs/{id}/report-error | `{segment_id, note}` | `{id}` (escaped error, feeds calibration) |
| GET | /exceptions | | list of `{kind, job_id, segment_id?, reason, created_at}` — PM screen: only what needs a human |

`Quote`: `{id, file_id, source_lang, target_langs, content_type, word_count, currency, valid_until, analysis: {tm_context, tm_exact, tm_fuzzy, new, repetitions}, tiers: {auto|ai_review|hybrid|full: {price, est_auto_rate, eta_hours, available, blocked_reason?}}}`.
`Project`: `{id, name, source_lang, target_langs, tier, content_type, due_at, created_at, jobs?: Job[]}`.
`Job`: `{id, project_id, file_id, filename, source_lang, target_lang, tier, content_type, state, segment_count, word_count, auto_approved_count, review_count, ai_reviewed_count, progress (0..1), threshold, revenue, cost, margin, failure_reason, due_at, delivered_at, created_at}`.
Job states (authority: `services/api/arbiter/domain/states.py`): `draft, quoted, running, review, ready, merging, delivered, settled, failed, cancelled, disputed`. `running` covers extraction, TM, MT, QA, QE and senate; `review` = waiting for humans; `ready` = every segment approved, about to merge.
`Segment`: `{id, seq, source_tagged, target_tagged, state, origin, engine, tm_match, qe_score, decision, reasons[], signals{}, reviewer_id, is_control_sample}`.
Segment states (authority: states.py): `pending, translated, auto_approved, needs_review, in_review, reviewed, delivered`. Blocked segments are `needs_review` with decision `blocked`; AI-reviewed segments are `reviewed` with origin `editor`.
Decisions: `auto_approve, senate, review, blocked`.

## Linguistic assets
| Method | Path | Body | Returns |
|---|---|---|---|
| GET/POST | /glossaries | `{name, content_type?}` | `Glossary {id, name, content_type, version, term_count}` |
| GET | /glossaries/{id}/terms | `?q=&source_lang=&target_lang=` | list of `Term` |
| POST | /glossaries/{id}/terms | `{source_lang, target_lang, source_term, target_term?, kind, case_sensitive?, note?}` | `Term` |
| PATCH/DELETE | /terms/{id} | | `Term` / 204 (retires, bumps version) |
| POST | /glossaries/{id}/import | multipart `file` (csv or tbx) | `{imported, skipped, errors[]}` |
| GET | /glossaries/{id}/export | `?format=csv\|tbx` | file |
| POST | /tm/import | multipart `file` (tmx), `rights_confirmed=true` | `{imported, skipped}` |
| GET | /tm/search | `?q=&source_lang=&target_lang=` | list of `{entry_id, kind, score, source_tagged, target_tagged}` |
| GET | /tm/export | `?source_lang=&target_lang=` | TMX |
| GET | /term-questions | | list of `{id, source_term, source_lang, target_lang, options[], status}` |
| POST | /term-questions/{id}/answer | `{answer, add_to_glossary_id?}` | `TermQuestion` |

`Term`: `{id, glossary_id, source_lang, target_lang, source_term, target_term, kind, case_sensitive, note, valid_from, valid_to}`; kind ∈ `mandatory, preferred, forbidden, do_not_translate`.

## Quality
| GET | /quality/dashboard | | `{auto_rate, escaped_rate, control_samples, thresholds[], engines[]}` |
| GET | /quality/thresholds | | list of `{id, content_type, target_lang, value, band_width, safety_offset, auto_approval_suspended, suspended_reason}` |

## Reviewers (community)
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /reviewers/apply | `{name, email, password, country, pairs: [{source_lang, target_lang}], domains[]}` | `{token, user, profile}` |
| GET | /reviewer/me | | `ReviewerProfile {id, level, status, score, pairs[{source_lang,target_lang,status,score}], domains, balance, payout_threshold, tax_info_complete}` |
| PATCH | /reviewer/me | `{legal_name?, tax_id?, address?, date_of_birth?, payout_method?, payout_details?}` | profile |
| GET | /reviewer/tests | | list of `{id, kind, source_lang, target_lang, domain, time_limit_min, status: available\|passed\|failed\|locked}` |
| POST | /reviewer/tests/{id}/start | | `{attempt_id, items: [{index, source, target}], time_limit_min}` |
| POST | /reviewer/attempts/{id}/submit | `{answers: [{index, target, errors: [{span, category, severity}]}]}` | `{score, passed}` |
| POST | /reviewer/tasks/next | `{source_lang?, target_lang?}` | `Task` or 204 when none |
| POST | /reviewer/tasks/{id}/submit | `{decision: accept\|edit\|escalate\|skip, target_tagged?, errors?: [{dimension, severity, span, explanation}], comment?, time_ms}` | `{ok, pay_amount}` |
| POST | /reviewer/tasks/{id}/release | | 204 |
| GET | /reviewer/earnings | | `{balance, pending, paid, entries[]}` |
| POST | /reviewer/disputes | `{task_id, reason}` | `{id, due_at}` |

`Task`: `{id, segment_id, source_lang, target_lang, domain, source_tagged, target_tagged, context_before, context_after, terms: [{source_term, target_term, kind}], qe_score, flagged_errors[], hold_expires_at, pay_estimate}`.

## Admin (platform operator)
| GET | /admin/reviewers | `?status=` | list of profiles |
| POST | /admin/reviewers/{id}/status | `{status, level?}` | profile |
| GET | /admin/disputes | | list |
| POST | /admin/disputes/{id}/decide | `{outcome: upheld\|overturned, note}` | dispute |
| GET | /admin/payouts | | list `{id, reviewer_id, amount, state, created_at}` |
| POST | /admin/payouts/run | | `{created, total}` |
| GET | /admin/orgs | | list of Org with usage |
| POST | /admin/tests | `ReviewerTest` | created test |

## Integrations and billing
| GET/POST | /webhooks | `{url, events[]}` | `{id, url, events, active, secret}` (secret only on create) |
| DELETE | /webhooks/{id} | | 204 |
| GET | /usage | `?period=YYYY-MM` | `{period, words, ai_units, review_decisions, amount}` |
| GET | /invoices | | list |
| GET | /healthz | | `{ok: true}` (no /v1 prefix) |

Webhook events: `job.delivered, job.failed, job.needs_attention, quote.expired`. Signature header `Arbiter-Signature: t=<unix>,v1=<hex hmac sha256 of "t.body">`.

---

# Agency OS (PM / CRM / workflows / dashboards / AI assistant) — v1 addendum

The business layer an agency or a localization team runs on (the part Plunet-like systems
cover), plus an AI assistant that configures it from a plain-language description.
All endpoints: roles pm or api key unless stated; `client` role may read dashboards.
Money = decimal strings. Lists = `{items, next_offset}`.

## CRM
| Method | Path | Body | Returns |
|---|---|---|---|
| GET/POST | /crm/accounts | `{name, kind: client\|prospect, industry?, country?, vat_id?, currency?, default_tier?, workflow_template_id?, price_list_id?, notes?}` | `Account` |
| GET/PATCH/DELETE | /crm/accounts/{id} | | `Account` with `contacts[]`, `deals[]`, `recent_activities[]`, `stats {projects, jobs_active, revenue_total, revenue_90d, margin_90d}` (DELETE archives: status archived) |
| GET/POST | /crm/accounts/{id}/contacts | `{name, email?, phone?, role?, is_primary?}` | `Contact` |
| PATCH/DELETE | /crm/contacts/{id} | | `Contact` / 204 |
| GET/POST | /crm/deals | `?stage=&account_id=` ; `{account_id, title, value, currency?, stage?, expected_close?, quote_id?}` | `Deal` |
| PATCH/DELETE | /crm/deals/{id} | `{stage?, value?, title?, expected_close?, lost_reason?}` | `Deal` |
| GET/POST | /crm/activities | `?account_id=&deal_id=&open=true` ; `{account_id, deal_id?, kind: note\|call\|email\|meeting\|task, body, due_at?}` | `Activity` |
| PATCH | /crm/activities/{id} | `{done?, body?, due_at?}` | `Activity` |

`Account`: `{id, name, kind, status: active|archived, industry, country, vat_id, currency, default_tier, workflow_template_id, price_list_id, owner_user_id, notes, created_at}`.
`Deal`: `{id, account_id, account_name, title, value, currency, stage: lead|qualified|proposal|negotiation|won|lost, expected_close, quote_id, lost_reason, owner_user_id, created_at, updated_at}`.
`Activity`: `{id, account_id, deal_id, kind, body, due_at, done, user_id, created_at}`.

## Price lists
| GET/POST | /price-lists | `{name, currency, rates: [{source_lang?, target_lang?, tier, per_word}], tm_weights?: {context, exact, fuzzy_95, fuzzy_85, fuzzy_75, new, repetition}, minimum_charge?}` | `PriceList` |
| GET/PATCH/DELETE | /price-lists/{id} | | `PriceList` |

Quotes use the account's price list when `POST /quotes` carries `account_id`; rate lookup: exact pair+tier, then target-only, then tier-only, then org default.

## Workflow templates
| GET/POST | /workflows | `{name, description?, content_type?, tier, steps: Step[], is_default?}` | `Workflow` |
| GET/PATCH/DELETE | /workflows/{id} | | `Workflow` |

`Step`: `{kind, params?}` with kind ∈
`tm` (TM pre-translation), `mt` (`params.engine?`), `translation_senate` (best-of-N), `qe` (`params.threshold?`),
`senate` (band review), `ai_review` (senate + editor), `human_review` (`params.min_level?`),
`second_review` (a second human, senior), `client_review` (job waits for the client's approval before delivery),
`delivery`. Validation: must contain `mt` or `tm`; `qe` before any review step; `delivery` last; tier must be
consistent (full ⇒ human_review; auto ⇒ no human_review). Regulated orgs: tier auto/ai_review rejected.
A job freezes a snapshot of its workflow at creation (`job.workflow`).
`POST /projects` accepts `account_id?` and `workflow_template_id?` (tier comes from the template when given).
`POST /jobs/{id}/client-approve` — client/pm approves a job waiting in `client_review` → delivery.

## Dashboards
| GET/POST | /dashboards | `{name, widgets: Widget[]}` | `Dashboard` |
| GET/PATCH/DELETE | /dashboards/{id} | | `Dashboard` |
| GET | /dashboards/{id}/data | `?period=30d\|90d\|365d` | `{widgets: [{id, type, title, data}]}` |

`Widget`: `{id, type: kpi|bar|line|table|pipeline, metric, title?, size?: s|m|l}`. Metrics:
kpi — `revenue`, `margin`, `margin_pct`, `jobs_active`, `jobs_overdue`, `auto_rate`, `escaped_rate`, `open_deals_value`, `words_delivered`, `reviewer_cost`;
bar/line — `revenue_by_month`, `jobs_by_state`, `revenue_by_account`, `words_by_pair`, `auto_rate_by_month`;
pipeline — `deals_by_stage`; table — `overdue_jobs`, `top_accounts`, `open_activities`, `recent_deliveries`.
`GET /dashboards/default` returns (and creates on first call) the org's default dashboard.

## AI assistant
| POST | /assistant/threads | `{title?}` | `Thread` |
| GET | /assistant/threads | | list |
| GET | /assistant/threads/{id} | | `Thread` with `messages[]` |
| POST | /assistant/threads/{id}/messages | `{content}` | `{user_message, assistant_message}` |
| POST | /assistant/messages/{id}/apply | `{actions?: int[]}` (indices; default all) | `{results: [{index, type, ok, id?, error?}]}` |

`Message`: `{id, role: user|assistant, content, plan: Action[] | null, applied: int[] , created_at}`.
`Action`: `{type, summary, data}` with type ∈ `create_workflow, create_price_list, create_account, create_contact,
create_deal, create_activity, create_dashboard, update_org, create_glossary, add_terms, create_webhook`.
The assistant never changes anything by itself: it proposes a plan; a human applies all or selected actions.
It also answers questions about the org's data (jobs, revenue, deals) from a context summary it is given.
