"""The one place community and billing code writes a `state` column.

Every write goes through arbiter.domain.states.assert_transition first, so a transition
that is not in the state machine raises IllegalTransition instead of happening.
"""

from __future__ import annotations

from typing import Any

from arbiter.domain.states import assert_transition


def move(obj: Any, machine: str, dst: str) -> None:
    assert_transition(machine, str(obj.state), str(dst))
    obj.state = str(dst)
