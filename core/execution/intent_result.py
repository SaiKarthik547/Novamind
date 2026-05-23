from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from core.execution.execution_intent import IntentStatus

@dataclass(frozen=True)
class IntentResult:
    """
    The canonical, immutable result of an ExecutionIntent processed by the RuntimeKernel.
    
    This explicitly breaks legacy synchronous assumptions (where Callers expected a `CompletedProcess` dict
    such as `{"returncode": ..., "stdout": ...}`). It enforces strict boundaries:
    execution state is tracked by IntentStatus, and domain-specific outputs belong in `payload`.
    """
    intent_id: str
    status: IntentStatus
    success: bool
    payload: Dict[str, Any]
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "status": self.status.value,
            "success": self.success,
            "payload": self.payload,
            "error": self.error,
            "metrics": self.metrics,
        }
