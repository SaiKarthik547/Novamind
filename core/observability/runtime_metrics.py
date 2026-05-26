import logging
import threading
from typing import Dict, Any, List
from collections import defaultdict, deque
from dataclasses import dataclass

@dataclass
class WorkerMetricsSnapshot:
    timestamp_ns: int
    worker_id: str
    cpu_percent: float
    memory_mb: float
    queue_depth: int

@dataclass
class SystemMetricsSnapshot:
    timestamp_ns: int
    ipc_throughput_kbps: float
    telemetry_queue_depth: int
    active_workers: int

logger = logging.getLogger("RuntimeMetrics")

class RuntimeMetrics:
    """
    P14E-1: Collects telemetry and metrics for the Runtime Kernel.
    
    OBSERVABILITY ISOLATION LAW:
    This class must never mutate runtime state, trigger reconciliation, 
    alter capability trust, or change execution topology. It is strictly passive.
    """
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'RuntimeMetrics':
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, history_size: int = 600):
        self._metrics_lock = threading.Lock()
        
        # Ring buffers for telemetry
        self.history_size = history_size
        self._worker_metrics: Dict[str, deque] = {}
        self._system_metrics: deque = deque(maxlen=history_size)
        
        # Telemetry counters
        self.total_intents = 0
        self.successful_intents = 0
        self.failed_intents = 0
        
        # Phase 14 Telemetry
        self.replay_divergence_count = 0
        self.orphan_count = 0
        self.recovery_success_count = 0
        self.lock_contention_count = 0
        
        # P13F-1: authority_origin breakdown
        self.authority_breakdown: Dict[str, int] = defaultdict(int)
        
        # Performance
        self.cumulative_duration_ms = 0

    def record_worker_snapshot(self, snapshot: WorkerMetricsSnapshot):
        with self._metrics_lock:
            worker_id = snapshot.worker_id
            if worker_id not in self._worker_metrics:
                self._worker_metrics[worker_id] = deque(maxlen=self.history_size)
            self._worker_metrics[worker_id].append(snapshot)

    def record_system_snapshot(self, snapshot: SystemMetricsSnapshot):
        with self._metrics_lock:
            self._system_metrics.append(snapshot)

    def get_worker_history(self, worker_id: str) -> List[WorkerMetricsSnapshot]:
        with self._metrics_lock:
            if worker_id not in self._worker_metrics:
                return []
            return list(self._worker_metrics[worker_id])

    def get_system_history(self) -> List[SystemMetricsSnapshot]:
        with self._metrics_lock:
            return list(self._system_metrics)

    def prune_dead_workers(self, active_worker_ids: set[str]):
        """Remove metrics for workers that have cleanly terminated to save memory."""
        with self._metrics_lock:
            dead_workers = [w for w in self._worker_metrics.keys() if w not in active_worker_ids]
            for w in dead_workers:
                del self._worker_metrics[w]

    def record_intent_completion(self, result: 'IntentResult'):
        """Record the metrics from a completed or failed intent."""
        with self._metrics_lock:
            self.total_intents += 1
            if result.success:
                self.successful_intents += 1
            else:
                self.failed_intents += 1
                
            origin = getattr(result, "metrics", {}).get("authority_origin", "unknown")
            self.authority_breakdown[origin] += 1
            
            duration = getattr(result, "metrics", {}).get("duration_ms", 0)
            self.cumulative_duration_ms += duration

    def record_replay_divergence(self):
        with self._metrics_lock:
            self.replay_divergence_count += 1

    def record_orphan(self):
        with self._metrics_lock:
            self.orphan_count += 1

    def record_recovery_success(self):
        with self._metrics_lock:
            self.recovery_success_count += 1

    def record_lock_contention(self):
        with self._metrics_lock:
            self.lock_contention_count += 1

    def dump_metrics(self) -> Dict[str, Any]:
        """Returns the current metrics snapshot."""
        with self._metrics_lock:
            return {
                "total_intents": self.total_intents,
                "successful_intents": self.successful_intents,
                "failed_intents": self.failed_intents,
                "replay_divergence_count": self.replay_divergence_count,
                "orphan_count": self.orphan_count,
                "recovery_success_count": self.recovery_success_count,
                "lock_contention_count": self.lock_contention_count,
                "authority_breakdown": dict(self.authority_breakdown),
                "cumulative_duration_ms": self.cumulative_duration_ms,
                "average_duration_ms": self.cumulative_duration_ms / max(1, self.total_intents)
            }
