# Operations runbook

For the Hetzner deployment described in `deploy/README.md`. Commands run in `/opt/arbiter/deploy`.
Status: written ahead of the code. Behaviours marked "the system does" are build targets of phases P01 to P04 (`phases/README.md`); check `memory-bank/progress.md` for what is live.
Every incident gets a short note at the bottom of this file (date, what happened, what was done, follow-up).

Handy queries:

```bash
psql() { docker compose exec -T postgres psql -U arbiter -d arbiter "$@"; }
psql -c "select kind, status, count(*), min(run_at) from work_items group by 1,2 order by 1,2;"
psql -c "select kind, last_error, count(*) from work_items where status='dead' group by 1,2 order by 3 desc limit 20;"
```

---

## 1. Provider outage (Anthropic, OpenAI, DeepL or Google)

**Signals.** Rising `last_error` on translate/score work items for one engine, provider status page, latency spike in logs.

**What the system does by itself.** The router skips a provider whose key is missing or whose recent error rate is above the health limit, and falls back to the next engine on the scoreboard for that pair. While a fallback engine is in use, the decide step adds a **safety offset** to the threshold for the affected thresholds, so fewer segments auto-approve on an engine with less calibration data. Work items retry with backoff.

**Operator steps.**
1. Confirm which provider: `docker compose logs --since 30m worker | grep -i provider`.
2. If the outage is long (more than 1 h) and no healthy fallback exists for a pair, suspend auto-approval for that pair (section 3) so nothing ships on stale scoring.
3. Do not swap in a different provider key or model by hand mid-job; jobs record which engine produced each segment.
4. When the provider recovers, dead work items can be requeued: `psql -c "update work_items set status='ready', attempts=0, run_at=now() where status='dead' and kind in ('job.translate','job.score');"`
5. Remove the safety offset only after the engine's scores on control samples look normal again.

## 2. Drift alarm

**Signal.** Auto-approve rate for an org/content_type/target_lang moved more than `ARBITER_DRIFT_ALARM_RATIO` (default 30%) from its baseline. Shown on `/quality/dashboard`.

**Likely causes.** Provider silently changed a model, new kind of content from a customer, glossary change, judge prompt change.

**Steps.**
1. Check engine versions in recent provenance events for the threshold; compare with the baseline period.
2. Check whether the content mix changed (new project types, new file formats).
3. Pull control samples from the drift window and look at disagreement between judge and human.
4. If the auto rate went **up** without an explanation, treat it as dangerous: suspend auto-approval (section 3) until control samples confirm.
5. If it went **down**, it costs money, not quality: investigate, no suspension needed.
6. Calibration may move the threshold at most 3 points per week (D-011). Do not override that by hand.

## 3. Escaped-error spike: suspend auto-approval

**Signal.** Escaped-error rate (customer reports via `/jobs/{id}/report-error` plus control-sample failures) above `ARBITER_ESCAPED_ERROR_TARGET` for a threshold, or several critical errors in a short window.

**Steps.**
1. Suspend auto-approval on the affected thresholds: set `auto_approval_suspended=true` with a `suspended_reason` (admin UI, or SQL on `thresholds`). From then on every segment for that threshold goes to review per tier and `no_reviewer_policy`. Customers on `auto` see segments held, not silently reviewed by AI (D-012).
2. Collect the escaped errors and their provenance: which engine, QE score, senate verdict.
3. Fix the cause (prompt, glossary, engine choice, threshold) and record a decision if the fix changes behaviour.
4. Resume only after a fresh batch of control samples on that threshold passes.
5. Inform affected customers if delivered content contained critical errors; offer re-review.

## 4. Webhook endpoint failing / auto-disabled

**Behaviour.** Each delivery retries up to `ARBITER_WEBHOOK_MAX_ATTEMPTS` with backoff. After `ARBITER_WEBHOOK_DISABLE_AFTER_CONSECUTIVE_FAILURES` consecutive failures the webhook is set `active=false` with `disabled_reason`.

**Steps.**
1. `psql -c "select id, org_id, url, consecutive_failures, disabled_reason from webhooks where active=false;"`
2. Tell the customer (email to org PMs) with the reason and last HTTP status.
3. After they fix the endpoint they re-enable it in settings (or operator sets `active=true, consecutive_failures=0`). Missed events can be re-sent from `webhook_deliveries`; receivers dedupe on `event_id`.
4. Never disable signature checking to "help" a customer debug.

## 5. Payout failures

**Signals.** Payout in state `failed` or `blocked`; reviewer dispute about missing money.

**Steps.**
1. `psql -c "select id, reviewer_id, amount, state, created_at from payouts where state in ('failed','blocked') order by created_at;"`
2. `blocked` usually means missing or invalid tax info or payout details: the reviewer must complete their profile. Do not pay around the block.
3. `failed` is a provider rejection: check the payout provider response, fix details, re-run via `POST /admin/payouts/run` (only creates payouts for balances not already in flight).
4. Ledger must stay balanced: every correction is a new pair of ledger entries (`adjustment`), never an edit. Reconcile: sum per `txn_id` must be zero.
5. Amounts are Decimal; any rounding discrepancy is a bug, open an issue, do not patch by hand.

## 6. Restoring backups

Full procedure and the monthly drill: `deploy/README.md` section 9. Summary for a real incident:

1. Decide the restore point (latest good dump). Announce downtime.
2. `docker compose stop api worker web`
3. Restore DB: drop and create `arbiter`, `pg_restore --no-owner` the dump.
4. Restore the storage tarball into the `storage` volume.
5. `docker compose up -d` and check `alembic current`, `/healthz`, a known job's evidence pack.
6. Work items that were `running` at backup time are reclaimed when their lease expires.
7. Anything delivered after the restore point must be reconciled by hand from webhook logs and customer emails; write it down here.

## 7. Queue backlog / stuck worker

1. Oldest ready item age: `psql -c "select now()-min(run_at) from work_items where status='ready' and run_at<=now();"`
2. `docker compose logs --tail=200 worker`; restart with `docker compose restart worker`.
3. Scale workers on the same host if CPU allows: `docker compose up -d --scale worker=3` (SKIP LOCKED makes this safe).
4. Items stuck in `running` past `locked_until` return to `ready` automatically.

---

## Drill and incident log

| Date | Type | Duration | Notes |
|---|---|---|---|
| | | | |
