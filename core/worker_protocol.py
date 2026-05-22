import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import uuid
import time


class WorkerState(enum.Enum):
    """Explicit worker lifecycle FSM states."""
    BOOTING = "BOOTING"         # process starting
    READY = "READY"             # accepting work
    EXECUTING = "EXECUTING"     # effect active
    DEGRADED = "DEGRADED"       # partial fault
    TAINTED = "TAINTED"         # uncertain state
    TERMINATING = "TERMINATING" # supervisor shutdown
    DEAD = "DEAD"               # unrecoverable


class FrameType(enum.Enum):
    """Message frame types for deterministic IPC."""
    HANDSHAKE_SYN = 0x01
    HANDSHAKE_ACK = 0x02
    HEARTBEAT = 0x03
    EXECUTE_REQUEST = 0x10
    EXECUTE_RESULT = 0x11
    LEASE_INVALID = 0x20
    RESOURCE_LIMIT_EXCEEDED = 0x21
    WORKER_PANIC = 0x30
    TERMINATE = 0x40


@dataclass
class WorkerIdentity:
    """Identity and Attestation for a worker to prevent stale/rogue replays."""
    worker_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    boot_epoch: int = 0
    generation_counter: int = 0
    supervisor_nonce: str = ""
    
    def dict(self):
        return {
            "worker_id": self.worker_id,
            "boot_epoch": self.boot_epoch,
            "generation_counter": self.generation_counter,
            "supervisor_nonce": self.supervisor_nonce,
        }


@dataclass
class IpcFrame:
    """A standard deterministic IPC Envelope."""
    seq_num: int
    type: FrameType
    identity: WorkerIdentity
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.monotonic)
    correlation_id: str = ""

    def dict(self):
        return {
            "seq_num": self.seq_num,
            "type": self.type.value,
            "identity": self.identity.dict(),
            "payload": self.payload,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }
