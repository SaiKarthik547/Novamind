"""
core/contracts/runtime_events.py
Protocol Freeze - The single authoritative source for runtime and IPC event semantics.
Do NOT allow arbitrary enums, freeform event names, or scattered string literals.
All runtime event semantics must originate here.
"""

from enum import Enum

PROTOCOL_VERSION = "1.0.0"
MIN_SUPPORTED_PROTOCOL_VERSION = "1.0.0"


class RuntimeState(Enum):
    BOOT = "boot"
    PRECHECK = "precheck"
    RECOVER = "recover"
    VERIFY_WAL = "verify_wal"
    VERIFY_WORKERS = "verify_workers"
    START_IPC = "start_ipc"
    START_SCHEDULER = "start_scheduler"
    READY = "ready"
    DEGRADED = "degraded"
    RECOVERY = "recovery"
    QUIESCING = "quiescing"
    HALT = "halt"
    PANIC = "panic"


class PanicLevel(Enum):
    WORKER_CRASH = "worker_crash"
    KERNEL_CORRUPTION = "kernel_corruption"
    TIMEOUT = "timeout"
    IPC_DESYNC = "ipc_desync"


class MessageType:
    COMMAND = "COMMAND"
    EVENT = "EVENT"
    STATE_UPDATE = "STATE_UPDATE"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    SYSTEM = "SYSTEM"

    _ALL = frozenset({COMMAND, EVENT, STATE_UPDATE, ERROR, HEARTBEAT, SYSTEM})


class EventType:
    USER_COMMAND_ISSUED = "USER_COMMAND_ISSUED"
    AGENT_TOOL_CALL = "AGENT_TOOL_CALL"
    AGENT_TASK_STARTED = "AGENT_TASK_STARTED"
    AGENT_TASK_COMPLETED = "AGENT_TASK_COMPLETED"
    AGENT_TASK_FAILED = "AGENT_TASK_FAILED"
    AGENT_LIFECYCLE_CREATED = "AGENT_LIFECYCLE_CREATED"
    AGENT_LIFECYCLE_DESTROYED = "AGENT_LIFECYCLE_DESTROYED"
    SYSTEM_HEARTBEAT = "SYSTEM_HEARTBEAT"
    SCENE_LOAD = "SCENE_LOAD"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    STATE_DIVERGENCE = "STATE_DIVERGENCE"
    RECONCILIATION_REQUEST = "RECONCILIATION_REQUEST"
    RECONCILIATION_RESPONSE = "RECONCILIATION_RESPONSE"
    REPLAY_SYNC = "REPLAY_SYNC"
    WORKER_STARTED = "WORKER_STARTED"
    WORKER_BOUND = "WORKER_BOUND"
    WORKER_KILLED = "WORKER_KILLED"
    WORKER_LIMIT_EXCEEDED = "WORKER_LIMIT_EXCEEDED"
    WORKER_CAPABILITY_VIOLATION = "WORKER_CAPABILITY_VIOLATION"

    _ALL = frozenset({
        USER_COMMAND_ISSUED, AGENT_TOOL_CALL, AGENT_TASK_STARTED,
        AGENT_TASK_COMPLETED, AGENT_TASK_FAILED, AGENT_LIFECYCLE_CREATED,
        AGENT_LIFECYCLE_DESTROYED, SYSTEM_HEARTBEAT, SCENE_LOAD,
        INVARIANT_VIOLATION, STATE_DIVERGENCE, RECONCILIATION_REQUEST,
        RECONCILIATION_RESPONSE, REPLAY_SYNC, WORKER_STARTED, WORKER_BOUND,
        WORKER_KILLED, WORKER_LIMIT_EXCEEDED, WORKER_CAPABILITY_VIOLATION
    })


class TransportState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    ACTIVE = "active"
    DEGRADED = "degraded"
    QUIESCING = "quiescing"
    TERMINATED = "terminated"


class WorkerState(Enum):
    STARTING = "starting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"


class WorkerDeathReason(Enum):
    NORMAL_EXIT = "normal_exit"
    SUPERVISOR_TERMINATED = "supervisor_terminated"
    JOB_MEMORY_LIMIT = "job_memory_limit"
    JOB_CPU_LIMIT = "job_cpu_limit"
    IPC_TIMEOUT = "ipc_timeout"
    CAPABILITY_VIOLATION = "capability_violation"
    UNHANDLED_EXCEPTION = "unhandled_exception"
    UNKNOWN = "unknown"
