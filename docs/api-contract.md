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
