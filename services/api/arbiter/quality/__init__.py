"""Quality brain: deterministic hard checks, MQM scoring, the LLM judge, the routing
decision, the senate (multi-role review and best-of-N translation), the AI editor and
threshold calibration.

Design rule that runs through every module: a model can add doubt, never remove a
deterministic failure. Blocking hard checks always win over any model output.
"""
