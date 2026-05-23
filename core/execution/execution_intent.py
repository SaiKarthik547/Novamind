import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional

class IntentStatus(Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

class VerificationMode(Enum):
    EXACT = "EXACT"              # Byte-identical verification
    STRUCTURAL = "STRUCTURAL"    # Object shape/state verification
    SEMANTIC = "SEMANTIC"        # Intended OS outcome verification
    HEURISTIC = "HEURISTIC"      # Best-effort AI validation
    NONE = "NONE"                # Fire-and-forget

class RollbackMode(Enum):
    TERMINATE_TREE = "TERMINATE_TREE"
    REVERT_STATE = "REVERT_STATE"
    NO_ROLLBACK = "NO_ROLLBACK"

class IntentPriority(Enum):
    BACKGROUND = 0
    STANDARD = 1
    HIGH = 2
    CRITICAL = 3

class IntentDeterminismLevel(Enum):
    STRICT = "STRICT"
    PROBABILISTIC = "PROBABILISTIC"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"

@dataclass
class ExecutionIntent:
    """
    The boundary between Agent Intelligence and Kernel Execution.
    Agents emit Intents. They DO NOT execute them.
    Intents are serializable, replayable, and schedulable.
    """
    adapter: str             # e.g., 'process', 'filesystem', 'registry'
    operation: str           # e.g., 'spawn', 'write_file', 'set_key'
    idempotent: bool         # Mandatory declaration for replay safety
    
    verification_mode: VerificationMode
    rollback_strategy: RollbackMode
    capability_scope: Dict[str, Any]
    payload: Dict[str, Any]
    
    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = "UNKNOWN"
    status: IntentStatus = IntentStatus.PENDING
    
    # Scheduling & Determinism
    priority: IntentPriority = IntentPriority.STANDARD
    determinism: IntentDeterminismLevel = IntentDeterminismLevel.PROBABILISTIC
    timeout_ms: int = 30000
    
    # Results
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "agent_id": self.agent_id,
            "adapter": self.adapter,
            "operation": self.operation,
            "idempotent": self.idempotent,
            "verification_mode": self.verification_mode.value,
            "rollback_strategy": self.rollback_strategy.value,
            "capability_scope": self.capability_scope,
            "payload": self.payload,
            "status": self.status.value,
            "priority": self.priority.name,
            "determinism": self.determinism.value,
            "timeout_ms": self.timeout_ms,
            "result": self.result,
            "error": self.error
        }
