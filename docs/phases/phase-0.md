# P0 Measurement harness (current phase)

Status 2026-10-07: foundation done (10/10); measurement 0/5; ops 0/2.

Goal: measure whether the QE judge + senate can decide which segments ship without a human, on one real pair. English to Serbian is the first measurement pair (test instrument, not the market).

## Foundation
- [x] Monorepo layout, pyproject, config (`ARBITER_*`), contracts.py, state machines
- [x] SQLAlchemy models, initial Alembic migration, append-only provenance trigger
- [x] FormatHandler + handlers: docx, xlsx, pptx, html, md, json, po, txt/csv, xliff (round-trip tests)
- [x] Infra: Dockerfiles, compose, Caddy, backups, CI, env template, docs
- [x] Linguistic: segmentation rules (R-SEG), TM exact/fuzzy/semantic (R-TM), glossary with temporal versions + Snowball term checks (R-GL)
- [x] Engines: mock + Anthropic, OpenAI, DeepL, Google providers; tag protection; router with scoreboard (R-MT)
- [x] Quality: hard QA incl. tag policy D-009; QE judge (MQM-Core D-010); senate judges + overlap arbitration; decide step
- [x] Pipeline: work_items worker, step handlers, merge, deliver
- [x] API per docs/api-contract.md (enough for the harness: files, quotes, projects, jobs, segments, evidence)
- [x] Evidence pack JSON + PDF from provenance

## Measurement
- [ ] Reference set: real EN to SR documents across at least 3 content types, human-labelled MQM errors per segment
- [ ] Harness script: run pipeline on reference set, compare decisions to labels, output auto rate, escaped-error rate with confidence interval, senate agreement, cost per word
- [ ] Threshold sweep: escaped-error rate vs auto rate curve per content type
- [ ] Control-sample flow exercised (2% blind)
- [ ] Results written to docs (numbers only from real runs)
- [ ] Automated parity test: `alembic upgrade head` equals `create_all` (D-037)

## Ops
- [ ] Staging host on Hetzner deployed via deploy/README.md
- [ ] backup.sh in cron with off-site remote; one restore drill recorded

## Exit criteria
See ROADMAP.md P0.
