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

@dataclass
class ExecutionIntent:
    """
    The boundary between Agent Intelligence and Kernel Execution.
    Agents emit Intents. They DO NOT execute them.
    Intents are serializable, replayable, and schedulable.
    """
    target_adapter: str  # e.g., 'chrome', 'pty', 'filesystem'
    action: str          # e.g., 'navigate', 'run_command', 'write_file'
    payload: Dict[str, Any]
    
    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = "UNKNOWN"
    status: IntentStatus = IntentStatus.PENDING
    
    # Scheduling & Determinism
    priority: int = 0
    timeout_ms: int = 30000
    idempotent: bool = False
    
    # Results
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "agent_id": self.agent_id,
            "target_adapter": self.target_adapter,
            "action": self.action,
            "payload": self.payload,
            "status": self.status.value,
            "priority": self.priority,
            "timeout_ms": self.timeout_ms,
            "idempotent": self.idempotent,
            "result": self.result,
            "error": self.error
        }
