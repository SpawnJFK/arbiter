"""Module tms: the translator/PM workbench (segment editor operations, comments and client
queries, live preview) and the TM tools (TM editor, concordance, alignment, term
extraction, TM QA). Routes: api/routes/workbench.py and api/routes/tmtools.py.

Talks to the pipeline only through its public helpers (events.record, orchestrator's
target/learn helpers used by the jobs routes too) and to linguistic assets through
arbiter.linguistic. State changes go through domain/states.py; every segment change
writes provenance.
"""
