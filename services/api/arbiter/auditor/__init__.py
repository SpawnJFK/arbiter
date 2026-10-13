"""Module auditor: standalone QA/LQA of bilingual files produced by any tool.

bilingual.py  readers (XLIFF 1.2/2.x, TMX, bilingual CSV/XLSX, aligned document pairs)
service.py    the audit steps on the work queue (parse, check in batches, finish)
report.py     PDF/XLSX scorecards and the annotated XLIFF

Uses only shared core packages (fileproc, linguistic, quality, pipeline.queue, billing
usage); no other product module. Routes: api/routes/audits.py, gated by require_module.
"""
