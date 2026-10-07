"""Reviewer marketplace: profiles, qualification tests, task queue, review, score, disputes, payouts.

Every function here flushes and never commits; the API layer owns the transaction.
Return values meant for the API are plain dicts shaped like docs/api-contract.md.
"""
