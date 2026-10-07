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
