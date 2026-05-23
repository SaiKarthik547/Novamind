import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

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

class RuntimeMetrics:
    """
    Live runtime metrics aggregation.
    Ring-buffered and snapshot-based to prevent OOM / unbounded growth.
    """
    def __init__(self, history_size: int = 600):
        # Store last N snapshots (e.g. 600 seconds = 10 mins if sampled 1/sec)
        self.history_size = history_size
        
        self._worker_metrics: Dict[str, deque] = {}
        self._system_metrics: deque = deque(maxlen=history_size)
        self._lock = threading.Lock()

    def record_worker_snapshot(self, snapshot: WorkerMetricsSnapshot):
        with self._lock:
            worker_id = snapshot.worker_id
            if worker_id not in self._worker_metrics:
                self._worker_metrics[worker_id] = deque(maxlen=self.history_size)
            self._worker_metrics[worker_id].append(snapshot)

    def record_system_snapshot(self, snapshot: SystemMetricsSnapshot):
        with self._lock:
            self._system_metrics.append(snapshot)

    def get_worker_history(self, worker_id: str) -> List[WorkerMetricsSnapshot]:
        with self._lock:
            if worker_id not in self._worker_metrics:
                return []
            return list(self._worker_metrics[worker_id])

    def get_system_history(self) -> List[SystemMetricsSnapshot]:
        with self._lock:
            return list(self._system_metrics)

    def prune_dead_workers(self, active_worker_ids: set[str]):
        """Remove metrics for workers that have cleanly terminated to save memory."""
        with self._lock:
            dead_workers = [w for w in self._worker_metrics.keys() if w not in active_worker_ids]
            for w in dead_workers:
                del self._worker_metrics[w]
