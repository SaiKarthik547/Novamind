"""core/contracts/runtime_states.py

Canonical runtime state contract.

This module owns the authoritative runtime lifecycle/state taxonomy used by the
converged runtime authority.

Important:
- RuntimeLifecycleState is the canonical runtime lifecycle authority enum.
  Canonical values: INITIALIZING, RECONCILING, READY, DEGRADED, HALTING, HALTED, PANIC.
- RuntimeState is a compatibility enum kept only because existing bootstrap/runtime
  modules still reference legacy lifecycle values. New code should use
  RuntimeLifecycleState.
- Execution lifecycles live in core/execution/intent_execution_state.py.
- Execution observation state lives in core/contracts/runtime_events.py (ExecutionState).
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Set

# ── Canonical runtime lifecycle state ─────────────────────────────────────────

class RuntimeLifecycleState(str, Enum):
    """Canonical runtime lifecycle states owned by LifecycleAuthority."""
    INITIALIZING = "INITIALIZING"
    RECONCILING = "RECONCILING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    HALTING = "HALTING"
    HALTED = "HALTED"
    PANIC = "PANIC"


# ── Compatibility lifecycle enum ───────────────────────────────────────────────

class RuntimeState(str, Enum):
    """
    Compatibility lifecycle enum.

    This exists ONLY to avoid a mass rewrite of legacy modules that import
    RuntimeState from core.contracts.runtime_states and use the old lifecycle
    vocabulary (BOOT, PRECHECK, RECOVER, VERIFY_WAL, ...).

    These values are NOT the canonical runtime lifecycle. They are transitional
    compatibility values and must eventually be migrated to RuntimeLifecycleState
    or to a more specific lifecycle domain enum.
    """

    # Legacy bootstrap/runtime lifecycle values
    BOOT = "BOOT"
    PRECHECK = "PRECHECK"
    RECOVER = "RECOVER"
    VERIFY_WAL = "VERIFY_WAL"
    VERIFY_WORKERS = "VERIFY_WORKERS"
    START_IPC = "START_IPC"
    START_SCHEDULER = "START_SCHEDULER"
    QUIESCING = "QUIESCING"
    RECOVERY = "RECOVERY"

    # Canonical values (forward compatibility)
    INITIALIZING = "INITIALIZING"
    RECONCILING = "RECONCILING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    HALTING = "HALTING"
    HALTED = "HALTED"
    HALT = "HALT"
    PANIC = "PANIC"


# ── Contract invariants ────────────────────────────────────────────────────────

CANONICAL_RUNTIME_STATES: Final[set[str]] = {
    state.value for state in RuntimeLifecycleState
}

LEGACY_RUNTIME_STATES: Final[set[str]] = {
    RuntimeState.BOOT.value,
    RuntimeState.PRECHECK.value,
    RuntimeState.RECOVER.value,
    RuntimeState.VERIFY_WAL.value,
    RuntimeState.VERIFY_WORKERS.value,
    RuntimeState.START_IPC.value,
    RuntimeState.START_SCHEDULER.value,
    RuntimeState.QUESCIING.value if hasattr(RuntimeState, "QUESCIING") else RuntimeState.QUIESCING.value,
    RuntimeState.RECOVERY.value,
}


def is_legacy_runtime_state(value: str) -> bool:
    """True if the value belongs to the legacy compatibility lifecycle only."""
    return value in LEGACY_RUNTIME_STATES and value not in CANONICAL_RUNTIME_STATES
