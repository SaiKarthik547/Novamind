import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

class TelemetryClass(enum.Enum):
    """Classification dictates where and how telemetry is routed and persisted."""
    EPHEMERAL = "EPHEMERAL"              # Memory only, dropped under backpressure
    FORENSIC = "FORENSIC"                # Routed to Telemetry Sink for diagnostics
    REPLAY_CRITICAL = "REPLAY_CRITICAL"  # MUST be linked to deterministic WAL lineage

class ReplayIntegrityLevel(enum.Enum):
    """Confidence level that an action can be deterministically replayed."""
    VERIFIED = "VERIFIED"
    DEGRADED = "DEGRADED"
    NON_DETERMINISTIC = "NON_DETERMINISTIC" # Legacy UI manipulation

class DeterminismLevel(enum.Enum):
    """Adapter-level determinism declaration."""
    STRICT = "STRICT"
    RECONCILABLE = "RECONCILABLE"
    PROBABILISTIC = "PROBABILISTIC"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"

class IntentLifecycleEvent(enum.Enum):
    """Lineage tracking for intent semantics."""
    INTENT_CREATED = "INTENT_CREATED"
    INTENT_DISPATCHED = "INTENT_DISPATCHED"
    INTENT_STARTED = "INTENT_STARTED"
    INTENT_VERIFIED = "INTENT_VERIFIED"
    INTENT_FAILED = "INTENT_FAILED"
    INTENT_COMPENSATED = "INTENT_COMPENSATED"

@dataclass
class TelemetryEvent:
    """
    Internal fast-path structure for telemetry. 
    Does not use Pydantic to avoid GC/validation jitter in the hot path.
    """
    event_type: str
    telemetry_class: TelemetryClass
    payload: Dict[str, Any]
    
    # Lineage / Origin
    worker_id: Optional[str] = None
    adapter_id: Optional[str] = None
    transaction_id: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # State mapping
    runtime_state: str = "UNKNOWN"
    severity: str = "INFO"
    replay_integrity: ReplayIntegrityLevel = ReplayIntegrityLevel.VERIFIED
    
    # Timing
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ns: int = field(default_factory=time.time_ns)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Canonical Serialization (WAL/Sink)."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "telemetry_class": self.telemetry_class.value,
            "timestamp_ns": self.timestamp_ns,
            "worker_id": self.worker_id,
            "adapter_id": self.adapter_id,
            "transaction_id": self.transaction_id,
            "correlation_id": self.correlation_id,
            "runtime_state": self.runtime_state,
            "severity": self.severity,
            "replay_integrity": self.replay_integrity.value,
            "payload": self.payload
        }
