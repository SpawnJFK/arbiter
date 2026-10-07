# Architecture decision log

One entry per decision. Never edit an accepted entry; supersede it with a new one and mark the old one `Superseded by D-0NN`.
Template: Context, Decision, Rejected alternatives, Consequences. Date is when the decision was recorded.

---

## D-001 Monorepo: Python API + Next.js web
Date: 2026-10-07. Status: accepted.

**Context.** The product needs heavy text and file processing (XML/OOXML, segmentation, stemming, fuzzy matching, LLM orchestration) and a rich web UI for four roles. A small team (mostly AI agents) must keep API and UI in sync.

**Decision.** One repository: `services/api` (Python 3.13, FastAPI, SQLAlchemy 2, Alembic) and `apps/web` (Next.js 16). The HTTP contract lives in `docs/api-contract.md`; CI checks both sides on every push.

**Rejected.**
- *TypeScript end to end (Node API).* Weaker ecosystem for document formats, NLP and evaluation tooling; would duplicate work already in Python.
- *Polyrepo.* Contract drift between API and UI becomes invisible; agents lose cross-repo context.
- *Python-only with server-rendered templates.* Reviewer workspace and PM screens need a real client app.

**Consequences.** Two toolchains in CI. Contract changes must update both sides in one change.

---

## D-002 Durable queue in Postgres instead of Temporal, Celery or Redis
Date: 2026-10-07. Status: accepted.

**Context.** Pipeline steps (extract, translate, score, senate, merge, webhooks) must survive restarts, retry with backoff, and never run twice in a way that double-charges or double-pays. Ops capacity is one person.

**Decision.** A `work_items` table claimed with `FOR UPDATE SKIP LOCKED`, leases (`locked_until`), `max_attempts` then `dead`, unique `idempotency_key`. State change and enqueue commit in the same transaction. Same Docker image runs API and worker.

**Rejected.**
- *Temporal.* Excellent for long workflows, but another cluster to run, upgrade and back up. Kept as the upgrade path.
- *Celery + Redis/RabbitMQ.* Dual write between DB and broker loses or duplicates messages on crashes; Redis persistence is a second backup story.
- *Cloud queues (SQS, Pub/Sub).* Ties hosting to a hyperscaler and complicates EU residency on Hetzner.

**Consequences.** Throughput limited by Postgres (fine into thousands of items per second, far above need). Long human waits are modelled as states, not sleeping workers.

---

## D-003 pgvector inside Postgres instead of a separate vector database
Date: 2026-10-07. Status: accepted.

**Context.** TM semantic matching and similar-segment retrieval need vector search, always filtered by org and language pair.

**Decision.** `pgvector` columns on TM entries, with `pg_trgm` for fuzzy text matches, in the same database.

**Rejected.**
- *Pinecone, Weaviate, Qdrant, Milvus.* Another service, another backup, another data-residency question, and tenant filters must be duplicated outside SQL.
- *No semantic matching.* Fuzzy (edit distance) misses paraphrased repeats that matter for consistency checks.

**Consequences.** Index tuning (HNSW/IVFFlat) is Postgres work. If vectors outgrow one host, revisit.

---

## D-004 File formats in Python now, Okapi Framework as a later sidecar
Date: 2026-10-07. Status: accepted.

**Context.** Needed formats for P0/P1: docx, xlsx, pptx, html, md, json, po, txt/csv, xliff. Okapi supports many more but is Java.

**Decision.** Pure Python handlers behind a `FormatHandler` interface (`arbiter/fileproc/`), all converting to the tagged text model (D-007). Okapi Framework comes in P4 as a sidecar service implementing the same interface for long-tail formats (IDML, MIF, DITA, etc.).

**Rejected.**
- *Okapi from day one.* Main reason: a single runtime is simpler to build, test and deploy while the core is changing fast. Secondary trigger: Maven dependency resolution was blocked in the build environment.
- *A commercial file-filter SDK.* Licensing cost and lock-in before product-market fit.

**Consequences.** Each Python handler needs round-trip tests (extract then merge equals original). Formats outside the list are rejected at upload with a clear message.

---

## D-005 LLM judge as primary QE, COMET as optional plugin
Date: 2026-10-07. Status: accepted.

**Context.** Auto-approval needs a per-segment quality score that can explain itself (for the evidence pack) and handle terminology and context.

**Decision.** Primary QE is an LLM judge returning an MQM-style error list and a 0-100 score (D-010). COMET/CometKiwi can be added as an optional plugin signal.

**Rejected.**
- *COMET-only.* Strong correlation on news-like text, but no explanation, no glossary awareness, needs GPU hosting, and licensing of some checkpoints restricts commercial use.
- *Commercial QE API only (e.g. ModelFront).* Useful benchmark, but the decision logic is the product and should not be outsourced.

**Consequences.** Judge prompts and models are versioned; scores are calibrated per org/content_type/target_lang (D-011). Judge cost is part of job cost.

---

## D-006 Snowball stemmers for lemmatized term checks
Date: 2026-10-07. Status: accepted.

**Context.** Glossary checks must match inflected forms (Serbian, German, Russian, etc.) or they flood reviewers with false "term missing" errors.

**Decision.** `snowballstemmer` for supported languages, compare stems of term and text tokens; exact match fallback elsewhere.

**Rejected.**
- *spaCy/Stanza lemmatizers.* Better accuracy for some languages, but large models per language, slower, heavier images.
- *LLM-only term checking.* Non-deterministic and expensive for a hard QA step that must be reproducible.

**Consequences.** Stemming over- and under-matches sometimes; the LLM judge is the second line. Unsupported languages fall back to exact match and say so in the QA reason.

---

## D-007 Tagged text format ⟦n⟧
Date: 2026-10-07. Status: accepted.

**Context.** Engines, TM, QA and reviewers need one representation of inline formatting that survives MT and LLM edits and round-trips into every file format.

**Decision.** Paired codes `⟦1⟧...⟦/1⟧`, standalone `⟦2/⟧`, literal brackets escaped as `⟦⟦` and `⟧⟧`. Only fileproc converts to and from native markup. Defined in `arbiter/fileproc/base.py`.

**Rejected.**
- *XLIFF inline elements (`<pc>`, `<ph>`) as the internal form.* Verbose, and LLMs mangle XML attributes.
- *HTML-like tags.* Collide with real HTML/Markdown content.
- *Stripping formatting.* Unacceptable for customer files.

**Consequences.** Mathematical brackets are rare in source text; the escape rule keeps it lossless anyway. XLIFF export maps codes to `<pc>`/`<ph>`.

---

## D-008 contracts.py is the seam between modules
Date: 2026-10-07. Status: accepted.

**Context.** Linguistic assets, engines, quality and pipeline are built in parallel, often by different agents.

**Decision.** Modules exchange only the dataclasses and Protocols in `arbiter/contracts.py`. Internals are free; contract changes require a decision entry and updating every caller in the same change.

**Rejected.**
- *Modules importing each other's internals.* Fast at first, then every change breaks a parallel workstream.
- *Separate services per module.* Network boundaries far too early.

**Consequences.** Some duplication of small types; acceptable for independent progress.

---

## D-009 Tag severity policy
Date: 2026-10-07. Status: accepted.

**Context.** Translations often lose or reorder inline codes. Some losses break the output file or meaning; others only lose cosmetic formatting.

**Decision.**

| Situation | Severity |
|---|---|
| Missing standalone code (`⟦n/⟧`) | error |
| Whole paired code dropped (both `⟦n⟧` and `⟦/n⟧` gone) | warning |
| Half of a pair present | error |
| Unknown code (not in source) | error |
| Duplicate code | error |
| Invalid order / nesting | error |

Errors block auto-approval; warnings lower the score and are listed in the evidence.

**Rejected.**
- *All tag issues are errors.* Too many segments sent to review for lost bold/italic.
- *All tag issues are warnings.* Broken files reach customers.

**Consequences.** Standalone codes (images, line breaks, fields) are treated as content.

---

## D-010 MQM-Core severity weights 0 / 1 / 5 / 25
Date: 2026-10-07. Status: accepted.

**Context.** Judges, reviewers and calibration need a shared error scale.

**Decision.** MQM-Core dimensions (accuracy, fluency, terminology, style, locale conventions, design/markup) with severity weights neutral 0, minor 1, major 5, critical 25. Segment score derives from weighted penalty per word count.

**Rejected.**
- *Ad-hoc 1-5 star ratings.* Not comparable across reviewers or with industry practice.
- *Weights 1/5/10.* Critical errors (meaning reversal, safety) must dominate; 25 makes one critical fail almost any segment.

**Consequences.** Reviewer tests and disputes use the same scale.

---

## D-011 Thresholds per org / content_type / target_lang, slow calibration, blind control samples
Date: 2026-10-07. Status: accepted.

**Context.** One global auto-approval threshold is wrong: legal German and marketing Spanish behave differently, and engines drift.

**Decision.** A threshold row per org + content_type + target_lang (default `ARBITER_DEFAULT_THRESHOLD`), senate band `ARBITER_BAND_WIDTH`. Calibration may move a threshold at most 3 points per week. 2% of auto-approved segments go blind to human control review; their disagreements and reported escaped errors drive calibration.

**Rejected.**
- *Global threshold.* Over-reviews easy content and under-reviews hard content.
- *Fully automatic, unbounded tuning.* Feedback loops can walk thresholds down after a lucky week.
- *No control samples.* Without blind sampling the escaped-error rate is unknown.

**Consequences.** Control samples cost money and are priced into tiers. Auto-approval can be suspended per threshold (runbook).

---

## D-012 No silent AI substitution
Date: 2026-10-07. Status: accepted.

**Context.** Customers who pay for human review must get it, or know exactly when they did not.

**Decision.** When a human is required and none is available, apply the org's `no_reviewer_policy`: `wait`, `ai_fallback` (AI editor, disclosed), or `partial` (deliver approved segments, hold the rest). Every fallback is a provenance event and appears in the evidence pack and on the invoice. Regulated verticals cannot use `auto` or `ai_review`.

**Rejected.**
- *Quietly use AI when the queue is slow.* Fast, but a trust and contractual problem.
- *Always wait.* Some customers prefer speed and accept disclosed AI review.

**Consequences.** PM exceptions screen shows waiting jobs; pricing reflects the actual path taken.

---

## D-013 Hetzner + Docker Compose instead of Kubernetes
Date: 2026-10-07. Status: accepted.

**Context.** EU data residency, low cost, one operator.

**Decision.** One Hetzner host (Germany/Finland) running Docker Compose: Postgres, api, worker, web, Caddy (automatic TLS). Nightly `pg_dump` + storage tarball to EU object storage via rclone. GitHub Actions CI.

**Rejected.**
- *Kubernetes (managed or self-run).* Operational load far beyond current need.
- *Hyperscaler PaaS.* Higher cost; residency possible but more configuration.
- *Vercel for web.* Splits the stack and data path outside the single EU host for no gain at this stage.

**Consequences.** Vertical scaling first; split Postgres to its own host when needed. Restore drills are mandatory because there is no managed DB.

---

## D-014 JWT for sessions, API keys for integrations
Date: 2026-10-07. Status: accepted.

**Context.** Browser users and machine clients (CMS connectors, CI pipelines) both call the API.

**Decision.** Short-lived HS256 JWT after login; API keys `ak_<prefix>.<secret>`, argon2-hashed, shown once, scoped, revocable. Both sent as `Authorization: Bearer`.

**Rejected.**
- *Third-party auth service from day one.* Cost and lock-in before SSO is needed (SSO is P5).
- *Server sessions in Postgres.* Works, but API keys are needed anyway and JWT keeps the API stateless.

**Consequences.** JWT revocation relies on short TTL plus secret rotation. SAML/OIDC SSO added in P5.

---

## D-015 Append-only provenance enforced by a DB trigger
Date: 2026-10-07. Status: accepted.

**Context.** The evidence pack is a promise to the customer about how each segment was produced. It must not be editable after the fact, even by a bug.

**Decision.** `provenance_events` with a trigger that raises on UPDATE or DELETE. No FK to segments, so history survives retention deletes (content is deleted, decisions and hashes remain).

**Rejected.**
- *Application-level discipline only.* One bad migration or script rewrites history.
- *External ledger / blockchain.* Complexity without customer demand.

**Consequences.** Corrections are new events. Test teardown uses TRUNCATE (does not fire row triggers).

---

## D-016 One monotonically increasing glossary version per organization
Date: 2026-10-07. Status: accepted.

**Context.** A job must freeze the glossary state it started with (R-GL-11) and keep it while terms change. An org can have several glossaries, and a job reads all of the ones that apply to its content type.

**Decision.** Versions are org-wide: every term change bumps the org's maximum version by one and assigns it to the glossary that changed. Terms carry `valid_from`/`valid_to` in that same counter. A job stores one integer (`current_version` at prepare) and reads every term valid at it, across all glossaries. A new glossary starts at the org's current version, so creating it changes nothing.

**Rejected.**
- *Per-glossary counters.* A job would need a map {glossary: version}, and adding a new glossary mid-job could not be excluded cleanly.
- *Copying terms into the job.* Simple to read, but duplicates data and loses the link to term history.

**Consequences.** Version numbers jump when other glossaries change; the number is an ordering, not a count. The bump takes a row lock on the org's glossaries.

---

## D-017 Forbidden term: `target_term` is the forbidden target word, NULL means the source term
Date: 2026-10-07. Status: accepted.

**Context.** Forbidden terms are target-side checks ("never write X in the translation"). Clients also keep plain target-language blocklists with no source term pairing.

**Decision.** For `kind=forbidden`, `target_term` holds the forbidden target string. When it is NULL, `source_term` itself is the forbidden word in the target (blocklist entry). Forbidden terms are checked on every target segment, not only where the source term appears.

**Rejected.**
- *A separate blocklist table.* One more import/export path and UI for the same check.
- *Forbidden stored in `source_term` always.* Confusing for pairs where the forbidden word is a specific wrong translation of a source term.

**Consequences.** Import and UI must explain the NULL case. `forbidden_string(term)` is the one place that resolves it.

---

## D-018 Hybrid tier routing table
Date: 2026-10-07. Status: accepted.

**Context.** The hybrid tier promises a human on doubtful segments, with automation where the score is clearly good.

**Decision.** With effective threshold `eff = threshold + safety_offset` and band `band_width`:

| Score | Hybrid decision |
|---|---|
| blocking hard issue | `blocked` (human) |
| `score >= eff + band` (HIGH) | `auto_approve` |
| `eff <= score < eff + band` (upper band) | `senate` |
| `score < eff` | `review` (human) |
| auto-approval suspended | `review` |
| no score | `review` |

Regulated orgs and the `full` tier always route to `review`. The `auto`/`ai_review` tiers send the whole band (both halves) to the senate.

**Rejected.**
- *Senate for the whole band in hybrid.* Below threshold the customer paid for a human; the senate there would be AI substitution.
- *No senate in hybrid.* Upper-band segments would all go to humans and the tier would cost almost as much as full.

**Consequences.** Hybrid cost depends on the threshold position; calibration (D-011) moves it slowly.

---

## D-019 Senate severity on a confirmed finding = upper median
Date: 2026-10-07. Status: accepted.

**Context.** When two or more senate roles report the same error, they often disagree on severity.

**Decision.** The confirmed cluster takes the median severity of its members; on even counts the upper median (the more severe). Two independent reviewers disagreeing means the cautious one wins.

**Rejected.**
- *Maximum.* One outlier role could fail any segment.
- *Lower median or mean.* Systematically under-rates errors where judges split.

**Consequences.** Critical errors flagged by half the panel stay critical.

---

## D-020 A failed verification call keeps the finding
Date: 2026-10-07. Status: accepted.

**Context.** Lone senate findings (one role only, not minor style) are verified by asking the accuracy model whether fixing the span improves the translation. That call can fail (timeout, provider error, unparsable answer).

**Decision.** If verification fails, the finding is kept (fail safe: doubt goes to review). If fewer than `min_roles` roles answered at all, the verdict is void and the segment goes to a human or the safety offset rises.

**Rejected.**
- *Drop the finding on failure.* Provider trouble would silently raise the auto-approve rate.
- *Retry until success.* Unbounded latency and cost during an outage.

**Consequences.** Outages push more segments to review, which costs money but not quality.

---

## D-021 Google Cloud Translation Basic (v2 REST) with an API key
Date: 2026-10-07. Status: accepted.

**Context.** Keys come only from environment variables. Google's Advanced (v3) API needs OAuth service-account credentials.

**Decision.** Use the Basic edition endpoint `/language/translate/v2` with `ARBITER_GOOGLE_API_KEY`, tags protected as HTML spans. No glossary support there; term adherence is enforced by the hard checks.

**Rejected.**
- *v3 with a service account.* Credential file handling and rotation not justified while Google is one engine among four.

**Consequences.** If v3 features (glossaries, custom models) are needed, add a separate service-account client.

---

## D-022 PROMPT_VERSION recorded in every model_version
Date: 2026-10-07. Status: accepted.

**Context.** Scores and translations depend on the prompt as much as on the model. Calibration and evidence must know which prompt produced a result.

**Decision.** `quality/prompts.py` holds `PROMPT_VERSION`; every LLM call's `model_version` is `<model>+prompt:<PROMPT_VERSION>`, stored in provenance, senate runs and engine scores. Any prompt change bumps it.

**Rejected.**
- *Version prompts in git only.* Cannot be joined against stored results.

**Consequences.** A prompt change resets comparability; drift alarms (runbook) check prompt versions first.

---

## D-023 Translation senate ranks glossary adherence before judge score
Date: 2026-10-07. Status: accepted.

**Context.** Best-of-N translation picks one candidate among engines.

**Decision.** Candidates with a blocking hard issue are out. Among survivors, fewer term violations wins first; the judge score decides only between equals; ties then go by engine order.

**Rejected.**
- *Highest judge score wins.* A client-mandated term is a contract; a judge score is an estimate.

**Consequences.** An engine with weaker fluency but correct terminology can win; the review step still sees the score.

---

## D-024 Reviewer pay per decision (starting values)
Date: 2026-10-07. Status: accepted.

**Context.** Reviewers are paid per decision, which must be predictable for them and bounded for us.

**Decision.** `pay = max(0.02, BASE + words * PER_WORD * LEVEL_MULT)`, rounded half-up to the cent. Accept: base 0, 0.004 EUR/word. Edit: base 0.01, 0.012 EUR/word. Escalate and skip are not paid. Level multipliers: candidate and reviewer 1.0, senior 1.25, domain_expert 1.5. These are starting values, to be tuned against real throughput and the market.

**Rejected.**
- *Hourly pay.* Hard to verify remotely; rewards slowness.
- *Flat per segment.* Long segments become unattractive and are skipped.

**Consequences.** Every ledger movement is in whole cents. Pay estimates are shown on the task before the decision.

---

## D-025 Reviewer score formula
Date: 2026-10-07. Status: accepted.

**Context.** Reviewer quality must be judged on hidden control tasks with known answers, not on volume.

**Decision.** Events decay with a 90-day half-life. `accuracy = (passes + 0.70 * 10) / (passes + fails + 10)` (Bayesian prior of 70 with 10 virtual controls). An overturned failed control (dispute won) counts as a pass and cancels the fail. Penalties: 3.0 per escaped error, 1.0 per dispute lost, 0.5 per speed flag (accepting faster than about 0.6 s/word). `score = clamp(100 * accuracy - penalty, 0, 100)`. Demotion of a pair below 60 after 20+ controls; promotion to senior at 90+ with 200+ decisions and 50+ controls. All starting values.

**Rejected.**
- *Plain pass ratio.* New reviewers swing from 0 to 100 on one control.
- *No decay.* Old mistakes never wash out, old excellence never expires.

**Consequences.** New reviewers start at 70 and need roughly ten controls to move far.

---

## D-026 An expired dispute resolves in the reviewer's favour
Date: 2026-10-07. Status: accepted.

**Context.** A reviewer may dispute a rejected task within 7 days; we promise a decision within 48 hours.

**Decision.** An open dispute past its due time becomes `expired` with the same effect as `overturned`: task accepted, reviewer paid, score corrected.

**Rejected.**
- *Leave it open.* The reviewer bears the cost of our delay.
- *Auto-uphold.* Same, and invites ignoring disputes.

**Consequences.** Missed decisions cost money; the admin disputes screen shows due times.

---

## D-027 Blocked payouts carry no ledger movement
Date: 2026-10-07. Status: accepted.

**Context.** A payout cannot be sent while tax information is incomplete (needed for platform reporting).

**Decision.** A blocked payout is a marker only: the money stays in the reviewer's payable balance. At most one blocked payout per reviewer, re-evaluated each run; it becomes accrued once the info is complete.

**Rejected.**
- *Move money to in-transit and reverse later.* Two ledger movements for nothing, and the balance shown to the reviewer would drop.

**Consequences.** Balance always equals what we owe, blocked or not.

---

## D-028 Payout retry reuses the idempotency key
Date: 2026-10-07. Status: accepted.

**Context.** A failed send reverses the money to the reviewer's balance; the next run re-sends it.

**Decision.** `Payout.idempotency_key = "payout:<reviewer>:<yyyy-mm-dd>"` (unique). Running twice a day creates nothing new; a retry re-accrues the same payout and sends it with the same key, so a provider that actually paid the first time never pays twice.

**Rejected.**
- *New key per attempt.* A timeout after a successful send would pay twice.

**Consequences.** One payout per reviewer per day at most.

---

## D-029 Invoice tax rule (starting rule)
Date: 2026-10-07. Status: accepted, pending legal and tax review.

**Context.** Invoices go to customers in many countries.

**Decision.** If the customer org has a `vat_id`, its country is known and it differs from the seller country (`ARBITER_SELLER_COUNTRY`), tax is 0 with a reverse-charge note. Otherwise tax = subtotal * `ARBITER_VAT_RATE` (default 0). With no seller country configured, the default rate applies and the note says VAT is not configured. The tax decision is stored as a final invoice line.

**Rejected.**
- *Integrate a tax service now.* Cost and contracts before there is volume.
- *No tax handling.* Invoices would be wrong by construction.

**Consequences.** Legal and tax review before public launch is mandatory; the rule is deliberately simple to replace.

---

## D-030 Quote pricing starting values
Date: 2026-10-07. Status: accepted.

**Context.** Quotes must work end to end before real prices exist.

**Decision.** EUR per weighted word: auto 0.02, ai_review 0.04, hybrid 0.07, full 0.12. TM weights: context 0.1, exact 0.1, fuzzy 95-99 0.3, fuzzy 85-94 0.6, fuzzy 75-84 0.8, new 1.0, repetitions 0.1. Semantic matches are never leverage (R-TM-04). Minimum charge 5 EUR. Per org overrides in `org.settings.pricing`; per client overrides via price lists (D-040).

**Rejected.**
- *No defaults (owner must configure first).* Blocks testing and demos.

**Consequences.** These are not market-validated; the owner sets real prices before launch.

---

## D-031 Queue lease 10 minutes, exponential backoff, a dead job item fails the job
Date: 2026-10-07. Status: accepted (refines D-002).

**Decision.** A claimed work item holds a 10-minute lease. Retries back off 5 s, 10 s, 20 s ... capped at 30 min. When a `job.*` item runs out of attempts it is `dead` and the job is marked `failed` with the first line of the error, which surfaces on the exceptions screen.

**Rejected.**
- *Short leases (seconds) with heartbeats.* More moving parts; LLM steps legitimately take minutes.
- *Dead items without failing the job.* Jobs would hang in `running` forever.

**Consequences.** A crashed worker delays its item by up to 10 minutes. Step handlers must be idempotent.

---

## D-032 Webhooks: at-least-once, HMAC-signed, auto-disabled
Date: 2026-10-07. Status: accepted.

**Decision.** Deliveries go through the work queue with retries (`ARBITER_WEBHOOK_MAX_ATTEMPTS`). Header `Arbiter-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`; receivers dedupe on `event_id`. After `ARBITER_WEBHOOK_DISABLE_AFTER_CONSECUTIVE_FAILURES` consecutive failures the webhook is disabled with a reason. URLs must be https outside dev/test and not point at localhost or private addresses.

**Rejected.**
- *Exactly-once.* Not achievable over HTTP without receiver cooperation; dedupe on `event_id` is that cooperation.
- *Unsigned payloads.* Receivers could not trust them.

**Consequences.** Receivers must be idempotent. Runbook section 4 covers re-enabling.

---

## D-033 Evidence pack generated at delivery
Date: 2026-10-07. Status: accepted.

**Decision.** `job.merge` writes the evidence pack (JSON + PDF) from provenance next to the delivered file. For a job still in progress, `GET /jobs/{id}/evidence` builds a live pack without storing it.

**Rejected.**
- *Always build on request.* The delivered pack must not change if code changes later.

**Consequences.** Retention deletes the stored pack with the files; provenance remains.

---

## D-034 In-context 101 TM match with a clean glossary ships without engine or judge (R-TM-03)
Date: 2026-10-07. Status: accepted.

**Decision.** A context match (same source and same neighbouring segments) whose target still satisfies the job's frozen glossary is auto-approved with score 100 and reason `tm_context_match`, without MT or QE. An exact 100 match (no context) is still scored.

**Rejected.**
- *Score every segment.* Cost on content the client already approved in that exact context.
- *Ship exact 100 too.* Same sentence, different context, different meaning is common.

**Consequences.** If glossary terms changed since the TM entry, the segment goes through the normal path.

---

## D-035 Deadline policy
Date: 2026-10-07. Status: accepted (implements D-012).

**Decision.** When a job's review deadline passes with segments still waiting:
- `wait`: record `deadline_waiting`, emit `job.needs_attention`; nothing else changes.
- `ai_fallback`: run the review senate and the AI editor on each waiting segment and mark it `ai_fallback`; a segment with a blocking hard check still waits for a human.
- `partial`: waiting segments are delivered as machine output, decision `unreviewed`, flagged in the evidence pack.
Regulated orgs always wait, whatever the policy. Segments held by a reviewer are left alone. `job.no_reviewer_fallback_used` is set and every change is a provenance event.

**Rejected.**
- *Fallback over blocking checks.* A deterministic failure (dropped tag, missing mandatory term) must not be shipped by a model.

**Consequences.** Customers see in the job, the evidence and the invoice which path was taken.

---

## D-036 Web auth: httpOnly cookie + server proxy; Cache Components off
Date: 2026-10-07. Status: accepted.

**Decision.** The Next app stores the API token in an httpOnly cookie. The browser calls `/api/proxy/*`, the Next server adds the bearer token and forwards to the API (`API_URL` or `NEXT_PUBLIC_API_URL`). `proxy.ts` only routes by role; the API remains the authority. Cache Components are off because every authenticated screen reads the cookie at request time.

**Rejected.**
- *Token in localStorage, browser calls the API directly.* Any XSS steals the token; also needs CORS for every origin.
- *Cache Components on.* No gain for per-user dynamic pages, and cache bugs would leak data between users.

**Consequences.** One extra hop per request. CORS on the API matters only for direct API clients.

---

## D-037 Migration 0001 builds only its own schema (`metadata_0001`)
Date: 2026-10-07. Status: accepted.

**Context.** Migration 0001 used `create_all` from the current models; once Agency OS added tables and columns, a fresh database would get them at 0001 and migration 0002 would collide.

**Decision.** `dbinit.metadata_0001()` is the current metadata minus `LATER_TABLES`/`LATER_COLUMNS`; 0001 creates exactly that. 0002 is hand-written and must produce the same schema as `create_all`. No automated parity test exists yet (open item in memory-bank/progress.md).

**Rejected.**
- *Conditional 0002 ("create if not exists").* Hides drift and leaves two paths to the same schema.

**Consequences.** Every later migration must register its objects in `LATER_TABLES`/`LATER_COLUMNS`.

---

## D-038 Second review excludes the first reviewer via `skipped_by`
Date: 2026-10-07. Status: accepted.

**Decision.** The `second_review` step creates a task with min level senior and lists the first reviewer in `task.expected["skipped_by"]`, the same mechanism that keeps skipped tasks away from a reviewer.

**Rejected.**
- *A dedicated `excluded_reviewers` column.* Second path for the same rule.

**Consequences.** A pair with only one senior reviewer cannot complete second review; the deadline policy applies.

---

## D-039 Client review = existing `review` state + flag
Date: 2026-10-07. Status: accepted.

**Decision.** With a `client_review` step, a job whose segments are all done stays in `review`, records `client_review_requested_at` in its workflow snapshot, emits `job.needs_attention`, and exposes `awaiting_client_approval=true` until `POST /jobs/{id}/client-approve`, then goes `ready` -> merge.

**Rejected.**
- *A new job state `client_review`.* Every state consumer (web, dashboards, exceptions, tests) would change for one optional step.

**Consequences.** Consumers that need the distinction read the flag.

---

## D-040 Price-list rates stored as JSON with decimal strings
Date: 2026-10-07. Status: accepted.

**Decision.** `price_lists.rates` is a JSON list of `{source_lang, target_lang, tier, per_word}` with `per_word` as a decimal string, read back with `Decimal(str(...))`. Lookup: exact pair, then target-only, then tier-only, then org default.

**Rejected.**
- *A rates child table.* More joins and migrations for a list edited as a whole.
- *JSON numbers.* Float rounding on money.

**Consequences.** Validation lives in pydantic (`RateIn`), not in DB constraints.

---

## D-041 Revenue recognised at delivery
Date: 2026-10-07. Status: accepted.

**Decision.** Dashboard and account revenue counts jobs delivered in the period (job revenue split from the quote to the cent). Margin = that revenue minus engine and reviewer cost of the same jobs.

**Rejected.**
- *At order time.* Cancelled and failed jobs would inflate revenue.

**Consequences.** Long jobs show revenue late. Invoicing follows usage records, which is a separate view.

---

## D-042 The AI assistant proposes plans; a human applies them
Date: 2026-10-07. Status: accepted.

**Decision.** `POST /assistant/threads/{id}/messages` returns a reply and a plan of typed actions; nothing changes. The model sees only a compact context summary of the org. Every action is validated with the same pydantic models as the matching endpoint plus semantic rules (workflow validation, widget metrics, regulated tiers); invalid actions are dropped and the reply says so. Later actions may reference earlier ones as `"@<index>"`. Apply runs selected actions in order, each in its own savepoint, skips indices already applied, and reuses workflows, price lists and dashboards with the same name. When the configured model is a mock or fails, a deterministic heuristic planner answers.

**Rejected.**
- *Agent with direct write access.* One wrong guess changes production configuration.
- *All-or-nothing apply.* One invalid action would block an otherwise useful plan.

**Consequences.** Demos and tests work without a model key. Plans stay auditable.

---

## D-043 Archive versus delete per object type
Date: 2026-10-07. Status: accepted.

**Decision.** Objects other records point to are archived on DELETE: CRM accounts (`status: archived`), workflow templates and price lists (`archived_at`). Deals and dashboards are deleted and the response is the object as it was; contacts are deleted (204). An archived price list on an account falls back to org default rates.

**Rejected.**
- *Delete everything.* Projects, jobs and quotes would lose their links.
- *Archive everything.* Clutter for objects nothing depends on.

**Consequences.** List endpoints hide archived rows unless asked (`include_archived`, `status`).

---

## D-044 Login accepts any string as email
Date: 2026-10-07. Status: accepted.

**Decision.** `POST /auth/login` and reviewer apply take `email` as a plain string (apply validates the format itself). Registration still uses strict email validation.

**Rejected.**
- *`EmailStr` everywhere.* It rejects reserved domains such as the fictional demo accounts' `.test`, so seeded users could not log in.

**Consequences.** A malformed address at login is simply "wrong email or password".
