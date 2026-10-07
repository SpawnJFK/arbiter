"""Machine translation engines and LLM clients.

Everything here implements the protocols in ``arbiter.contracts`` (MtEngine, LlmClient).
Real providers are only reachable when their ARBITER_* key is set by the owner; in the
"test" environment the registry hands out mocks only, so no test can ever spend money.
"""
