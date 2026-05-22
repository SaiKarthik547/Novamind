import logging
import psutil
import time
from typing import Dict, List, Optional
from core.runtime.capability_broker import ResourceBudget

logger = logging.getLogger("ResourceGovernor")


class ResourceViolation(Exception):
    pass


class StarvationError(Exception):
    pass


class ResourceGovernor:
    """
    Enforces ResourceBudgets associated with ExecutionLeases.
    Provides OS-level process enforcement, starvation detection, and hard quotas.
    """
    def __init__(self):
        self._monitored_processes: Dict[int, Dict] = {}
        self._dispatch_count = 0
        self.max_dispatches_per_minute = 1000

    def register_process(self, pid: int, task_id: str, budget: ResourceBudget):
        try:
            proc = psutil.Process(pid)
            self._monitored_processes[pid] = {
                "process": proc,
                "task_id": task_id,
                "budget": budget,
                "start_time": time.monotonic()
            }
            logger.debug(f"Governor enforcing PID {pid} for task {task_id[:8]}")
        except psutil.NoSuchProcess:
            logger.warning(f"PID {pid} already dead before governor could track")

    def unregister_process(self, pid: int):
        self._monitored_processes.pop(pid, None)
        
    def record_dispatch(self):
        self._dispatch_count += 1
        # Simplistic starvation policy: if we hit 1000 dispatches rapidly, sleep briefly to let OS catch up
        if self._dispatch_count % self.max_dispatches_per_minute == 0:
            logger.warning("Dispatch quota reached. Throttling to prevent starvation.")
            time.sleep(1.0)

    def check_resources(self):
        """
        Called periodically (e.g., by KernelSupervisor) to enforce budgets.
        """
        dead_pids = []
        for pid, data in self._monitored_processes.items():
            proc: psutil.Process = data["process"]
            budget: ResourceBudget = data["budget"]
            start_time: float = data["start_time"]
            
            try:
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    dead_pids.append(pid)
                    continue
                    
                duration = time.monotonic() - start_time
                if duration > budget.max_duration_seconds:
                    self._terminate_violator(proc, f"Duration exceeded ({duration:.1f}s > {budget.max_duration_seconds}s)")
                    dead_pids.append(pid)
                    continue

                # Starvation detection: if a process is using 100% CPU for too long
                cpu_percent = proc.cpu_percent(interval=0.0)
                if cpu_percent > 95.0 and duration > 30.0:
                    self._terminate_violator(proc, f"CPU Starvation detected (>95% for 30s)")
                    dead_pids.append(pid)
                    continue

                mem_mb = proc.memory_info().rss / (1024 * 1024)
                if mem_mb > budget.max_memory_mb:
                    self._terminate_violator(proc, f"Memory exceeded ({mem_mb:.1f}MB > {budget.max_memory_mb}MB)")
                    dead_pids.append(pid)
                    continue

                num_threads = proc.num_threads()
                if num_threads > budget.max_threads:
                    self._terminate_violator(proc, f"Thread count exceeded ({num_threads} > {budget.max_threads})")
                    dead_pids.append(pid)
                    continue

                # Child processes count
                children = proc.children(recursive=True)
                if len(children) > budget.max_subprocesses:
                    self._terminate_violator(proc, f"Subprocess count exceeded ({len(children)} > {budget.max_subprocesses})")
                    dead_pids.append(pid)
                    continue

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                dead_pids.append(pid)
                continue

        for pid in dead_pids:
            self.unregister_process(pid)

    def _terminate_violator(self, proc: psutil.Process, reason: str):
        logger.error(f"Resource violation for PID {proc.pid}: {reason}. Terminating.")
        try:
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
