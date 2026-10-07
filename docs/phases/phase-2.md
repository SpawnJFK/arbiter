# P2 Reviewer community at scale

Status 2026-10-07: community mechanics built and tested locally; nothing at scale yet.

- [x] Reviewer application flow, pairs and domains
- [x] Qualification tests (MQM-annotated items), auto-grading, retake rules
- [x] Levels and quality score from reviewer_score_events
- [x] Task routing: pair, domain, level, load; holds and expiry
- [x] Per-decision pay estimate and accrual to ledger
- [x] Disputes with due dates and admin decisions
- [x] Payout runs, tax info completeness, payout failure handling (ledger side; mock provider)
- [ ] Real payout provider integration (prod payouts only accrue today)
- [ ] Ledger reconciliation report (to the cent)
- [x] Reviewer workspace UX: context, terms, flagged errors, keyboard-first
- [ ] Wait-time monitoring per pair vs hybrid target
- [ ] Reviewer contractor terms reviewed

Exit criteria: ROADMAP.md P2.
