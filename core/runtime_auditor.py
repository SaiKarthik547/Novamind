"""
core/runtime_auditor.py
Continuous semantic invariant auditor for NovaMind.

Design principle (from user directive):
  The auditor does NOT kill the runtime.
  It emits INVARIANT_VIOLATION events to a RuntimeSupervisor callback.
  The Supervisor decides policy (log, alert, quarantine, or shutdown).

Invariants enforced:
  1. Task State Machine — illegal transitions are rejected
       Valid:  CREATED → STARTED → COMPLETED | FAILED
       Invalid: COMPLETED → STARTED, FAILED → RUNNING, etc.
  2. Temporal Ordering — COMPLETED cannot precede STARTED (even if final state is correct)
  3. Msg ID Uniqueness — duplicate msg_ids emit a violation
  4. Lifecycle Continuity — agent DESTROYED must be preceded by CREATED
  5. Correlation Continuity — every causal_parent_id must reference a known msg_id
  6. Heartbeat Consistency — active_task_ids from heartbeat must match known created/not-destroyed tasks
"""

import logging
import time
from enum import Enum
from typing import Callable, Dict, Optional, Set

from shared.protocol.events import EventType

logger = logging.getLogger(__name__)


class TaskState(Enum):
    CREATED   = "CREATED"
    STARTED   = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"


# Legal task state transitions
_VALID_TRANSITIONS: Dict[Optional[TaskState], Set[TaskState]] = {
    None:                {TaskState.CREATED},
    TaskState.CREATED:   {TaskState.STARTED},
    TaskState.STARTED:   {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.COMPLETED: set(),   # Terminal state
    TaskState.FAILED:    set(),   # Terminal state
}

_EVENT_TO_TRANSITION = {
    EventType.AGENT_LIFECYCLE_CREATED:   TaskState.CREATED,
    EventType.AGENT_TASK_STARTED:        TaskState.STARTED,
    EventType.AGENT_TASK_COMPLETED:      TaskState.COMPLETED,
    EventType.AGENT_TASK_FAILED:         TaskState.FAILED,
    EventType.AGENT_LIFECYCLE_DESTROYED: None,   # Special — validates destruction
}


class RuntimeAuditor:
    """
    Continuously validates semantic correctness of the event stream.
    Thread-safe: all state mutations happen in the asyncio loop thread via
    direct event subscription (EventBus calls from the main loop).
    """

    def __init__(self, supervisor_callback: Callable[[dict], None] = None):
        """
        supervisor_callback: invoked with a violation dict whenever an invariant
        is breached. If None, violations are only logged at ERROR level.
        """
        self._supervisor = supervisor_callback or self._default_supervisor

        # task_id → TaskState
        self._task_states: Dict[str, Optional[TaskState]] = {}

        # agent_id → bool (True = alive)
        self._agent_alive: Dict[str, bool] = {}

        # All msg_ids ever seen (for global uniqueness)
        self._all_msg_ids: Set[str] = set()

        # All msg_ids as a mapping to event_type (for causal parent validation)
        self._msg_id_event_map: Dict[str, str] = {}

        # Counters
        self.violation_count = 0
        self.events_processed = 0

    # ── EventBus hook ─────────────────────────────────────────────────────────

    def on_event(self, event: dict):
        """
        Called for every EventBus event. Validates invariants synchronously.
        The event dict is the raw payload — not the IPC wire message.
        """
        self.events_processed += 1
        event_type = event.get("event_type") or event.get("type", "UNKNOWN")
        msg_id = event.get("msg_id")
        task_id = event.get("task_id")
        agent_id = event.get("agent_id")
        causal_parent_id = event.get("causal_parent_id")

        # ── Invariant 1: Msg ID Uniqueness ────────────────────────────────────
        if msg_id:
            if msg_id in self._all_msg_ids:
                self._violation("MSG_ID_DUPLICATE", event, f"Duplicate msg_id: {msg_id}")
            else:
                self._all_msg_ids.add(msg_id)
                self._msg_id_event_map[msg_id] = event_type

        # ── Invariant 5: Correlation Continuity ───────────────────────────────
        if causal_parent_id and causal_parent_id not in self._msg_id_event_map:
            self._violation(
                "UNKNOWN_CAUSAL_PARENT",
                event,
                f"causal_parent_id '{causal_parent_id}' references unknown msg_id"
            )

        # ── Invariant 4: Agent Lifecycle ──────────────────────────────────────
        if event_type == EventType.AGENT_LIFECYCLE_CREATED:
            if agent_id and self._agent_alive.get(agent_id) is True:
                self._violation("AGENT_DOUBLE_CREATE", event, f"Agent '{agent_id}' created twice without destruction")
            if agent_id:
                self._agent_alive[agent_id] = True

        elif event_type == EventType.AGENT_LIFECYCLE_DESTROYED:
            if agent_id and not self._agent_alive.get(agent_id):
                self._violation("AGENT_DESTROY_UNKNOWN", event, f"Agent '{agent_id}' destroyed without prior CREATED")
            if agent_id:
                self._agent_alive[agent_id] = False

        # ── Invariants 1 & 2: Task State Machine + Temporal Ordering ──────────
        target_state = _EVENT_TO_TRANSITION.get(event_type)
        if target_state is not None and task_id:
            current = self._task_states.get(task_id)
            allowed = _VALID_TRANSITIONS.get(current, set())
            if target_state not in allowed:
                self._violation(
                    "ILLEGAL_TASK_TRANSITION",
                    event,
                    f"Task '{task_id}': {current} → {target_state} is an illegal transition"
                )
            else:
                self._task_states[task_id] = target_state

    # ── Heartbeat reconciliation check ────────────────────────────────────────

    def validate_heartbeat(self, authoritative_active_tasks: list):
        """
        Compare heartbeat's authoritative active task list against auditor's
        internal model. Emit violation if Godot-visible set diverges.
        """
        auditor_active = {
            tid for tid, state in self._task_states.items()
            if state in (TaskState.CREATED, TaskState.STARTED)
        }
        authoritative_set = set(authoritative_active_tasks)

        orphans_in_auditor = auditor_active - authoritative_set
        orphans_in_auth = authoritative_set - auditor_active

        if orphans_in_auditor:
            self._violation(
                "HEARTBEAT_GHOST_TASKS",
                {"authoritative": list(authoritative_set), "auditor": list(auditor_active)},
                f"Auditor knows active tasks not in heartbeat: {orphans_in_auditor}"
            )
        if orphans_in_auth:
            self._violation(
                "HEARTBEAT_UNKNOWN_TASKS",
                {"authoritative": list(authoritative_set), "auditor": list(auditor_active)},
                f"Heartbeat has active tasks unknown to auditor: {orphans_in_auth}"
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _violation(self, code: str, context: dict, message: str):
        self.violation_count += 1
        violation = {
            "code": code,
            "message": message,
            "context": context,
            "timestamp": time.time(),
            "violation_number": self.violation_count,
        }
        logger.error(f"[Auditor] INVARIANT VIOLATION #{self.violation_count} [{code}]: {message}")
        self._supervisor(violation)

    @staticmethod
    def _default_supervisor(violation: dict):
        """Default: log only. Production systems should inject a real supervisor."""
        logger.critical(
            f"[Supervisor] Unhandled violation {violation['code']} — "
            "inject a supervisor_callback to handle this."
        )
