import logging
import json
import time
from typing import Dict, Any, List

from core.execution.intent_result import IntentResult
from core.execution.execution_intent import ExecutionIntent

logger = logging.getLogger("IntentTrace")

class IntentTrace:
    """
    P13G-2: Structured debugging and observability for Intent execution.
    Maintains a deterministic replay log of events.
    """
    def __init__(self, intent_id: str):
        self.intent_id = intent_id
        self.events: List[Dict[str, Any]] = []
        self.start_time = time.monotonic()
        
    def add_event(self, event_type: str, details: Dict[str, Any]):
        """Records a point-in-time trace event."""
        self.events.append({
            "timestamp": time.time(),
            "elapsed_ms": int((time.monotonic() - self.start_time) * 1000),
            "event_type": event_type,
            "details": details
        })
        logger.debug(f"[Trace {self.intent_id[:8]}] {event_type} | {json.dumps(details)}")

    def finalize(self, result: IntentResult):
        """Finalizes the trace when the intent completes or fails."""
        self.add_event("COMPLETED", {
            "success": result.success,
            "error": result.error,
            "metrics": result.metrics
        })

    def get_trace(self) -> Dict[str, Any]:
        """Returns the full trace payload for diagnostic purposes."""
        return {
            "intent_id": self.intent_id,
            "duration_ms": int((time.monotonic() - self.start_time) * 1000),
            "events": self.events
        }
