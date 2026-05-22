import logging
from typing import Dict, Set

from core.contracts.runtime_states import RuntimeState

logger = logging.getLogger(__name__)

class IllegalStateTransition(Exception):
    """Raised when an illegal runtime state transition is attempted."""
    pass

class RuntimeLifecycle:
    """
    Authoritative state machine for the NovaMind execution kernel.
    This is the ONLY entity allowed to transition runtime states.
    """

    # Strict transition table. ANY state can transition to PANIC.
    ALLOWED_TRANSITIONS: Dict[RuntimeState, Set[RuntimeState]] = {
        RuntimeState.BOOT: {RuntimeState.PRECHECK},
        RuntimeState.PRECHECK: {RuntimeState.RECOVER},
        RuntimeState.RECOVER: {RuntimeState.VERIFY_WAL},
        RuntimeState.VERIFY_WAL: {RuntimeState.VERIFY_WORKERS},
        RuntimeState.VERIFY_WORKERS: {RuntimeState.START_IPC},
        RuntimeState.START_IPC: {RuntimeState.START_SCHEDULER},
        RuntimeState.START_SCHEDULER: {RuntimeState.READY},
        RuntimeState.READY: {RuntimeState.DEGRADED, RuntimeState.QUIESCING},
        RuntimeState.DEGRADED: {RuntimeState.RECOVERY, RuntimeState.QUIESCING},
        RuntimeState.RECOVERY: {RuntimeState.READY, RuntimeState.QUIESCING},
        RuntimeState.QUIESCING: {RuntimeState.HALT},
        RuntimeState.PANIC: {RuntimeState.HALT},
        RuntimeState.HALT: set(),  # Terminal state
    }

    def __init__(self):
        self._current_state = RuntimeState.BOOT
        logger.info(f"[RuntimeLifecycle] Initialized. State: {self._current_state.value}")

    @property
    def current_state(self) -> RuntimeState:
        return self._current_state

    def transition(self, new_state: RuntimeState, reason: str = "") -> None:
        """
        Attempts to transition the runtime to a new state.
        Raises IllegalStateTransition if the transition violates the FSM.
        """
        if new_state == RuntimeState.PANIC:
            # Panic is allowed from ANY state
            pass
        elif new_state not in self.ALLOWED_TRANSITIONS.get(self._current_state, set()):
            raise IllegalStateTransition(
                f"Cannot transition from {self._current_state.value} to {new_state.value}. Reason: {reason}"
            )

        logger.info(f"[RuntimeLifecycle] Transition: {self._current_state.value} -> {new_state.value} ({reason})")
        self._current_state = new_state

    def assert_state(self, expected_state: RuntimeState):
        """Helper to ensure the runtime is in a specific state before allowing an action."""
        if self._current_state != expected_state:
            raise IllegalStateTransition(
                f"Expected state {expected_state.value}, but currently in {self._current_state.value}."
            )
