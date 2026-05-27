"""
core/execution/execution_scheduler.py

Phase 15A.5: Execution Scheduler Authority (True Semantics)

The SINGLE owner of execution ordering, fairness, queue topology, timeout domains,
and starvation prevention.

Upgraded to support:
- Queue Aging (Starvation Prevention)
- HWND Lifecycle Tracking (Cancellation Propagation)
- AsyncExecutionFuture (Passive Verification Handoff)
- Watchdog Escalation
"""

import time
import logging
import threading
from typing import Dict, Any, Optional, Tuple
from queue import PriorityQueue
from dataclasses import dataclass, field

from core.execution.intent_result import IntentResult
from core.execution.execution_intent import IntentStatus
from core.execution.window_lifecycle import WindowLifecycleTracker, StaleHandleError
from core.execution.verification_semantics import AsyncExecutionFuture, VerificationCoordinator, PassiveVerifier

logger = logging.getLogger("ExecutionScheduler")

@dataclass(order=True)
class ScheduledIntent:
    priority: int
    timestamp: float
    intent_id: str = field(compare=False)
    capability: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False)
    intent_meta: Dict[str, Any] = field(compare=False)
    timeout: float = field(compare=False)
    verifier: Optional[PassiveVerifier] = field(compare=False, default=None)
    future: Optional[AsyncExecutionFuture] = field(compare=False, default=None)

class ExecutionScheduler:
    """
    Centralized Execution Scheduling Authority.
    """
    
    def __init__(self, kernel_facade):
        self._kernel_facade = kernel_facade
        
        # Primary topological queues
        self._intent_queue = PriorityQueue()
        self._hwnd_queues: Dict[str, PriorityQueue] = {}
        
        # Concurrency & Topology
        self._lock = threading.RLock()
        self._active_hwnds = set()
        self._running = False
        self._scheduler_thread = None
        
        # Foundation integration
        self._lifecycle_tracker = WindowLifecycleTracker.get_instance()
        self._verification_coord = VerificationCoordinator.get_instance()

        # Telemetry
        self._telemetry = {
            "queued": 0,
            "dispatched": 0,
            "timeouts": 0,
            "starved": 0,
            "cancelled_stale_hwnd": 0
        }

    def start(self):
        with self._lock:
            if not self._running:
                self._running = True
                self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True, name="ExecutionSchedulerThread")
                self._scheduler_thread.start()

    def stop(self):
        with self._lock:
            self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=2.0)

    def submit_intent(self, capability: str, payload: Dict[str, Any], intent_meta: Dict[str, Any], 
                      timeout: float = 30.0, priority: int = 10, verifier: Optional[PassiveVerifier] = None) -> AsyncExecutionFuture:
        """
        Submit an intent. Returns an AsyncExecutionFuture which the caller can wait on.
        """
        target_hwnd = payload.get("hwnd", None)
        
        future = AsyncExecutionFuture(
            intent_id=intent_meta["intent_id"],
            target_hwnd=target_hwnd,
            dispatch_success=False,
            dispatch_metrics={},
            pre_state_snapshot=None,  # Will be captured by the verifier before dispatch if needed
            verifier=verifier
        )

        scheduled = ScheduledIntent(
            priority=priority,
            timestamp=time.monotonic(),
            intent_id=intent_meta["intent_id"],
            capability=capability,
            payload=payload,
            intent_meta=intent_meta,
            timeout=timeout,
            verifier=verifier,
            future=future
        )
        
        with self._lock:
            if target_hwnd:
                if target_hwnd not in self._hwnd_queues:
                    self._hwnd_queues[target_hwnd] = PriorityQueue()
                self._hwnd_queues[target_hwnd].put(scheduled)
            else:
                self._intent_queue.put(scheduled)
            self._telemetry["queued"] += 1

        logger.debug(f"[Scheduler] Queued intent {scheduled.intent_id} (hwnd={target_hwnd}, priority={priority})")
        return future

    def _scheduler_loop(self):
        """
        Main scheduler watchdog and dispatcher loop.
        """
        while self._running:
            try:
                with self._lock:
                    target_hwnd, scheduled = self._select_next_intent()
                    
                if not scheduled:
                    time.sleep(0.01)
                    continue

                if target_hwnd:
                    self._active_hwnds.add(target_hwnd)
                
                self._telemetry["dispatched"] += 1
                
                # Execute via gateway
                start = time.monotonic()
                try:
                    result = self._kernel_facade.execute_gateway(
                        capability=scheduled.capability,
                        payload=scheduled.payload,
                        intent_meta=scheduled.intent_meta,
                        timeout=scheduled.timeout
                    )
                    
                    scheduled.future.dispatch_success = result.success
                    scheduled.future.dispatch_metrics = result.metrics
                    
                except Exception as e:
                    logger.error(f"[Scheduler] Gateway unhandled exception for {scheduled.intent_id}: {e}")
                    scheduled.future.dispatch_success = False
                    scheduled.future.dispatch_metrics = {"error": str(e)}
                finally:
                    duration = time.monotonic() - start
                    
                    # Watchdog Escalation: If dispatch blocks the scheduler loop entirely,
                    # we must log a critical severity warning (in production, invoke PanicManager).
                    if duration > scheduled.timeout:
                        logger.critical(f"[Scheduler] WATCHDOG VIOLATION: Intent {scheduled.intent_id} blocked the scheduler for {duration:.2f}s!")
                    
                    with self._lock:
                        if target_hwnd:
                            self._active_hwnds.remove(target_hwnd)
                            
                    # Handoff to Verification Coordinator
                    self._verification_coord.verify_future(scheduled.future, timeout=scheduled.timeout)

            except Exception as e:
                logger.error(f"[Scheduler] Loop encountered fault: {e}", exc_info=True)
                time.sleep(0.1)

    def _select_next_intent(self) -> Tuple[Optional[str], Optional[ScheduledIntent]]:
        """
        Pulls the next valid intent. Handles Queue Aging and HWND Lifecycle tracking.
        """
        current_time = time.monotonic()

        # 1. HWND Lane fairness & Lifecycle Tracking
        # Iterate over a copy of items so we can safely delete empty queues
        for hwnd, queue in list(self._hwnd_queues.items()):
            if queue.empty():
                del self._hwnd_queues[hwnd]
                continue
                
            if hwnd not in self._active_hwnds:
                try:
                    # Validate HWND before dequeuing
                    self._lifecycle_tracker.assert_valid_and_owned(hwnd)
                    
                    # HWND is valid, we can schedule it
                    item = queue.get_nowait()
                    self._apply_queue_aging(queue, current_time)
                    return hwnd, item
                except StaleHandleError as e:
                    # Cancellation Propagation: The HWND is dead.
                    # Drain the entire queue for this dead HWND and cancel all futures.
                    logger.warning(f"[Scheduler] HWND {hwnd} is stale. Purging {queue.qsize()} intents. ({e})")
                    self._telemetry["cancelled_stale_hwnd"] += queue.qsize()
                    while not queue.empty():
                        stale_item = queue.get_nowait()
                        stale_item.future.dispatch_success = False
                        stale_item.future.dispatch_metrics = {"error": "StaleHandleError: HWND died before dispatch."}
                        self._verification_coord.verify_future(stale_item.future, 0.1)
                    del self._hwnd_queues[hwnd]
                    
        # 2. Generic Lane
        if not self._intent_queue.empty():
            item = self._intent_queue.get_nowait()
            self._apply_queue_aging(self._intent_queue, current_time)
            return None, item
            
        return None, None

    def _apply_queue_aging(self, queue_obj: PriorityQueue, current_time: float) -> None:
        """
        Queue Aging (Starvation Prevention): 
        Slightly boost the priority of older intents remaining in the queue.
        """
        if queue_obj.empty():
            return
            
        temp_list = []
        while not queue_obj.empty():
            item = queue_obj.get_nowait()
            # If waiting > 5 seconds, boost priority
            if current_time - item.timestamp > 5.0 and item.priority > 0:
                item.priority -= 1 
            temp_list.append(item)
            
        for item in temp_list:
            queue_obj.put(item)
