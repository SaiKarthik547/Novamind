"""
Task Scheduler — Priority queue + time-based scheduling for NovaMind.
Supports: immediate, scheduled, recurring, priority-ordered execution.
All tasks run in background threads and report status back to the UI.
"""
import json
import time
import uuid
import heapq
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Scheduler")


class Priority(Enum):
    CRITICAL = 0   # Runs immediately, skips queue
    HIGH     = 1
    NORMAL   = 2
    LOW      = 3
    IDLE     = 4   # Only when nothing else is queued


class ScheduledTaskStatus(Enum):
    QUEUED    = "queued"
    WAITING   = "waiting"       # Scheduled for future time
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    RECURRING = "recurring"     # Completed one cycle, waiting for next


@dataclass(order=True)
class ScheduledTask:
    run_at:      float              # Unix timestamp — when to run next
    priority:    int                # Lower = higher priority
    task_id:     str = field(compare=False)
    request:     str = field(compare=False)
    context:     Dict = field(default_factory=dict, compare=False)
    recur_every: Optional[float] = field(default=None, compare=False)  # seconds
    max_runs:    int = field(default=1, compare=False)
    runs_done:   int = field(default=0, compare=False)
    status:      ScheduledTaskStatus = field(default=ScheduledTaskStatus.QUEUED,
                                             compare=False)
    created_at:  str = field(default_factory=lambda: datetime.now().isoformat(),
                              compare=False)
    last_run_at: str = field(default="", compare=False)
    last_result: Dict = field(default_factory=dict, compare=False)
    on_done:     Optional[Callable] = field(default=None, compare=False)
    label:       str = field(default="", compare=False)

    def to_dict(self) -> Dict:
        return {
            "task_id":     self.task_id,
            "request":     self.request,
            "label":       self.label or self.request[:60],
            "priority":    Priority(self.priority).name,
            "status":      self.status.value,
            "run_at":      datetime.fromtimestamp(self.run_at).isoformat(),
            "recur_every": self.recur_every,
            "max_runs":    self.max_runs,
            "runs_done":   self.runs_done,
            "created_at":  self.created_at,
            "last_run_at": self.last_run_at,
            "last_result": self.last_result,
        }


class TaskScheduler:
    """
    Background task scheduler with priority queue and time-based triggering.

    Usage:
        scheduler = TaskScheduler(brain=brain)
        scheduler.start()

        # Run immediately
        scheduler.submit("Draw a blue sports car in MS Paint")

        # Run at specific time
        scheduler.submit("Backup my documents folder",
                         run_at=datetime(2025,1,1,9,0,0))

        # Run every hour
        scheduler.submit("Check system resources",
                         recur_every=3600, max_runs=24)

        # High priority
        scheduler.submit("Close all Chrome windows",
                         priority=Priority.HIGH)
    """

    MAX_WORKERS = 3
    TICK = 0.5   # seconds between queue checks

    def __init__(self, brain=None, memory=None):
        self.brain  = brain
        self.memory = memory

        self._heap: List[ScheduledTask] = []   # min-heap (run_at, priority)
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock  = threading.Lock()
        self._running = False
        self._worker_sem = threading.Semaphore(self.MAX_WORKERS)
        self._dispatcher: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[Dict], None]] = []

    # ──────────────────────────────────────────────────────
    #  Lifecycle
    # ──────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop,
            daemon=True, name="Scheduler-Dispatch"
        )
        self._dispatcher.start()
        logger.info("TaskScheduler started")

    def stop(self):
        self._running = False
        if self._dispatcher:
            self._dispatcher.join(timeout=3)
        logger.info("TaskScheduler stopped")

    # ──────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────

    def submit(self, request: str,
               priority: Priority = Priority.NORMAL,
               run_at: Optional[datetime] = None,
               delay_secs: float = 0.0,
               recur_every: Optional[float] = None,
               max_runs: int = 1,
               context: Dict = None,
               label: str = "",
               on_done: Optional[Callable] = None) -> str:
        """
        Schedule a task.

        Args:
            request:      Plain English task description (same as Brain.process_request)
            priority:     Priority enum value
            run_at:       datetime to run (None = now + delay_secs)
            delay_secs:   Delay in seconds from now
            recur_every:  If set, task repeats every N seconds
            max_runs:     Maximum number of times to run (use 0 for infinite)
            context:      Extra context dict passed to Brain
            label:        Human-readable label for the UI
            on_done:      Callback(result_dict) called when task completes
        """
        task_id = str(uuid.uuid4())

        if run_at is not None:
            ts = run_at.timestamp()
        else:
            ts = time.time() + max(0, delay_secs)

        task = ScheduledTask(
            run_at      = ts,
            priority    = priority.value,
            task_id     = task_id,
            request     = request,
            context     = context or {},
            recur_every = recur_every,
            max_runs    = max_runs if max_runs > 0 else 999_999,
            label       = label or request[:60],
            on_done     = on_done,
        )

        if delay_secs > 0 or run_at is not None:
            task.status = ScheduledTaskStatus.WAITING

        with self._lock:
            heapq.heappush(self._heap, task)
            self._tasks[task_id] = task

        self._notify_all()
        logger.info(
            f"Scheduled [{task_id[:8]}] '{request[:50]}' "
            f"priority={priority.name} "
            f"at={datetime.fromtimestamp(ts).strftime('%H:%M:%S')}"
        )
        return task_id

    def cancel(self, task_id: str) -> bool:
        """Cancel a queued or waiting task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status in (ScheduledTaskStatus.QUEUED,
                                        ScheduledTaskStatus.WAITING,
                                        ScheduledTaskStatus.RECURRING):
                task.status = ScheduledTaskStatus.CANCELLED
                self._notify_all()
                return True
        return False

    def get_task(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            t = self._tasks.get(task_id)
        return t.to_dict() if t else None

    def get_all_tasks(self, status: Optional[str] = None) -> List[Dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.run_at)
        result = [t.to_dict() for t in tasks]
        if status:
            result = [t for t in result if t["status"] == status]
        return result

    def get_stats(self) -> Dict:
        with self._lock:
            tasks = list(self._tasks.values())
        by_status = {}
        for t in tasks:
            s = t.status.value
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "total":    len(tasks),
            "by_status": by_status,
            "workers":  self.MAX_WORKERS,
            "running":  self._running,
        }

    def register_callback(self, fn: Callable):
        """Register a callback that fires whenever task status changes."""
        self._callbacks.append(fn)

    # ──────────────────────────────────────────────────────
    #  Dispatch loop (runs in background thread)
    # ──────────────────────────────────────────────────────

    def _dispatch_loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Scheduler dispatch error: {e}", exc_info=True)
            time.sleep(self.TICK)

    def _tick(self):
        """Standard scheduler tick loop."""
        now = time.time()
        with self._lock:
            while self._heap and self._heap[0].run_at <= now:
                task = self._heap[0]
                
                if task.status in (ScheduledTaskStatus.CANCELLED, ScheduledTaskStatus.RUNNING):
                    heapq.heappop(self._heap)
                    continue
                    
                heapq.heappop(self._heap)
                self._execute_async(task)

    def _execute_async(self, task):
        task.status = ScheduledTaskStatus.RUNNING
        threading.Thread(
            target=self._run_task,
            args=(task,),
            daemon=True,
            name=f"sched-{task.task_id[:8]}",
        ).start()

    def _execute_via_brain(self, task: ScheduledTask) -> Dict:
        try:
            exec_ = self.brain.process_request(task.request, context=task.context)
            deadline = time.time() + 300
            finished = False

            while time.time() < deadline and not finished:
                s = self.brain.get_task_status(exec_.task_id)
                status_str = s.get("status", "pending") if s else "pending"
                if status_str not in ("pending", "running", "retrying"):
                    finished = True
                else:
                    time.sleep(1.5)
            
            if time.time() < deadline:
                return self.brain.get_task_status(exec_.task_id)
            else:
                return {"status": "timeout", "task_id": exec_.task_id}
        except Exception as e:
            logger.error(f"Task run failed: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    def _run_task(self, task: ScheduledTask):
        with self._worker_sem:
            logger.info(f"Running [{task.task_id[:8]}] '{task.request[:50]}'")
            task.last_run_at = datetime.now().isoformat()
            task.runs_done  += 1
            result = {}

            if self.brain is not None:
                result = self._execute_via_brain(task)
            else:
                result = {"status": "no_brain"}

            task.last_result = result

            with self._lock:
                is_done = task.runs_done >= task.max_runs
                is_recurring = not is_done and task.recur_every is not None
                
                if is_recurring:
                    task.status = ScheduledTaskStatus.RECURRING
                    task.run_at = time.time() + task.recur_every
                    heapq.heappush(self._heap, task)
                else:
                    if result.get("status") == "success":
                        task.status = ScheduledTaskStatus.DONE
                    else:
                        task.status = ScheduledTaskStatus.FAILED

            if task.on_done:
                try:
                    task.on_done(task.to_dict())
                except Exception as e:
                    logger.warning(f"on_done callback failed: {e}")

            self._notify_all()
            logger.info(
                f"Finished [{task.task_id[:8]}] status={task.status.value} "
                f"runs={task.runs_done}/{task.max_runs}"
            )

    def _notify_all(self):
        snapshot = self.get_all_tasks()
        for fn in self._callbacks:
            try:
                fn(snapshot)
            except Exception:
                pass
