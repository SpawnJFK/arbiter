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
Date: 2026-10-07. Status: superseded by D-080 (production hosting) and D-082 (backups); the compose stack stays for local development and as the emergency fallback.

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

---

## D-045 English-first product; the assistant answers in the UI locale
Date: 2026-10-08. Status: accepted.

**Context.** The market is global. Earlier the setup assistant mirrored the language of the user's input, so a Serbian description produced Serbian workflow and dashboard names inside an English UI.

**Decision.** Every user-visible backend string is English (errors, evidence pack, CLI, seed data). `POST /assistant/threads/{id}/messages` takes `locale` (BCP-47, default `en`, sent by the web app from the UI locale). The model replies in that locale and names everything it creates in it; proper names the user gave stay verbatim. The deterministic built-in planner still understands English and Serbian input but always answers in English; for other locales it adds a note that only the AI model localizes replies. `ASSISTANT_PROMPT_VERSION` 2026-10-08.1.

**Rejected.**
- *Reply in the input language.* Names in the data would not match the UI language and would differ per user.
- *Translate the built-in planner's strings per locale.* It is a fallback for dev and demos; maintaining catalogs for it is not worth it.

**Consequences.** Serbian remains only in parsing keywords, test inputs and en->sr language data (glossary terms, reviewer test items).

---

## D-046 UI strings: English catalog in the web repo, translations in the database
Date: 2026-10-08. Status: accepted.

**Decision.** The English UI catalog is the source and lives in the web repo. Translations are stored in Postgres (`ui_locales`, `ui_messages`), served publicly (`GET /v1/i18n/...`, cached 60 s) and written by the platform admin through import endpoints (merge or replace, optional placeholder check against the English source). Adding a language or fixing a string needs no redeploy. Migration 0003 is hand-written; its tables are in `dbinit.LATER_TABLES`.

**Rejected.**
- *Per-locale JSON files committed per language.* Every fix becomes a code change and a deploy, and translators need repo access.
- *A third-party TMS.* An extra subprocessor and cost for a few thousand strings; we are a translation platform and can run this flow ourselves later.

**Consequences.** The web app must fall back to the bundled English string for missing keys and must send its English catalog as `source` when importing to get placeholder checks.

---

## D-047 Adopt the HYPERPOWER v2 agent operating system, core vendored unchanged
Date: 2026-10-09. Status: accepted.

**Context.** Agents work this repo from zero chat history. Until now the workflow was prose (CLAUDE.md, a Cursor law file, /status and /end) plus a small manifest; nothing could replay a claim of done, nothing tracked executable work across machines, and no guard stopped destructive shell commands. The owner's HYPERPOWER v2 pilot (his EVHub v2 repository) has a working control plane: a project-agnostic, hash-locked core (`.hyperpower/core/`, version 1.0.0) driven by `hyperpower.json` schema 2, an append-only evidence ledger with replayable verifiers, a phase gate that closes a Beads issue and reads it back, soft git hooks and a Cursor shell guard.

**Decision.** Copy `.hyperpower/core/` byte for byte (14 files, `core.lock.json` unchanged, doctor reports no drift) together with `schemas/` and the tool registry (bd 1.3.1, OSV-Scanner 2.6.0, Betterleaks 1.9.0, Graphify 0.9.28, each with SHA256 and licence). Everything project specific lives outside the core: `hyperpower.json`, `phases/`, `ACCEPTANCE.md`, `evidence/`, `.beads/`, `.githooks/`, `.cursor/` and the scripts the hooks and verifiers call. Monorepo adaptations are made in those scripts, never in the core: `npm run verify` chains a runtime check, the API checks (ruff, pytest in the venv) and the web checks (lint with i18n, tsc, build); verifier scripts take no arguments because the core's `cli` verifier rewrites node arguments into paths; the `sql` verifier runs through psycopg in the API venv instead of a Node driver; Playwright and Impeccable are listed under `tools.requiredOutsideRegistry` because core status only looks at the repo root. The Impeccable engine binary is not vendored (the skill's launcher downloads it with a SHA256 sidecar check), so its pre-edit hook is written but not wired until P00 installs the engine.

**Rejected.**
- *Patch the core for the monorepo* (status lookup in `apps/web/node_modules`, a Python runtime check in doctor). Breaks the hash lock and the promise that one core serves every project; the same effect is reachable from project files.
- *Write a lighter Arbiter-only workflow.* Re-learns the pilot's failures (guards that skipped silently, phases closed by chat claims).
- *Vendor the 14 MB Windows Impeccable binary.* Large binary in git for a tool the launcher installs verifiably.

**Consequences.** Every phase closes through `npm run hp -- gate P0x --product`. Nothing in the layer is proven on the owner's Windows machine until P00. A future core release is copied whole and re-locked with a new decision entry.

---

## D-048 Phase plan moves to root `phases/`, renumbered P00 to P08
Date: 2026-10-09. Status: superseded by D-090 (plan rewritten as P00 to P09 on 2026-10-13).

**Context.** The plan lived in `docs/phases/phase-0..6.md` with ROADMAP numbers P0 to P6, where P0 mixed built foundation, open measurement and ops, and P1/P2 mixed built features with launch work. The HYPERPOWER format needs one file per gateable phase with Goal, Scope, Human-only steps, Declared spend, Acceptance, Exit gate, Out of scope, and an order table.

**Decision.** `phases/README.md` holds the frozen order: P00 install and verify on Windows, P01 measurement harness, P02 staging deploy on Hetzner, P03 money and legal readiness, P04 self-serve launch, P05 integrations, P06 Okapi formats, P07 enterprise, P08 white-label. Everything already built is listed as built in `phases/README.md` and in the phase files' "Already built" sections, not as open scope. The README maps earlier numbers to new ones; older decision entries keep their original numbers. `docs/phases/` is removed and every live reference points to `phases/`.

**Rejected.**
- *Keep P0 to P6 and add HYPERPOWER sections to the old files.* P0 would never pass a gate: its ops items need a server that P0 has no reason to create, and its foundation items are long done.
- *One phase for deploy plus money plus legal.* Too many human steps and too much spend under one "apply".

**Consequences.** ROADMAP.md uses the new numbers. Payment provider, payout provider, legal and tax review moved earlier as one phase (P03) before the launch phase (P04).

---

## D-049 Node 24 pinned by `.node-version`; Python 3.13 checked by `check:runtime`
Date: 2026-10-09. Status: accepted.

**Context.** `.nvmrc` pinned Node 22 while the owner's machine runs fnm with Node 24 as default, and the HYPERPOWER doctor fails on a Node major that differs from `hyperpower.json`. Python was pinned in `.python-version` but nothing checked it.

**Decision.** `.node-version` with `24` replaces `.nvmrc` (fnm reads both; one file only). `hyperpower.json` `runtime.node.major` is 24 with an upgrade window to 26 on 2026-11-15, taken at the start of a phase, never mid-phase. CI's web job reads `.node-version`, the web Docker image moves to `node:24-alpine`, root `package.json` declares `engines.node >=24 <25`. `npm run check:runtime` (first step of `npm run verify`) checks Node against `.node-version` and the API venv's Python against `.python-version`.

**Rejected.**
- *Stay on Node 22.* Doctor would report BROKEN on the owner's machine every session.
- *Move straight to Node 26.* Not LTS on the date of this decision.

**Consequences.** The web build and lint were re-run on Node 24 in the cloud session. P00 proves the pins on Windows.

---

## D-050 `.cursor/mcp.json` is untracked; only `.cursor/mcp.json.example` is in git
Date: 2026-10-09. Status: accepted.

**Context.** `.cursor/mcp.json` was tracked with the hosted Context7 entry and no key. Context7 works best with a key, and a key must never be committed.

**Decision.** `git rm --cached .cursor/mcp.json`, gitignore it, track `.cursor/mcp.json.example` with placeholders (Context7 required, GitHub optional, hosted HTTP forms only). The agent writes the real file with the key in P00 and the owner restarts Cursor.

**Rejected.**
- *Keep the tracked file without a key.* Invites someone to add the key to a tracked file.
- *Read the key from an environment variable in the file.* Cursor's support for env interpolation in MCP headers differs across versions; a gitignored file is predictable.

**Consequences.** Pulling the commit that untracks the file deletes the owner's local copy; Context7 in Cursor is off until P00 item 16 writes the new file.

## D-051 Blob storage behind one interface (local or S3) with presigned direct uploads; email through the work queue
Date: 2026-10-13. Status: accepted.

**Context.** Uploads of up to 1 GB went through the API as multipart bodies, which does not survive a CDN or proxy body limit and ties files to one box. There was no way to send email (password reset, invites, job notifications).

**Decision.** `arbiter/storage.py` exposes one `Storage` protocol with two backends picked by `ARBITER_STORAGE_BACKEND`: `local` (files under `storage_dir`, direct uploads go to the API's own HMAC-signed `PUT /v1/uploads/{id}/blob`) and `s3` (any S3-compatible store, browser PUTs to a presigned URL and downloads through presigned GETs). The browser flow is the same in both: `POST /v1/uploads`, PUT the bytes, `POST /v1/uploads/{id}/complete`. Email is queued: `notify.queue_email()` writes an `email_messages` row and an `email.send` work item in the caller's transaction; the worker sends through `log` (dev, test) or `smtp`. Single-use links (password reset) store only a SHA-256 in `account_tokens`.

**Rejected.**
- *Keeping multipart uploads only.* Body limits at the edge and memory pressure on the API for large files.
- *Sending email inline in the request.* A slow or failing mail server would fail or roll back the change that caused the email.
- *A provider-specific email SDK.* SMTP works with every transactional provider, so switching is a settings change.

**Consequences.** `POST /v1/files` stays for small files and as a fallback. Delivery state of every email is visible in `email_messages`; dead `email.send` items mark the message `failed`.

## D-052 Module gating at router level; disabled module = 404 `module_disabled`
Date: 2026-10-13. Status: accepted.

**Context.** Arbiter is sold as separable modules (`platform/modules.py`). Existing routes had no notion of entitlement, and the web showed every section to everyone.

**Decision.** Each product route module declares `APIRouter(dependencies=[require_module("<key>")])`, so a new route in that file is gated without anyone remembering to add it. Entitlements stay in `org.settings["modules"]`; the platform admin edits them with `PUT /v1/admin/orgs/{id}/modules` (billing will write the same list). `Org.modules` in `/me` carries the effective list and the web hides nav sections of disabled modules. Module isolation is checked statically (`tests/platform/test_module_isolation.py`, ast), with the six cross-module imports that already existed listed as known debt.

**Rejected.**
- *A middleware mapping URL prefixes to modules.* A second place that must know every path; a renamed route silently becomes ungated.
- *403 for a disabled module.* The feature does not exist for the org; 404 matches the tenancy rule and does not advertise what could be bought.
- *Importing each package with another one deleted (sys.modules tricks).* Slow, flaky and order-dependent in one interpreter; the static check gives the same guarantee for imports.

**Consequences.** Platform routes (auth, org, API keys, webhooks, usage, invoices, i18n, roles, team, audit, SSO) are never gated. Paying down the known debt (`engines.tags` used by quality, `quality.prompts` by engines, `engines.registry` by agency) means moving those helpers behind contracts.py.

## D-053 Custom roles replace the base role's permissions; escalation guards; `audit.read` is explicit-only
Date: 2026-10-13. Status: accepted.

**Context.** Agencies need roles beyond pm and client (auditor, team lead, finance). The permission seam already allowed a principal-level override.

**Decision.** `roles` table per org with `base_role` (pm or client, drives the coarse route guards) and `permissions` (patterns). A user with `role_id` gets exactly those permissions for `require_permission` checks; an empty list grants nothing. Nobody grants a permission they do not hold (`permissions.covers`), only a pm creates or assigns pm-based roles, nobody changes their own role, and an org always keeps one active pm. Team and role writes need a signed-in user, never an API key. `audit.read` is not granted by `*.read`, so clients and API keys do not read the audit log by default.

**Rejected.**
- *Custom permissions added on top of the base role.* Then a restricted role (read-only auditor) is impossible to express on a pm base.
- *Permission-only routing with no base role.* Every existing route uses coarse role guards; rewriting all of them in this change is too large and risky.

**Consequences.** Coarse guards still decide which routes a user can reach at all; permissions refine access on routes that check them (platform routes now; other modules can adopt `require_permission` gradually).

## D-054 Audit log: append-only table, written in the request transaction
Date: 2026-10-13. Status: accepted.

**Context.** Enterprise buyers ask who changed org settings, keys, roles, SSO and production data.

**Decision.** `audit_events` with a trigger rejecting UPDATE and DELETE (same pattern as provenance). `platform.audit.audit()` adds the row in the caller's session, so the event commits or rolls back with the change. A pure ASGI middleware puts client IP and user agent in a context variable; `X-Forwarded-For` is used only with `ARBITER_TRUST_PROXY_HEADERS`. Secret-looking keys in `data` are redacted; the CSV export guards against spreadsheet formula injection.

**Rejected.**
- *A generic middleware that logs every non-GET request.* No target ids or before/after values, and it logs failed requests as if they happened.
- *Writing audit rows in a separate transaction.* Events for changes that were rolled back would remain.

**Consequences.** Failed logins are not audited yet (the request transaction rolls back); that needs a separate short transaction and rate limiting, a later item.

## D-055 SSO: OpenID Connect code flow with PKCE, domains proven by DNS TXT, pyjwt + httpx
Date: 2026-10-13. Status: accepted.

**Context.** Enterprise customers require login through their IdP. The stack already has pyjwt and httpx; authlib was an option.

**Decision.** One OIDC IdP per org (`sso_configs`), client secret encrypted with Fernet under `ARBITER_SECRETS_KEY` (comma-separated keys for rotation). Email domains (`sso_domains`) route logins to an org only after a DNS TXT record (checked through DNS-over-HTTPS) or a platform admin verifies them. Login state, nonce and PKCE verifier live in a single-use `sso_states` row, consumed before validation. The id_token is checked with pyjwt against the IdP JWKS fetched with httpx (asymmetric algorithms only, issuer, audience, azp, expiry, nonce, `email_verified` not false). Unknown users are provisioned with the org's default role; an email owned by another org is never taken over. `enforce_sso` blocks password login and requires a verified domain first.

**Rejected.**
- *authlib.* A large dependency for a flow of about 200 lines; its JWKS fetching is harder to stub with httpx.MockTransport.
- *Stateless signed state (JWT in the state parameter).* Cannot be made single use without a store, and would expose the PKCE verifier in the URL.
- *Trusting a domain because the configuring admin's email is in it.* Anyone can register with any address; that is not proof of control.
- *SAML now.* Most target IdPs (Entra ID, Okta, Google Workspace) speak OIDC; SAML is a later item.

**Consequences.** The web exposes `/api/sso/start` and `/api/sso/callback`; the IdP must allow `<ARBITER_WEB_BASE_URL>/api/sso/callback` as redirect URI. SCIM provisioning and SAML are later items.
---

## D-056 Engine keys in the database, encrypted, resolved org BYOK > platform > environment
Date: 2026-10-13. Status: accepted.

**Context.** Engine keys lived only in `ARBITER_*` environment variables: one key per provider for the whole platform, changed by a redeploy. The engine module is sold to enterprises that bring their own provider contracts, and the platform admin needs to rotate keys without a deploy.

**Decision.** Table `engine_credentials` (scope `platform` or `org`, provider, label, encrypted secret, `secret_hint` with the last 4 characters, non-secret `config` JSON for model, region, endpoint, project, prices, enabled, last test result). Secrets are encrypted with Fernet from `cryptography` using `ARBITER_SECRETS_KEY` (comma separated, first key encrypts, all decrypt, so keys rotate without a data migration); prod refuses to store a secret without it. The API never returns a secret after save. Per call, `arbiter.engines.credentials.resolve` picks the org's enabled BYOK key, else the newest enabled platform key, else the environment (the behaviour before this decision). `registry.get_llm/get_mt/available_*` take an optional `EngineContext(session, org_id)`; without it they behave exactly as before. OpenAI-compatible endpoints are one engine per credential (`compat:<id>`). The test-environment fence (mocks only) is unchanged: database keys are never used in tests.

**Rejected.**
- *A cloud secret manager (AWS Secrets Manager, Vault).* Another service and account to run before launch; Fernet at rest with the key outside the database gives the same property (a database dump alone reveals nothing) at no cost. Can be added behind `arbiter.crypto` later.
- *pgcrypto in SQL.* The key would travel in SQL statements and end up in query logs.
- *Storing secrets in `org.settings`.* No encryption boundary, returned by every org read.

**Consequences.** Losing `ARBITER_SECRETS_KEY` makes stored keys unreadable (they must be entered again). `POST /engines/{id}/test` makes one tiny real call in dev and prod; tests stub `arbiter.engines.probe.run_probe`.

---

## D-057 EU processing: Bedrock EU inference profiles, Vertex "eu", DeepL; no silent fallback
Date: 2026-10-13. Status: accepted.

**Context.** Claude goes through Anthropic's own API by default (global processing). EU customers, regulated ones first, need every AI and MT call processed in the EU. This is sold as an add-on.

**Decision.** `org.settings["processing_region"]` is `global` (default) or `eu`, set through `PATCH /org` (needs the `eu_processing` add-on; regulated orgs may use it). Every engine declares `region` (`eu`, `us`, `global`, or `local` for in-process mocks); `MtEngine` and `LlmClient` in `contracts.py` gain the attribute. New LLM clients: `engines/bedrock.py` (Converse API through boto3; region derived from the model id, so `eu.anthropic.claude-*` geographic inference profiles count as EU), `engines/vertex.py` (rawPredict on Vertex with a service-account JWT exchanged for an OAuth token through pyjwt + httpx; default location `eu`, host `aiplatform.eu.rep.googleapis.com`, overridable per credential), `engines/openai_compatible.py` (region declared by the admin, default `global`). DeepL is EU. For an EU org the router keeps only `eu`/`local` engines; when nothing is left the job fails with "no EU engine configured" (provenance `routing_blocked`), never a fallback outside the EU. Processing region, engine and model are written to provenance (`engine_route`, `target_set`, `qe_scored`) and to a `processing` block of the evidence pack.

**Rejected.**
- *Regional Anthropic API endpoints.* Not offered for this use; Bedrock and Vertex EU are the documented ways to keep Claude traffic in the EU.
- *Falling back to a global engine when no EU engine is configured.* A silent breach of what the customer bought.
- *Google SDKs (google-auth) for Vertex.* Two HTTP calls do the job; pyjwt and cryptography are already dependencies.

**Consequences.** The Vertex multi-region host and the exact Bedrock profile ids must be checked against the provider consoles before the first EU customer (no Context7 in the build session). Training providers that serve from the US cannot be used by EU orgs (D-059).

---

## D-058 Engine routing rules and monthly budgets
Date: 2026-10-13. Status: accepted.

**Context.** R-MT-02 ordered engines by the scoreboard, then the settings default. Agencies want explicit rules per pair and content type (e.g. DeepL for EN to DE legal), per purpose (MT, judge, senate, editor), and a cost ceiling per provider.

**Decision.** Table `engine_routes` (org_id null = platform default; source_lang, target_lang, content_type nullable = any; purpose; ordered `engines`; `fallback`; enabled). Precedence in `arbiter.engines.routing.choose`: org rule before platform rule, then the rule with more matching fields, then the scoreboard (MT only), the settings default and anything available; `fallback=false` stops after the rule's own list; senate and editor fall back to the judge rule. Then the region filter (D-057) and the budget filter. Table `engine_budgets` (org, provider, monthly cap, currency, period, spent) is checked before calls (capped providers are dropped by the router, and wrappers check again before each call) and charged after each call with one atomic UPDATE. When every engine is capped the job stays `running`, provenance records `engine_budget_exceeded`, a `job.needs_attention` webhook (`budget_exceeded`) goes out at most once a day, and the step is retried every hour, so raising the cap or a new month resumes the job without anyone touching it.

**Rejected.**
- *Failing the job when the cap is reached.* The owner would have to find and resume every job by hand after raising the cap.
- *A rule priority number set by hand.* Specificity is what people mean; numbers drift and collide.
- *Counting spend from `usage_records`.* Those hold billable units for the customer, not provider cost per provider.

**Consequences.** Spend is an estimate from pricing.py. The orchestrator now resolves judge, senate and editor clients separately (`_judge(session, job, purpose)`); `_judge()` without arguments keeps the old behaviour.

---

## D-059 Own models: per-client LoRA fine-tunes with consent, measured on the scoreboard
Date: 2026-10-13. Status: accepted.

**Context.** A model trained on one client's approved translations can beat general engines for that client. It must never be trained without consent, never trained on another client's data, and only used when it measures better.

**Decision.** `arbiter/training/`: dataset export (only segments a human approved, one org, one pair, one domain, only while `org.settings["training_consent"]` is true; dedupe by source; tags converted to `<gN>..</gN>`/`<xN/>`; deterministic train/validation split by a hash of the source; chat-format JSONL), a `TrainingProvider` protocol with Together and Fireworks adapters (fine-tune REST APIs through httpx) and a manual provider that only exports the dataset. Tables `training_jobs` (state machine `training` in `domain/states.py`) and `custom_models` (an OpenAI-compatible endpoint registered as engine `custom:<id>`, region declared). After training the worker (`training.poll`, `training.evaluate` work items) translates the held-out set with the new model, scores it with the org's judge route and writes `engine_scores`; an admin activates the model, and the scoreboard (minimum `ARBITER_CUSTOM_MODEL_MIN_EVAL_SEGMENTS`) decides whether it is used. EU orgs may only train with the manual provider and only EU-declared models are evaluated for them.

**Rejected.**
- *Training on all customers' data for one shared model.* No consent model allows it and it leaks one client's terminology to another.
- *Hosting GPUs ourselves now.* Capital and operations before demand is proven; the manual provider keeps that door open.
- *Activating a model automatically after training.* A human decides; the scoreboard numbers inform the decision.

**Consequences.** Together and Fireworks request shapes were written from public docs without Context7 and are covered only by stubbed tests; one small real job per provider is needed before the first customer job.
---

## D-060 Software strings: own key-value model, copy-on-write branches, merge by base version
Date: 2026-10-13. Status: accepted. (Parallel branches may also use this number; renumber at merge.)

**Context.** The `strings` module (the Lokalise / Phrase Strings / Crowdin category) needs keys with values per language, plurals, branches for feature work and releases. The document pipeline (files, jobs, segments) models paragraphs of one file in one language pair per job, which fits neither keys that live for years nor many target languages per key.

**Decision.** New tables (migration 0007): `string_projects`, `string_branches` (a real `main` row per project), `string_keys` (unique per project + namespace + name, created in a branch), `string_translations` (one row per key, branch and language; the base-language text is a translation row too; plural and array values in `forms`), append-only `string_history` (trigger like provenance), `string_releases`, `string_batches`. Parsers live in `arbiter/strings/formats/`, separate from `fileproc` (document formats). Branches are copy-on-write: writing in a branch copies the main row and records `base_version`; reads prefer the branch row. Merge applies branch rows whose main row is still at `base_version`; a main row that moved on is a conflict the user resolves per key and language (keep branch or keep main). Key metadata (description, max length, tags) is shared by every branch; only key creation and values are branch scoped. Branches are created from main only.

**Rejected.**
- *Reuse jobs and segments for strings.* One job per language pair and file and a segment state machine built for delivering a file; keys would be duplicated per job and their history scattered.
- *Snapshot (full copy) branches.* Simple reads, but a project with 20k keys and 30 languages copies 600k rows per branch.
- *Git-style three-way text merge.* Translations are short values; a per-value conflict with both versions shown is clearer and enough.
- *Nested branches.* Row versions in different branches are not comparable; main-only parents keep conflict detection exact.

**Consequences.** Key renames and metadata edits made in a branch are visible in main at once. Two branches cannot create the same key name (the second gets 409 until the first is merged).

---

## D-061 Human review of strings through carrier jobs, not a second task type
Date: 2026-10-13. Status: accepted.

**Context.** Strings need the same reviewer community (routing by pair and level, holds, pay, control grading, disputes). `review_tasks.segment_id` is a foreign key to `segments`, and every community flow reads the segment.

**Decision.** `arbiter/strings/review.py` creates, per string project and target language, a carrier `Project` + `FileAsset` (format `strings`, no file) + `Job` whose workflow snapshot is `{"adapter": "strings", "steps": []}`, and one `Segment` per translation and form holding the placeholder-protected source and the machine target. `review_queue.create_task()` queues it like any pipeline segment. `pipeline/hooks.segment_reviewed` dispatches segments of adapter jobs to the module (`hooks.ADAPTERS`, imported lazily); the module restores placeholders, writes the value back (reviewed once every form is reviewed), stores it in the TM and closes the carrier job. The worker gained `MODULE_HANDLERS` for module-owned work items (`strings.translate`).

**Rejected.**
- *A `string_translation_id` column on review_tasks (nullable segment_id).* Touches every community query, the reviewer cockpit, pay and disputes; high risk for the existing flows.
- *A strings-only reviewer queue.* Duplicates routing, holds, scoring and payouts.

**Consequences.** Carrier projects show in the customer's project list as "Strings review: <name>". Carrier jobs never get pipeline steps, deadlines or invoices; reviewer pay is booked to the carrier job's `cost_reviewers`. The no-reviewer policy is not applied to strings yet (translations stay `machine` with `needs_review`).

---

## D-062 Strings translation flow, states and what ships
Date: 2026-10-13. Status: accepted.

**Context.** Strings must use the same engines, TM, glossary, hard QA, QE judge and tier rules as documents, but an app string ships continuously, not as a delivered file, and a broken placeholder crashes the app.

**Decision.** Placeholders (ICU, printf, iOS, Android, Rails, mustache, template literals, inline markup) become standalone codes before TM and engines, so the document hard checks (`tag_missing`, ...) catch a dropped or invented placeholder; string QA adds placeholder, ICU, plural-form and length checks on the restored value. TM context for a string is the key itself (101 = same key, same source). `quality.qe.decide` with the project tier maps to states: `auto_approve` -> `reviewed`; `senate` and `review` -> `machine` + `needs_review` (+ a review task when `human_review` is on and the org has the community module); blocking QA -> `blocked`. `approved` is a human sign-off (editor or bulk approve). Releases and pulls take `release_min_state` (default `machine`) and never ship blocked translations; with `fallback_to_base` (default) the base text fills gaps so an app never shows a raw key. Changing a base text drops reviewed and approved translations of that key back to `machine`. `strings.publish` was added to the built-in pm and api roles. The senate band is not convened for strings yet; it is treated as needs review.

**Rejected.**
- *Ship only reviewed translations by default.* Most software teams ship machine output early and review later; the setting covers stricter teams.
- *Treat placeholders as plain text and rely on regex QA only.* Engines then see and sometimes translate `{name}`; codes make them untouchable.

**Consequences.** OTA bundles are immutable per version (cached for a year) and `latest` is short-cached with ETag revalidation. Private projects use a distribution token (only its hash is stored); the internal project id never appears in public URLs.
---

## D-063 Editor splits and merges map back onto extraction slots (`signals.slots`)
Date: 2026-10-13. Status: accepted.

**Context.** The workbench splits and merges segments inside a unit, but every format handler merges a target map with exactly the segment count of the extraction (`resolve_segments` refuses anything else).

**Decision.** Each segment carries `signals["slots"]`: 1 as extracted, 0 for the second half of a split (its target is appended to the previous slot), k for a merge of k extracted segments (target in the first slot, k-1 empty slots). `pipeline/units.py` regroups segments into slots for `merge()`, the XLIFF export and the live preview. Splits keep the exact source on both sides (no character lost), merges join sources with one space (none for zh/ja/th/lo/km/my, none when re-merging a split).

**Rejected.**
- *Re-extract and re-segment the unit on merge.* The translator's segmentation would be lost and targets would have to be redistributed by guesswork.
- *Teach every handler variable segment counts.* Ten handlers, each with round-trip guarantees; one regroup function is safer.

**Consequences.** A merged segment ends with the inter-sentence whitespace of the original unit moved after it (for example a trailing space in a Markdown paragraph); harmless in markup formats, visible in plain text. Merge refuses two segments that reuse a code id.

---

## D-064 Auditor runs on the work queue in batches, AI judge sampled deterministically
Date: 2026-10-13. Status: accepted.

**Context.** Standalone audits of bilingual files can have tens of thousands of segments, need visible progress and must keep AI cost under the customer's control.

**Decision.** `audit.parse` reads the file into `audit_segments`, `audit.check` handles 100 segments per work item and commits progress, `audit.finish` runs consistency checks, the scorecard (quality/scorecard.py, shared with job LQA) and records AI usage. Idempotency keys include an attempt number so a retried audit runs again. `ai_mode` none | sample | full; sample picks `ai_sample_pct` of the segments by hash of audit id and position (a rerun samples the same segments). Hard QA issues count in the MQM score (blocking or error = major, warning = minor, info = neutral).

**Rejected.**
- *One work item for the whole audit.* No progress, and a crash late in a big file redoes everything.
- *Random sampling.* Two runs of the same audit would disagree.

**Consequences.** A new state machine `audit` in domain/states.py (queued, running, done, failed; failed -> queued on retry). The worker marks an audit failed when its item dies.

---

## D-065 Sentence alignment: Gale-Church with an embedding term, banded, pure Python
Date: 2026-10-13. Status: accepted.

**Context.** TM alignment and document-pair audits need sentence alignment without new heavy dependencies (no numpy in the API image).

**Decision.** linguistic/align.py: Gale-Church dynamic program over 1-1, 1-0, 0-1, 2-1, 1-2, 2-2 beads with the classic priors, plus SIM_WEIGHT x (1 - cosine) of the sides' embeddings (folded 256 -> 64 dimensions), inside a diagonal band; above 2 million cells it falls back to lengths only. Confidence = 0.7 x length probability + 0.3 x similarity. Aligned pairs are stored as plain text (two separately extracted files do not share code ids).

**Rejected.**
- *Hunalign or bleualign as a sidecar.* Another process and dictionary per language pair for a first version.
- *Embedding-only alignment.* With the mock provider cross-language similarity is weak; lengths carry most of the signal until a multilingual embedding provider is configured.

**Consequences.** Omitted long sentences tend to become 2-1 beads rather than 1-0 (a known Gale-Church weakness); the review grid shows confidence so a human catches them before commit.

---

## D-066 Comments are internal, queries are the client channel
Date: 2026-10-13. Status: accepted.

**Context.** Translators and PMs need notes on segments; some questions must go to the client, who should not see internal discussion.

**Decision.** `segment_comments.kind` comment | query. Client users see only queries, cannot open threads and answer by replying; a client reply reopens a resolved query. A new query emits the new webhook event `job.query.opened`. Comments survive a segment merge (re-pointed to the survivor, no FK).

**Rejected.**
- *One kind with a visibility flag.* Easy to leak an internal note by toggling the wrong flag.

**Consequences.** `/queries` is the client portal inbox; the editor filters segments by open queries.
## D-067 Own vendors are a separate model from the reviewer marketplace (module pm)
Date: 2026-10-13. Status: accepted. (Numbered in a parallel build; renumber on merge if the range is taken.)

**Context.** Agencies run their own pool of freelance translators, reviewers and partner agencies (rates per pair and service, NDAs, availability, payment details) next to, or instead of, the platform's reviewer community.

**Decision.** New tables `vendors`, `vendor_absences`, `vendor_documents` (migration 0009), owned by one org and managed through `/vendors`. Rates are JSON rows `{source_lang?, target_lang?, service, unit, rate, currency}` with the price-list lookup order (pair, target, any); a `minimum` unit is the least paid per assignment. Weekly capacity is `capacity_words_per_day` plus `working_days`; absences are date ranges.

**Rejected.**
- *Reuse `reviewer_profiles` with an org_id.* Marketplace reviewers are platform users with tests, scores, DAC7 data and ledger payouts; own vendors have none of that and must never be visible to other orgs or paid through the platform ledger.
- *A `vendor_rates` table.* Rates are always read and edited with the vendor; JSON keeps the profile one row, like price lists.
- *A per-day availability table.* Capacity per day is derived (weekly capacity minus booked work minus absences), so nothing has to be kept in sync.

**Consequences.** Vendor money is the agency's accounts payable (purchase orders, vendor invoices), never `ledger_entries`.

## D-068 Human step routing: a live assignment holds the step; the marketplace stays the default
Date: 2026-10-13. Status: accepted.

**Context.** Per job and step (human_review, second_review) the PM must choose the marketplace, an own vendor or an internal user, without breaking the existing pipeline.

**Decision.** `vendor_assignments` rows; the orchestrator's `_queue_review` asks `assignments.route_for(job, step)` (only when the org has the pm module). With a live assignment (pending, offered, accepted, in_progress, delivered) no review task is created: the segment stays `needs_review` with `signals.route`, a `routed` provenance event is written, and the assignee decides in the vendor workbench through `hooks.segment_reviewed`, exactly like a reviewer. `reroute_open_segments` moves open segments between routes when the PM changes the assignment (queued marketplace tasks are deleted; held ones stay with their reviewer and a late duplicate is a no-op). Control samples and escalations always go to the marketplace. Offers to a ranked list are one `offer_group`: sequential (timeout work item `vendor.offer_timeout` moves to the next rank) or broadcast (first to accept wins); an exhausted group returns the step to the marketplace and emits `job.needs_attention` (`vendor_unassigned`). Assignment, purchase order and vendor invoice states live in `domain/states.py` (`transition_status`).

**Rejected.**
- *Create review tasks anyway and reserve them for the vendor.* Vendors are not reviewer profiles; the task queue, holds, pay and control grading would all need vendor branches.
- *Store the route in the frozen `job.workflow` snapshot.* The route changes during the job (declines, timeouts, PM changes); the snapshot is meant to stay frozen.
- *Hard dependency of the pipeline on the agency package.* The import is lazy and module-gated, so removing pm leaves the marketplace behaviour unchanged.

**Consequences.** The deadline policy still applies to vendor-routed segments (it works on open segments, with or without tasks). `report_error` only touches the reviewer score when the reviewer id is a marketplace profile.

## D-069 Purchase orders on acceptance; vendor invoices uploaded or generated; job cost includes vendor fees
Date: 2026-10-13. Status: accepted.

**Context.** The agency needs a PO per accepted job, a way to receive or produce vendor invoices, a monthly payables view and an accounting export, and the job margin must include what the vendor costs.

**Decision.** One PO per accepted vendor assignment, numbered per org and year from `number_series` (`PO-2026-0001`, row-locked), PDF rendered on request with reportlab. A vendor invoice covers approved assignments of one vendor and one currency: uploaded (workbench or PM, the vendor's own number, total must match) or generated (`VI-2026-0001`). Covered assignments and their POs become `invoiced`; a rejected invoice returns them to `approved`/`issued` (the only backward transitions, in `states.py`). Approving delivered work adds the fee to the new `jobs.cost_vendors` when it is in the platform currency; a foreign-currency fee is recorded in provenance and not converted. Job `cost`/`margin`, CRM and dashboard margins add `cost_vendors`.

**Rejected.**
- *Issue the PO at offer time.* Offers to a ranked list would produce POs nobody accepted.
- *Silent FX conversion of vendor fees.* No rate source is configured; a wrong margin is worse than a flagged one.

**Consequences.** Tax treatment of vendor invoices needs legal and tax review before public launch.

## D-070 Capacity planning and deadline risk are derived on read
Date: 2026-10-13. Status: accepted.

**Context.** PMs ask who is free for a pair and volume by a date, and which jobs will miss their deadline.

**Decision.** `agency/capacity.py` computes per vendor and day: capacity on working days outside absences, load = remaining words of accepted and in-progress assignments spread evenly to their due date (or booked at full capacity from today without one), free = capacity - load. The planner ranks vendors by can-meet, earliest finish, price, rating. Deadline risk divides the remaining human words per step by the route's capacity (vendor free capacity; internal and marketplace words per day from `org.settings.pm`, defaults 4000 and 20000, documented as assumptions) and flags jobs whose estimated finish is after `due_at`; `/exceptions` shows them as `deadline_risk`.

**Rejected.**
- *A scheduling solver or stored bookings.* Over-built for the decision a PM makes; derived numbers never go stale.
- *Marketplace throughput from history.* No production history yet; a configurable assumption is honest and replaceable later.

**Consequences.** Numbers are estimates and the UI says so. Timezones are UTC dates.

## D-071 PM copilot: facts first, plan-then-apply kept
Date: 2026-10-13. Status: accepted.

**Context.** The assistant should answer "who is free...", "which jobs are at risk", "propose assignments for job X" and "draft a quote for client Y" without letting a model invent capacity or prices.

**Decision.** `agency/copilot.pm_query` parses the question (`heuristic_pm.parse_pm`, English and Serbian) and computes the answer from the database before the model is called; the result goes into `context.pm.query` and the system prompt (version 2026-10-13.1) tells the model to quote it. The built-in planner answers from the same result (`heuristic_pm.pm_answer`). New plan actions `create_assignment` and `draft_quote` are applied by a human like every other action; a draft quote becomes a CRM deal in stage `proposal` (a real quote needs a file for TM analysis).

**Rejected.**
- *Give the model tools to query the database.* The single-shot plan contract and its validation stay simpler and testable with mocks.
- *Draft quotes as `quotes` rows without a file.* Quotes are file analyses (TM bands, repetitions); a deal holds a priced proposal honestly.

**Consequences.** Without the pm module no pm facts reach the model and pm actions are dropped by validation.
---

## D-072 Subscription billing: Paddle as merchant of record, our database as source of truth
Date: 2026-10-13. Status: accepted (owner approved).

**Context.** Arbiter sells modules globally by card from day one and needs VAT and sales tax collected and filed in many jurisdictions, chargebacks handled and enterprise invoices with terms, PO numbers and bank transfer. There is no company yet in a country Stripe supports for this setup.

**Decision.** Paddle Billing is the payment provider and merchant of record now; Stripe is a second rail added later. Plans, subscriptions, entitlements, usage, credits and invoice records live in our database (migration 0010: `plans`, `credit_packs`, `subscriptions`, `billing_customers`, `credit_ledger`, `billing_events`). Each provider is a thin adapter behind `billing/providers/base.py` (`create_checkout`, `create_credit_checkout`, `customer_portal_url`, `cancel`, `add_charge`, `report_usage`, `parse_webhook`, `invoice_document_url`): `paddle.py` (API v1 over httpx), `stripe.py` (same interface, off unless configured and selected), `manual.py` (our own invoice, admin marks it paid). Access starts only when the provider confirms payment through a signed webhook; every webhook is stored once per `(provider, event_id)` and applied in a savepoint, a failed one is kept with its error and answered 500 so the provider retries. Plans are data seeded with starter values (Starter, Team, Business, Enterprise) and edited in the admin plans editor. The registry picks: org override, then `ARBITER_BILLING_PROVIDER`, then auto (Paddle when configured, else manual).

**Rejected.**
- *Stripe first.* Needs a company in a supported country and leaves tax registration and filing to us.
- *Provider as source of truth (read plans and entitlements from Paddle).* Ties every module check to a provider call and makes the Stripe rail a rewrite.
- *Lemon Squeezy or similar resellers.* Weaker subscription and enterprise invoicing tooling for this use; Paddle covers invoices with terms.
- *Plans in code.* Every price change would be a deploy.

**Consequences.** Adding Stripe later is configuration plus price mapping, not a rewrite. Paddle needs a client-side token and an approved domain for the `/checkout/paddle` page (Paddle.js opens the overlay for `?_ptxn`). Live keys, the default payment link and the webhook destination are P03 human steps.

---

## D-073 Payout rails and the platform fee
Date: 2026-10-13. Status: accepted (owner approved).

**Context.** Reviewers and vendors are paid worldwide. Payout fees differ by rail, and the marketplace charges the paying customer a transparent fee on human work.

**Decision.** `community/payout_rails/` adds Payoneer (Mass Payouts API style, payee registration link, payout request, status polling), PayPal (Payouts API batch, OAuth client credentials, polling) and a bank-file rail (SEPA pain.001.001.09 XML, plain CSV, Wise batch CSV for manual upload, admin confirms). `RailRouter` is the `PayoutProvider` in production and picks the rail by the payee's payout method. Rails never answer "settled" on send; only a poll or an admin confirmation settles, so the ledger never shows money that did not move. Payee accounts and onboarding status live in `payout_accounts` (payee kind reviewer now, vendor later); Payoneer payees are blocked until onboarding is active. Effective threshold = max(profile threshold, method minimum). The platform fee is a percent per org (default 5, range 0 to 8) of the human work: shown as an estimate on quotes for `hybrid` and `full`, and charged when the work is credited (`billing.fees.charge_fee`: ledger `platform:revenue:platform_fee` against the org receivable, usage unit `platform_fee`).

**Rejected.**
- *Wise payouts API as the first rail.* Business account onboarding for API payouts is slower; Wise stays a CSV fallback.
- *Fee on the whole quote price.* Machine-only tiers would carry a marketplace fee for no human work.
- *Fee hidden in the per-word rate.* Not transparent; the owner wants it shown.

**Consequences.** The fee basis on quotes is an estimate (review words times the reviewer edit rate); the charged fee follows actual pay. Vendor payouts reuse the same tables once Agency OS vendors exist. Live credentials and a small test payout are P03.

---

## D-074 Invoices: records of the provider's documents, our own only for manual billing; credits and overage
Date: 2026-10-13. Status: accepted.

**Context.** With a merchant of record, the provider sells to the customer and issues the tax invoice. Issuing our own invoice for the same sale would double-document it.

**Decision.** For Paddle (and later Stripe) payments the `invoices` table keeps a record: `kind`, `provider`, `provider_ref`, `provider_invoice_number`, totals as reported, and the document link is fetched fresh from the provider. Only the manual provider issues our numbered invoice (ARB sequence, D-029 tax rule, PDF, due date from the org's payment terms, PO number). Prepaid credit is a wallet of lots in `credit_ledger`, mirrored by double-entry txns on `org:<id>:credits`; spending order is earliest expiry first, expiry becomes breakage revenue, a provider refund refunds only unused credit. At period close, usage beyond the plan's included volume is priced at the plan's overage rate, credit is spent first and the rest is charged through the subscription's provider (Paddle one-time charge with our invoice id in custom data, so the payment webhook settles our record; manual: our invoice). One overage record per org and period makes the close idempotent.

**Rejected.**
- *Our own invoice for every payment.* Duplicates the merchant of record's tax document.
- *Provider metering (Stripe meters, Paddle has none).* Would split usage truth between two systems; we report usage only where a provider bills meters.
- *Credits as a balance column.* No lots, so no expiry or refund per purchase.

**Consequences.** Invoice lists mix our invoices and provider records; the UI shows who issued each. Paddle has no idempotency header, so the period close relies on our record.

---

## D-075 Entitlements follow the subscription; legacy orgs keep every module
Date: 2026-10-13. Status: accepted.

**Context.** `platform/modules.py` reads `org.settings["modules"]` (default: every module). Billing must write it without breaking existing organizations.

**Decision.** `billing/entitlements.refresh` is the only writer. Current subscription (active, trialing, past_due) gives its plan's modules; an org whose subscription lapsed gets none; an org that never had a subscription is left untouched (all modules) unless the admin sets overrides. Admin overrides (`module_overrides.add/remove`) apply on top; dependencies are added, and a module whose dependency is explicitly removed is dropped. A new paid provider subscription cancels the org's manual or admin one.

**Rejected.**
- *Switch every existing org to a free tier at migration.* Would cut features from current users without a decision.
- *Compute entitlements on every request.* `modules.py` stays a cheap reader of org settings.

**Consequences.** past_due keeps access while the provider retries. Seat limits are reported (`seats_used`) but not yet enforced at user creation.

## D-076 Format handler options are stored on the file and used by every read of it
Date: 2026-10-13. Status: accepted.

**Context.** The fileproc handlers gained an options seam (XML rules and dialect, subtitle `max_chars_per_line`). Extraction happens several times for one file: at upload (validation and counts), in the quote, in the job's extract step, in the XLIFF export, in the preview and in the merge. If any of those reads the file without the options, segment counts and merge slots disagree and the output breaks.

**Decision.** `POST /v1/uploads` takes `options` (JSON object), `POST /v1/files` takes an `options` form field (JSON string). The handler validates them before any bytes move (422 `unsupported_file` when the format takes no options or a value is wrong). They are stored on `upload_sessions.options` and then on `files.options` (migration 0011), and every caller passes `fa.options` to `detect_and_extract` / `get_handler`: quote, orchestrator extract and merge, XLIFF export, workbench preview. The new-project wizard offers the subtitle line limit for `.srt`, `.vtt` and `.ass`.

**Rejected.**
- *Options per job or per project.* Two jobs of one file could then disagree on segmentation, and the quote (made before the project) would not know them.
- *Options inferred from the org's settings.* Hidden state that changes how an already uploaded file is read.

**Consequences.** Changing options means uploading the file again. XML rule editing has no UI yet; API clients send the rules.

## D-077 Add-ons per plan; billing is the only writer of modules and add-ons
Date: 2026-10-13. Status: accepted.

**Context.** The engine module defined paid add-ons (`eu_processing`, `byok`, `custom_models`) read from `org.settings["addons"]`, the billing module wrote `org.settings["modules"]` from the subscription (D-075), and the platform module had its own admin editor that wrote the module list directly. Two writers would overwrite each other on the next subscription change.

**Decision.** Plans carry `addons` (migration 0011; business includes `byok`, enterprise all three). `billing.entitlements.refresh` writes both `modules` and `addons`: plan values plus admin overrides (`module_overrides`, `addon_overrides`, set through `POST /v1/admin/orgs/{id}/subscription` with `modules_add/remove` and `addons_add/remove`); an org that never subscribed keeps everything and nothing is stored. The platform editor (`PUT /v1/admin/orgs/{id}/modules`) calls `entitlements.set_exact_modules`, which turns the requested list into overrides against the plan. The org and admin module pages show add-ons read-only (`GET /v1/org/modules` returns `addons`). An add-on works only while its module is enabled.

**Rejected.**
- *Keeping the direct write in the platform editor.* The next webhook or period close would silently undo the admin's choice.
- *Add-ons as modules.* They are options of the engine module, not separable products; a module key for each would break the module isolation rule and the dependency model.

**Consequences.** The migration 0010 starter-catalog seed moved to 0011, because the seed uses the ORM model, which now has `plans.addons`.

## D-078 One invite flow, one secrets helper, all outbound email through notify
Date: 2026-10-13. Status: accepted.

**Context.** Eight modules were built in parallel. The infra builder added account tokens with an invite purpose and a set-password page, the platform builder added `user_invites` with `/v1/auth/invite/accept`; the engine builder added its own Fernet helper next to `platform/secrets.py`; the vendor module logged offer emails because no mailer existed yet.

**Decision.** Team invites use the platform flow (`POST /v1/users/invite`, `user_invites`, `/accept-invite`, `/v1/auth/invite/accept`); the email is queued through `notify.send_invite` with that link. `account_tokens` are only for password reset, and the reset endpoint accepts only reset tokens. Engine credentials are encrypted with `arbiter/platform/secrets.py` under the one `ARBITER_SECRETS_KEY` (`arbiter/crypto.py` removed). Vendor offers and assignment messages are queued through `notify.vendor_message` (template `vendor_message`); the assignment still keeps a record of each message. Templates may declare `optional` placeholders (a message without a link has no button).

**Rejected.**
- *Keeping both invite mechanisms.* Two links with different lifetimes and pages for the same action, and two places to revoke.
- *A second encryption key for engine keys.* Two keys to rotate and back up for the same class of secret.

**Consequences.** Vendor invoices marked paid do not trigger the platform payout rails: an agency pays its own vendors, while the rails pay marketplace reviewers from platform funds. Connecting the two needs a decision about who holds the money.

---

Entries D-079 to D-090 record the infrastructure, money, compliance and plan decisions the owner approved on 2026-10-13. Facts marked "research" come from the infrastructure research report of October 2026 (kept outside the repo); each fact names its original source so it can be re-checked. Prices are dated facts from that report or are labelled estimates that the phase confirms through the provider's API or console before anything is created. `docs/infrastructure.md` is the long form.

## D-079 Global market; GDPR without EU hosting; Claude through Anthropic's API by default, EU processing as a paid add-on
Date: 2026-10-13. Status: accepted (owner approved).

**Context.** Arbiter is sold globally, English-first. Earlier documents (D-013, PRODUCT.md, SECURITY.md, DESIGN.md section 7) treated EU hosting as a product constraint. GDPR does not require EU hosting: a transfer outside the EU is lawful under a DPA with the EU-US Data Privacy Framework or Standard Contractual Clauses. Research: as of October 2026 Anthropic's first-party API offers only "global" or "us" inference geography and a US-only workspace geography, so it cannot process in the EU ([Claude docs, data residency](https://platform.claude.com/docs/en/manage-claude/data-residency)). EU-processed Claude means AWS Bedrock with the EU geographic inference profile (routing inside EU regions such as eu-central-1, eu-west-1, eu-west-3) or Google Vertex AI's "eu" multi-region, which carries a 10 % premium ([Claude on Vertex](https://platform.claude.com/docs/en/api/claude-on-vertex-ai)); single-region Vertex endpoints serve only Sonnet 4.6 and older, so the honest promise is "processed within the EU", not "in Germany". The API reports the actual region per call in `usage.inference_geo`.

**Decision.** Default processing for every org: Claude through Anthropic's own API (global geography), other engines as configured. EU-only processing is the paid per-org add-on `eu_processing` (`org.settings["processing_region"] = "eu"`), routed only to engines that declare `region = eu`: Bedrock EU inference profiles, Vertex `eu`, DeepL. Never a silent fallback: a job of an EU org without an EU engine fails visibly with `no EU engine configured` (already built, D-056 to D-058). The processing region, engine and model of every call are written to provenance and the evidence pack, so residency is a replayable record, not a sales claim. Transfers are covered by the DPA plus the Data Privacy Framework or SCCs; legal review before public launch.

**Rejected.**
- *EU hosting and EU processing for everyone.* Costs every customer the EU premium and limits engine choice for buyers who do not need it; GDPR does not require it.
- *Global routing for EU orgs with a contractual promise only.* Not verifiable; the evidence pack would contradict the promise.
- *Promising single-country processing.* Not available for current Claude models on Vertex single regions (research, see above).

**Consequences.** Residency-pinned LLM spend costs more (research: budget about 10 % more on Vertex `eu`); the add-on price covers it. Bedrock profile ids and the Vertex `eu` host are confirmed against the provider consoles in P01 (INT-03) or before the first EU customer. Hosting location no longer decides residency for AI processing; D-080 picks hosting on cost and operations. Supersedes the "EU hosting" constraint wording in PRODUCT.md and SECURITY.md.

---

## D-080 Hosting: Hetzner Cloud VMs behind a load balancer, Kamal 2 deploys, Cloudflare in front, Tailscale for SSH
Date: 2026-10-13. Status: accepted (owner approved). Supersedes D-013 for staging and production.

**Context.** D-013 chose one Hetzner host running Compose with Postgres on a local volume: no redundancy and the operator owns database operations. The research report recommended an AWS eu-central-1 cell, mainly so Claude could run through Bedrock EU in the same region and because Hetzner has no managed Postgres. Research facts on Hetzner: ISO 27001:2022 for its German datacenter parks ([Hetzner](https://www.hetzner.com/de/unternehmen/rechenzentrum?country=us)), used as a production subprocessor by security-sensitive B2B products ([heylogin](https://www.heylogin.com/en/subprocessors)); the certificate page names only the German parks. The report also says the absolute saving of self-hosting at Arbiter's size is hundreds of dollars a month and that Kamal 2 works in production but needs health endpoints and a remote builder early ([Planet Argon](https://blog.planetargon.com/blog/entries/deploying-laravel-with-kamal-2-lessons-from-a-real-production-setup)). With D-079 the EU route is an add-on reached over the network, so co-locating compute with Bedrock is no longer required, and D-081 removes the "no managed Postgres" objection.

**Decision.** Hetzner Cloud (EU and US locations available) with at least two VMs per production environment behind a Hetzner Load Balancer. App containers are deployed by Kamal 2 as two services: `arbiter` (image `arbiter-api`, roles `api` and `worker`) and `arbiter-web` (image `arbiter-web`, role `web`); images live in GHCR, built and attested in CI (`.github/workflows/release.yml`), never on the hosts. Cloudflare in front for DNS, WAF and rate limiting, SSL mode Full (strict). TLS terminates at the load balancer; kamal-proxy on each VM listens on port 80 on the private network. Tailscale carries SSH for operators and CI; the VMs have no public SSH. Staging is one VM, production two or more. Configs exist in `deploy/kamal/` (D-051).

**Rejected.**
- *Single-box Compose + Caddy (D-013).* No redundancy and we own database operations. It stays only as local development and emergency fallback (`deploy/docker-compose.yml`).
- *Coolify.* Operational trouble on another of the owner's projects.
- *Kubernetes.* Too many moving parts before scale (the research report agrees: concepts without matching benefit at this size).
- *AWS full stack as the default.* Estimated 3 to 5 times the monthly cost now (owner's estimate, not measured); kept as an enterprise-region profile triggered by a contract (P09).
- *Scaleway.* pgvector support and PITR on its managed Postgres were not confirmed.
- *Vercel + Neon or Supabase + Render.* Many US subprocessors, and long-running queue workers polling `work_items` fit badly on serverless platforms.

**Consequences.** Questionnaires will ask about the US cell: Hetzner's named ISO scope covers the German parks only, so a US cell on Hetzner needs that caveat, or P09's AWS profile. Hetzner managed certificates on the load balancer need the zone in Hetzner DNS (to verify in P02); with Cloudflare DNS the expected path is an uploaded Cloudflare Origin CA certificate. GitHub plan limits for environments, required reviewers and artifact attestations on a private repository are checked in P02 before relying on them. Prices are read from the Hetzner API (`hcloud`) and written to `hyperpower.json` before creation.

---

## D-081 Database: Ubicloud managed PostgreSQL on Hetzner, after pgvector is verified
Date: 2026-10-13. Status: accepted (owner approved), conditional on the pgvector check in P02.

**Context.** Postgres holds everything: relational data, the `work_items` queue, TM vectors (pgvector, D-003), fuzzy search (pg_trgm), append-only provenance. Research: Ubicloud offers managed Postgres on Hetzner-class hardware in Germany and the US, from 19.54 USD per month, with 7-day per-minute restore ([Ubicloud pricing](https://www.ubicloud.com/docs/about/pricing)); the report flags that a young provider raises its own questionnaire questions, and that pgvector support per provider was not verified. The owner also lists high availability and a SOC 2 Type 2 report for Ubicloud; both are confirmed from Ubicloud's own documentation in P02 before they appear in any customer-facing text. The report argues for an always-on managed Postgres over serverless because long-lived worker connections keep compute awake anyway (reasoning, not a benchmark).

**Decision.** Ubicloud managed PostgreSQL 16, in the same region as the Hetzner VMs, TLS required, access limited to the VMs' egress addresses. Before creating anything billable, P02 verifies that `CREATE EXTENSION vector` and `CREATE EXTENSION pg_trgm` work on Ubicloud (docs first; if unclear, the smallest instance under the declared ceiling, deleted if the check fails). Evidence: INT-04. Fallback chosen by evidence, in order: Scaleway managed Postgres (only once its pgvector and PITR are confirmed), or self-managed Postgres 16 with a streaming replica on Hetzner VMs plus WAL archiving.

**Rejected.**
- *Postgres on the app VM (D-013).* Single point of failure, operator-owned backups and failover.
- *Serverless Postgres (Neon).* Worker polling keeps it awake; no saving, more moving parts.
- *Supabase.* Research: the PITR add-on is 100 USD per month ([Neon comparison](https://neon.com/guides/neon-launch-plan-vs-supabase-pro-plan)), and the bundled auth and storage are not used.
- *AWS RDS now.* Tied to the AWS default rejected in D-080.

**Consequences.** If the pgvector check fails, P02 records a superseding decision before creating the fallback. Database host metrics come from the managed provider (D-083). The migrations must run as a role that can create extensions, or the extensions are created once by the provider's admin role; P02 records which.

---

## D-082 Storage: Hetzner Object Storage for customer files, Backblaze B2 EU for backups at a different provider
Date: 2026-10-13. Status: accepted (owner approved). Supersedes the backup half of D-013.

**Context.** Uploads up to 1 GB go straight from the browser to object storage through presigned URLs (built, D-051), because Cloudflare caps proxied request bodies by plan and the app should never carry file bytes. Backups must survive the loss of the primary provider. Research: managed PITR is what security questionnaires ask about; a logical dump at a second provider covers provider loss and operator error past the PITR window.

**Decision.** Customer files: Hetzner Object Storage, one private bucket per environment, CORS limited to the app origin, lifecycle rule aborting incomplete multipart uploads after one day. Backups: three layers. (1) Ubicloud PITR (D-081). (2) Nightly `pg_dump -Fc`, encrypted with a symmetric passphrase, uploaded with a manifest of row counts to Backblaze B2 in its EU region (built: `.github/workflows/backup.yml`, 02:17 UTC). (3) A monthly restore drill in CI that restores the newest dump into a scratch pgvector Postgres, checks the checksum, the alembic version and that no populated table came back empty, and keeps `restore-drill.json` as an artifact for 400 days (built, same workflow). Retention lives in B2 lifecycle rules (35 daily copies). Customer file buckets get their own copy policy in P02 (object versioning or a nightly sync to B2; decision recorded there).

**Rejected.**
- *Backups in the same provider as production (Hetzner Object Storage only).* One account problem loses both.
- *Hetzner Storage Box with rclone (D-013 path).* Needs a host cron and an operator-run drill; CI keeps the drill replayable.
- *PITR only.* No copy outside the database provider, and the window is short (research: 7 days on Ubicloud).

**Consequences.** The B2 account region is chosen at sign-up and cannot be changed later, so the P02 click path selects the EU region first. The backup passphrase is a secret with its own rotation (SECURITY.md). INT-07 is the drill record.

---

## D-083 Observability: PostHog EU plus Better Stack, instrumented through OpenTelemetry
Date: 2026-10-13. Status: accepted (owner approved).

**Context.** Research, from PostHog's own handbook (October 2026): error tracking, logs and web vitals are production-ready; distributed tracing and metrics are alpha; there is no infrastructure or synthetic monitoring and "no built-in on-call/incident management" ([PostHog handbook](https://posthog.com/handbook/growth/use-case-selling/observability)). PostHog error tracking has Python and Next.js SDKs with 100K exceptions a month free ([pricing](https://posthog.com/docs/error-tracking/pricing)); logs are OpenTelemetry-native, 10 GB a month free then 0.25 USD per GB ([logs pricing](https://posthog.com/docs/logs/pricing)); AI observability has a privacy mode that drops prompt and completion text ([privacy mode](https://posthog.com/docs/ai-observability/privacy-mode)); PostHog Cloud EU sits in Frankfurt ([GDPR](https://posthog.com/docs/privacy/gdpr-compliance)). Better Stack's free tier has 10 monitors and heartbeats and one status page; a responder seat is 34 USD a month (29 yearly) for on-call; EU log ingestion is 0.10 USD per GB ([Better Stack pricing](https://betterstack.com/pricing.md)). The queue is a custom Postgres table, so a heartbeat plus queue depth is the portable signal.

**Decision.** PostHog Cloud EU for errors, logs, product analytics and LLM analytics, with privacy mode always on: segment text, prompts and completions never leave Arbiter (built in `observability.py`, D-051). Better Stack for uptime checks on `/healthz` and the web app, the worker heartbeat (`ARBITER_HEARTBEAT_URL`), a public status page and phone alerts. OpenTelemetry in code (`ARBITER_OTEL_*`) so either vendor can be swapped by configuration. Database metrics come from Ubicloud's own console.

**Rejected.**
- *PostHog alone.* No uptime checks, status page or on-call, by PostHog's own description; tracing and metrics are alpha.
- *Sentry + Grafana as the default.* More vendors; PostHog already covers errors and logs at our volume. Sentry stays the upgrade if debugging depth is needed; Langfuse (research: EU cloud, open source) is the upgrade when prompt management and eval datasets for the judge need a dedicated tool.
- *Self-hosted Prometheus and Grafana.* One more system for one operator to run.

**Consequences.** Both vendors appear in the subprocessor list (D-086) with "no segment text" stated. The free tiers cover staging; a responder seat for phone alerts is the first paid item at launch (P04).

---

## D-084 Payments: Paddle as merchant of record now; our database is the source of truth; Stripe only with a company in a supported country
Date: 2026-10-13. Status: accepted (owner approved). Confirms D-072 with the research facts.

**Context.** Research: Stripe supports 51 countries and regions as of August 2026 and "everywhere else is unsupported" ([StartupOwl](https://startupowl.com/setup/stripe-unsupported-countries)); Serbia is not among them, and Stripe's own merchant-of-record product still needs a Stripe account ([Stripe Managed Payments](https://stripe.com/en-dk/managed-payments)). Paddle accepts software sellers from any country outside a short sanctions list, Serbia included ([Paddle](https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle)), and costs 5 % + 50 cents per transaction with tax calculation, filing, remittance, chargebacks and fraud included and no monthly fee ([Paddle pricing](https://www.paddle.com/pricing)). Paddle supports invoices with payment terms, PO numbers, bank transfer and tax-exempt billing for valid VAT or GST IDs; its native usage billing is in early-access beta and it recommends tracking usage in your own app ([Paddle for AI companies](https://developer.paddle.com/get-started/how-paddle-works/ai-companies.md)). Known downsides (research): domain review estimated at 5 to 7 business days, payouts only in USD, EUR, GBP, AUD and CAD. Entity options for a later Stripe rail: Stripe Atlas (500 USD once, 100 USD a year; a foreign-owned single-member US LLC must file Form 5472 yearly or face a 25,000 USD penalty per form) or an Estonian company via e-Residency (about 415 EUR in state fees, 700 to 2,000 EUR a year to run); e-Residency is not tax residency, and a company managed from Serbia may be treated as Serbian-resident ([Stripe Atlas](https://stripe.com/atlas), [TaxesForExpats](https://www.taxesforexpats.com/articles/foreign-business/foreign-owned-single-member-llc.html), [Enty](https://enty.io/blog/real-cost-running-estonian-e-resident-company-2026)).

**Decision.** Paddle is the merchant of record and the only live card rail now. Usage, credits, entitlements, plans and invoice records stay in our database (built, D-072 to D-075); providers are thin adapters. The Stripe adapter exists and stays off until a company in a Stripe-supported country exists; which entity (US LLC through Atlas or an Estonian company) is an open owner decision that needs a tax adviser's check first (P03). Enterprise customers can be billed through the manual bank-invoice provider (our own PDF invoice, admin marks it paid).

**Rejected.**
- *Stripe first.* Not available without a foreign entity, and tax filing would be ours.
- *Forming the foreign entity now.* Tax residency risk unreviewed.
- *Dedicated usage engines (Metronome, Orb).* Research: both now belong to payment companies and are enterprise-priced; Lago is the one to revisit if the in-house ledger becomes a burden.
- *Polar, Creem, Dodo and similar.* Smaller, with weaker or unclear usage and enterprise invoicing support (research).

**Consequences.** The Paddle application goes in early (P03) with the website, terms and pricing page live, because review takes days. For EU B2B buyers with VAT IDs much VAT is reverse-charged, so the 5 % is a launch cost, revisited when enterprise volume grows (research).

---

## D-085 Payouts: Payoneer and PayPal first, bank files as fallback; platform fee on human work; agencies pay their own vendors
Date: 2026-10-13. Status: accepted (owner approved). Confirms D-073 and D-078.

**Context.** Research: translation marketplaces converge on Payoneer for the long tail, with PayPal and bank transfer beside it. Gengo added Payoneer in 2017 and pays translators monthly in over 200 countries and territories ([Gengo](https://gengo.com/translator-product-updates/gengo-payoneer-a-new-translator-payment-option/)); Smartcat processes payouts within 3 business days with a 7 USD or EUR minimum, Payoneer wallets with roughly 3 USD deducted by Payoneer, bank transfer and PayPal as alternatives ([Smartcat Payoneer](https://smartcat-company.helpjuice.com/1674961-payoneer)), and charges the paying company 2 % to 8 % per transaction ([Smartcat](https://smartcat-company.helpjuice.com/payment-automation/1539596-how-to-pay-freelancers-in-smartcat)). Paddle pays the seller, not third parties, so payouts need their own provider. Stripe Connect is unavailable without a Stripe account.

**Decision.** Payoneer and PayPal are the first live rails; bank files (SEPA pain.001, plain CSV, Wise batch CSV) are the fallback (built, D-073). Arbiter is the paying counterparty for marketplace reviewers, from its own funds. Platform fee: 0 to 8 % of human work, default 5 %, charged to the customer and shown on quotes for `hybrid` and `full` (built). Vendor invoices of an agency's own vendors are paid by the agency outside the platform rails (D-078).

**Rejected.**
- *Stripe Connect.* Needs a Stripe account (D-084).
- *Wise API as the first rail.* Slower business onboarding for API payouts (D-073).
- *Outsourcing the reviewer pool to a vendor.* The senate-plus-reviewer design makes the pool core to the product (research notes this is how some competitors do it).
- *Paying agency vendors through the platform.* Arbiter would hold agency money and take on that liability.

**Consequences.** Arbiter takes on payee identity checks, sanctions screening and tax documentation. Two obligations are unverified and need specialist review before the marketplace pays real reviewers (P03): US tax forms (W-8BEN or W-9) for US-linked payees, and EU DAC7 reporting for platforms with EU sellers of personal services (research could not confirm whether review work falls under it).

---

## D-086 Compliance path: trust page, DPA and subprocessor list now; ISO 27001 or SOC 2 Type I on the first enterprise deal; Type II after
Date: 2026-10-13. Status: accepted (owner approved).

**Context.** Research: comparable products lead with ISO 27001 or SOC 2. Crowdin wins enterprise accounts on ISO 27001 plus a HIPAA BAA without SOC 2 on its security page ([Crowdin](https://crowdin.com/page/security)); Smartling held SOC 2 since 2013 and announced ISO 27001 on 2025-12-04 ([Smartling](https://www.smartling.com/security)). ISO 27001 lands better with EU buyers, SOC 2 with US buyers. Cost estimates (research, from compliance vendors whose numbers do not cleanly sum): first-year SOC 2 compliance platform 7,500 to 25,000 USD a year, Type II audit 12,000 to 50,000 USD, pen test 4,000 to 15,000 USD, observation window 3 to 12 months, headline total 25,000 to 100,000+ USD ([Strac](https://www.strac.io/blog/soc-2-cost)); specialist auditors cost a third to a fifth of the Big 4, Type I takes about three months, renewals run 20 to 40 % cheaper ([Agency](https://blog.getagency.com/articles/soc-2-audit-cost-for-startups)). ISO 27001 cost at one-to-five person scale was not sourced. Lokalise publishes a full subprocessor list naming every LLM and MT provider with location ([Lokalise](https://lokalise.com/sub-processors)).

**Decision.** Now (P03): a public trust page, a GDPR DPA and a public subprocessor list (draft in `docs/subprocessors.md`: vendor, purpose, data, location), all pending legal review before public launch. On the first enterprise deal that asks: ISO 27001 or SOC 2 Type I, chosen by the buyer's region (P07). Then SOC 2 Type II after a 3 to 6 month window. ISO/IEC 42001 (AI management) is noted as a later differentiator, not planned.

**Rejected.**
- *Starting SOC 2 Type II before any enterprise demand.* Tens of thousands of dollars and months of evidence collection with no buyer asking.
- *No public subprocessor list until a customer asks.* Every serious buyer asks; publishing it early is cheap.

**Consequences.** The controls already in the repo (append-only provenance, evidence ledger, org scoping, regulated-vertical blocks, audit log) are the base of the later audit. The audit choice and its fees are declared in P07, not before.

---

## D-087 Modular product: seven modules and three add-ons sold through plans, one entitlement writer
Date: 2026-10-13. Status: accepted (owner approved). Records the product shape built in D-052 to D-055 and D-077.

**Context.** Buyers differ: a software team wants strings and an engine API, an agency wants PM and a workbench, a quality team wants only the auditor. Selling one bundle prices out the small buyer and under-prices the large one.

**Decision.** Seven modules: `tms` (web translation and workbench), `engine` (translation engine API, keys, routing, own models), `ai` (QE judge, senate, AI editor), `pm` (Agency OS, vendors, POs, capacity), `auditor` (standalone QA and LQA), `strings` (software strings, OTA; needs `tms`), `community` (reviewer marketplace; needs `tms`). Add-ons on the engine module: `eu_processing`, `byok`, `custom_models`. Plans (data, admin-edited) grant modules and add-ons; billing is the only writer of `org.settings["modules"]` and `["addons"]`; admin overrides are stored as overrides against the plan. A disabled module answers 404 `module_disabled`. Modules talk only through `contracts.py`.

**Rejected.**
- *One bundle with seats.* Does not fit the buyers above.
- *Usage-only pricing with every module on.* Hides the product structure and makes the entry price unpredictable.

**Consequences.** Known debt: `strings` and `auditor` import engines, quality and community internals (`tests/platform/test_module_isolation.py`). Seat limits are reported, not enforced.

---

## D-088 Own models activate after measurement and first customers
Date: 2026-10-13. Status: accepted (owner approved). Builds on D-059.

**Context.** Per-client LoRA fine-tunes on consented, human-approved segments are built (D-059) and compete on the scoreboard. Training needs real approved segments from one client and pair; none exist before customers, and the scoreboard needs the judge calibrated (P01) before its numbers mean anything.

**Decision.** Own models stay switched off for customers until P01 has a calibrated judge and real customers have produced consented approved segments. P06 runs the first real training, evaluation on the held-out set and scoreboard comparison. EU orgs train only with the manual provider and evaluate only EU-declared models (D-059).

**Rejected.**
- *Training on synthetic or public data now to have a model at launch.* It would not be the client's model, which is the point.
- *Shared model across clients.* No consent model allows it (D-059).

**Consequences.** The `custom_models` add-on can be sold from P04, but delivery starts when a client has enough approved segments (`ARBITER_TRAINING_MIN_EXAMPLES`).

---

## D-089 Owner override of phase discipline on 2026-10-13
Date: 2026-10-13. Status: accepted (owner instruction).

**Context.** CLAUDE.md law 4 says work only on the current phase. On 2026-10-13 P00 was the current phase, and the owner asked for every product module (platform, engines, strings, file formats, workbench, vendors, billing, infra configs) to be built ahead of the plan, in parallel builds that were then merged (activeContext 2026-10-13).

**Decision.** That work is an owner-directed exception, not a violation. No phase item was ticked for it; the rewritten plan (D-090) lists it under "Already built", and every phase still proves it through its own gate.

**Rejected.**
- *Treating the merged work as unplanned and reverting it.* The owner asked for it.
- *Ticking phase items because the code exists.* Code existing is not proof (ACCEPTANCE.md).

**Consequences.** Later agents read this entry instead of raising law 4. Law 4 applies again from now on: work follows `phases/` in order unless the owner says otherwise.

---

## D-090 Phase plan rewritten as P00 to P09 around what is built
Date: 2026-10-13. Status: accepted. Supersedes D-048.

**Context.** The P00 to P08 plan (D-048) assumed single-box Compose on Hetzner, an undecided payment provider, an Okapi phase and no own-models or region phase. After D-079 to D-089 most product scope is built; what remains is proof on the owner's machine, measurement, accounts, deploys, legal work and launch.

**Decision.** New order: P00 install and verify on Windows; P01 measurement harness (plus the EU route when keys exist); P02 production-grade staging on the chosen stack; P03 money and legal; P04 self-serve launch; P05 integrations and connectors; P06 own models in production; P07 enterprise; P08 white-label for agencies; P09 enterprise region (AWS profile on contract) and US cell on demand. Journeys J-10 to J-18 cover the merged modules; integration checkpoints are renumbered INT-01 to INT-11 (none had evidence, so no record changes). The Okapi sidecar phase is dropped from the numbered plan: the Python handlers now cover IDML, DITA, XML with ITS, subtitles and resource formats; Okapi moves to the ROADMAP backlog, triggered by a format request the handlers cannot serve.

**Rejected.**
- *Keeping P00 to P08 and patching each file.* P02 and P03 described a stack and choices that no longer apply.
- *Merging P02 and P04 (deploy production straight away).* Staging must prove the stack, backups, restore drill and attested deploys before customer data arrives.

**Consequences.** `hyperpower.json` phases map, `phases/README.md`, `ROADMAP.md` and `ACCEPTANCE.md` follow the new numbers. P00 creates ten beads, not nine.
