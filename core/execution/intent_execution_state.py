"""
core/execution/intent_execution_state.py
L2.5-A: Authoritative execution state machine for every ExecutionIntent.

WAL events are derived from transitions here.
Recovery, compensation, and supervision all key off this state.

Legal transitions are defined in LEGAL_TRANSITIONS.
Any transition not listed is a KERNEL PANIC — it means the system
has reached a state that cannot be reasoned about for replay.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import FrozenSet, Dict

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  States
# ─────────────────────────────────────────────────────────────────────────────

class IntentExecutionState(str, Enum):
    CREATED      = "CREATED"       # Intent object built but not submitted
    QUEUED       = "QUEUED"        # Submitted to the kernel queue
    DISPATCHED   = "DISPATCHED"    # Routed to the correct adapter/legacy
    RUNNING      = "RUNNING"       # Adapter actively executing
    VERIFYING    = "VERIFYING"     # Post-execution verification in progress
    COMPLETED    = "COMPLETED"     # Verification passed; side effect committed
    FAILED       = "FAILED"        # Execution or verification failed
    COMPENSATING = "COMPENSATING"  # Rollback / compensation action executing
    COMPENSATED  = "COMPENSATED"   # Compensation finished successfully
    ABORTED      = "ABORTED"       # Cancelled before execution started
    REJECTED     = "REJECTED"      # Capability not allowed; never executed


# ─────────────────────────────────────────────────────────────────────────────
#  Legal transition table — THE AUTHORITATIVE TRUTH
#
#  Any (from_state, to_state) pair not in this map is ILLEGAL.
#  Attempting an illegal transition raises IntentStateError.
#  This is NOT configurable at runtime.
# ─────────────────────────────────────────────────────────────────────────────

LEGAL_TRANSITIONS: Dict[IntentExecutionState, FrozenSet[IntentExecutionState]] = {
    IntentExecutionState.CREATED: frozenset({
        IntentExecutionState.QUEUED,
        IntentExecutionState.REJECTED,
        IntentExecutionState.ABORTED,
    }),
    IntentExecutionState.QUEUED: frozenset({
        IntentExecutionState.DISPATCHED,
        IntentExecutionState.ABORTED,
    }),
    IntentExecutionState.DISPATCHED: frozenset({
        IntentExecutionState.RUNNING,
        IntentExecutionState.FAILED,   # e.g. adapter not found
        IntentExecutionState.ABORTED,
    }),
    IntentExecutionState.RUNNING: frozenset({
        IntentExecutionState.VERIFYING,
        IntentExecutionState.FAILED,
    }),
    IntentExecutionState.VERIFYING: frozenset({
        IntentExecutionState.COMPLETED,
        IntentExecutionState.FAILED,   # verification failed
    }),
    IntentExecutionState.COMPLETED: frozenset(),     # Terminal — no forward transitions
    IntentExecutionState.FAILED: frozenset({
        IntentExecutionState.COMPENSATING,
        IntentExecutionState.ABORTED,   # abort without compensation
    }),
    IntentExecutionState.COMPENSATING: frozenset({
        IntentExecutionState.COMPENSATED,
        IntentExecutionState.FAILED,   # compensation itself failed
    }),
    IntentExecutionState.COMPENSATED: frozenset(),   # Terminal
    IntentExecutionState.ABORTED:     frozenset(),   # Terminal
    IntentExecutionState.REJECTED:    frozenset(),   # Terminal
}

# Terminal states — no further transitions permitted
TERMINAL_STATES: FrozenSet[IntentExecutionState] = frozenset({
    IntentExecutionState.COMPLETED,
    IntentExecutionState.COMPENSATED,
    IntentExecutionState.ABORTED,
    IntentExecutionState.REJECTED,
})


# ─────────────────────────────────────────────────────────────────────────────
#  Error
# ─────────────────────────────────────────────────────────────────────────────

class IntentStateError(RuntimeError):
    """
    Raised when an illegal state transition is attempted.
    This is a kernel-level invariant violation, NOT a user error.
    """


# ─────────────────────────────────────────────────────────────────────────────
#  State machine tracker (per-intent)
# ─────────────────────────────────────────────────────────────────────────────

class IntentStateMachine:
    """
    Tracks and enforces state transitions for a single ExecutionIntent.

    Usage:
        sm = IntentStateMachine(intent_id="abc-123")
        sm.transition(IntentExecutionState.QUEUED)
        sm.transition(IntentExecutionState.DISPATCHED)
        ...
    """

    def __init__(self, intent_id: str):
        self.intent_id = intent_id
        self.state = IntentExecutionState.CREATED
        self.history: list[IntentExecutionState] = [IntentExecutionState.CREATED]

    def transition(self, new_state: IntentExecutionState) -> None:
        """
        Attempt a state transition. Raises IntentStateError on illegal transition.
        """
        allowed = LEGAL_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise IntentStateError(
                f"Intent {self.intent_id[:8]}: Illegal transition "
                f"{self.state.value} -> {new_state.value}. "
                f"Allowed from {self.state.value}: "
                f"{[s.value for s in allowed] or 'none (terminal state)'}."
            )
        logger.debug(
            f"[IntentSM] {self.intent_id[:8]}: {self.state.value} -> {new_state.value}"
        )
        self.state = new_state
        self.history.append(new_state)

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def current(self) -> IntentExecutionState:
        return self.state
