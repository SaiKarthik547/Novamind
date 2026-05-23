import logging
import threading
from typing import Dict, Any
from collections import defaultdict

logger = logging.getLogger("RuntimeMetrics")

class RuntimeMetrics:
    """
    P13G-1: Collects telemetry and metrics for the Runtime Kernel.
    P13F-1: Aggregates authority_origin breakdown to track Legacy Bridge elimination.
    """
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'RuntimeMetrics':
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._metrics_lock = threading.Lock()
        
        # Telemetry counters
        self.total_intents = 0
        self.successful_intents = 0
        self.failed_intents = 0
        
        # P13F-1: authority_origin breakdown
        self.authority_breakdown: Dict[str, int] = defaultdict(int)
        
        # Performance
        self.cumulative_duration_ms = 0

    def record_intent_completion(self, result: 'IntentResult'):
        """Record the metrics from a completed or failed intent."""
        with self._metrics_lock:
            self.total_intents += 1
            if result.success:
                self.successful_intents += 1
            else:
                self.failed_intents += 1
                
            origin = result.metrics.get("authority_origin", "unknown")
            self.authority_breakdown[origin] += 1
            
            duration = result.metrics.get("duration_ms", 0)
            self.cumulative_duration_ms += duration

    def dump_metrics(self) -> Dict[str, Any]:
        """Returns the current metrics snapshot."""
        with self._metrics_lock:
            return {
                "total_intents": self.total_intents,
                "successful_intents": self.successful_intents,
                "failed_intents": self.failed_intents,
                "authority_breakdown": dict(self.authority_breakdown),
                "cumulative_duration_ms": self.cumulative_duration_ms,
                "average_duration_ms": self.cumulative_duration_ms / max(1, self.total_intents)
            }
