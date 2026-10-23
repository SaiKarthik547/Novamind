"""
core/contracts/runtime_events.py

Phase 15/16: Semantic Event Hierarchy & Execution State Machine.
The single authoritative source for runtime and IPC event semantics.
Eliminates taxonomy inflation by providing strict semantic domains.
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import time
import uuid

PROTOCOL_VERSION = "1.1.0"

class ExecutionState(Enum):
    """Formal Execution State Machine for Verification Semantics."""
    PENDING = "PENDING"           # Scheduler holds the intent
    DISPATCHED = "DISPATCHED"     # Sent to Lane Adapter (Gateway)
    ACCEPTED = "ACCEPTED"         # API accepted the call (e.g. PostMessage returned True)
    MUTATED = "MUTATED"           # Target state actually changed (Passive verification started)
    OBSERVED = "OBSERVED"         # Mutation seen by the Verifier
    VERIFIED = "VERIFIED"         # Verifier confirms semantic success
    CONVERGED = "CONVERGED"       # Topology fully reconciled
    INVALIDATED = "INVALIDATED"   # HWND died, UIPI blocked, or Watchdog timeout

@dataclass(frozen=True)
class RuntimeEvent:
    """
    Base causal event model. 
    Guarantees causal lineage for Replay integrity.
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.monotonic)
    parent_event_id: Optional[str] = None
    causal_lineage: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)

# ── Semantic Event Hierarchy ──────────────────────────────────────────

@dataclass(frozen=True)
class LifecycleEvent(RuntimeEvent):
    """
    Domain: Window/Process lifecycle invalidation.
    E.g., HWND destroyed, thread detached, UAC elevation.
    """
    hwnd: int = 0
    pid: int = 0
    is_dead: bool = False
    reason: str = ""

@dataclass(frozen=True)
class ExecutionEvent(RuntimeEvent):
    """
    Domain: Intent Execution and State Machine transitions.
    Replaces granular (ButtonHoverEvent) with a unified ExecutionState.
    """
    intent_id: str = ""
    target_hwnd: Optional[int] = None
    state: ExecutionState = ExecutionState.PENDING
    payload: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

@dataclass(frozen=True)
class VerificationEvent(RuntimeEvent):
    """
    Domain: Passive verification conclusions and reconciliation.
    """
    intent_id: str = ""
    success: bool = False
    metrics: Dict[str, Any] = field(default_factory=dict)
    divergence_detected: bool = False

@dataclass(frozen=True)
class SchedulerEvent(RuntimeEvent):
    """
    Domain: Topology coordination, queue aborts, and Watchdog escalation.
    """
    action: str = "" # e.g., "QUEUE_ABORT", "WATCHDOG_TIMEOUT", "STARVATION_ESCALATION"
    target_queue_id: str = ""
    reason: str = ""

@dataclass(frozen=True)
class TelemetryEvent(RuntimeEvent):
    """
    Domain: Pure observability. Does not affect runtime topology.
    """
    severity: str = "INFO"
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

# Retaining critical legacy enums until full transition
class PanicLevel(Enum):
    WORKER_CRASH = "worker_crash"
    KERNEL_CORRUPTION = "kernel_corruption"
    TIMEOUT = "timeout"
    IPC_DESYNC = "ipc_desync"


# ── IPC/event type taxonomy (transitional canonical) ──────────────────────────

class MessageType(Enum):
    """Canonical IPC message envelope types."""
    COMMAND = "COMMAND"
    EVENT = "EVENT"
    STATE_UPDATE = "STATE_UPDATE"
    HEARTBEAT = "HEARTBEAT"
    ERROR = "ERROR"
    SYSTEM = "SYSTEM"


class EventType(Enum):
    """Canonical event type taxonomy used by IPC and runtime observers."""
    SYSTEM_HEARTBEAT = "system_heartbeat"
    WORKER_STARTED = "worker_started"
    WORKER_BOUND = "worker_bound"
    WORKER_KILLED = "worker_killed"
    AGENT_LIFECYCLE_CREATED = "agent_lifecycle_created"
    AGENT_LIFECYCLE_DESTROYED = "agent_lifecycle_destroyed"
    AGENT_TASK_STARTED = "agent_task_started"
    AGENT_TASK_COMPLETED = "agent_task_completed"
    AGENT_TASK_FAILED = "agent_task_failed"


MessageType._ALL: frozenset = frozenset({m.value for m in MessageType})
EventType._ALL: frozenset = frozenset({e.value for e in EventType})


# ── Worker death reason taxonomy ──────────────────────────────────────────────

class WorkerDeathReason(Enum):
    """Canonical reasons for worker death, used by WorkerSupervisor and recovery."""
    UNKNOWN = "unknown"
    UNHANDLED_EXCEPTION = "unhandled_exception"
    CAPABILITY_VIOLATION = "capability_violation"
    IPC_TIMEOUT = "ipc_timeout"
    SUPERVISOR_TERMINATED = "supervisor_terminated"
    JOB_OBJECT_ERROR = "job_object_error"
    SANDBOX_ERROR = "sandbox_error"
