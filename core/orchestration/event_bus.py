"""
core/orchestration/event_bus.py

Phase 17: Runtime Event Topology Coordinator + Causal Durability
Enforces fsync-before-propagation to preserve topological determinism across crashes.
Includes strict Topology Recursion Control to prevent event amplification storms.
"""

import asyncio
import logging
import threading
from typing import Callable, List, Optional, Dict, Set

from core.contracts.runtime_events import (
    RuntimeEvent, LifecycleEvent, ExecutionEvent, 
    VerificationEvent, SchedulerEvent, TelemetryEvent
)
from core.execution.execution_scheduler import ExecutionScheduler
from core.replay.event_recorder import RecoveryJournal

logger = logging.getLogger("RuntimeEventTopology")

MAX_PROPAGATION_DEPTH = 5

class RuntimeEventTopologyCoordinator:
    """
    Thread-safe synchronization and routing authority.
    Only accepts strongly-typed RuntimeEvent subclasses.
    Enforces fsync-before-propagation via RecoveryJournal.
    """

    def __init__(self, scheduler: Optional[ExecutionScheduler] = None, memory_system=None):
        self._subscribers: Dict[type, List[Callable]] = {}
        self._event_log: List[RuntimeEvent] = []
        
        self._scheduler = scheduler
        self._journal = RecoveryJournal()
        
        self._log_lock = threading.Lock()
        self._verification_lock = threading.Lock()
        
        # Topology Recursion Control
        self._routing_state = threading.local()

    def set_scheduler(self, scheduler: ExecutionScheduler) -> None:
        """Inject the scheduler to allow closed-loop convergence routing."""
        self._scheduler = scheduler

    def emit_sync(self, event: RuntimeEvent) -> None:
        """
        Synchronous topological routing with recursion bounds and durability guarantees.
        """
        if not isinstance(event, RuntimeEvent):
            logger.error("[Topology] Rejected untyped event emission. Must be a RuntimeEvent.")
            return

        # 1. Topology Recursion Control
        if not hasattr(self._routing_state, 'depth'):
            self._routing_state.depth = 0
            self._routing_state.seen_ids = set()

        if self._routing_state.depth >= MAX_PROPAGATION_DEPTH:
            logger.critical(f"[Topology] STORM DETECTED. Max depth {MAX_PROPAGATION_DEPTH} exceeded on event {event.event_id}.")
            self._abort_storm(event)
            return
            
        if event.event_id in self._routing_state.seen_ids:
            logger.warning(f"[Topology] CYCLE DETECTED. Event {event.event_id} already routed in this tick.")
            return

        self._routing_state.depth += 1
        self._routing_state.seen_ids.add(event.event_id)

        try:
            # 2. Causal Durability Guarantee: Fsync BEFORE Propagation
            # No topological consequence can occur unless its cause is durable.
            if not isinstance(event, TelemetryEvent):
                self._journal.commit_sync(event)

            # 3. Topological Guarantees & Closed-Loop Routing
            self._enforce_topology_rules(event)

            # 4. Sequential Guarantee for Verification
            if isinstance(event, VerificationEvent):
                with self._verification_lock:
                    self._dispatch_to_subscribers(event)
            else:
                self._dispatch_to_subscribers(event)

            # 5. In-Memory Window (Transitional)
            with self._log_lock:
                if len(self._event_log) > 5000:
                    self._event_log.pop(0)
                self._event_log.append(event)
        finally:
            self._routing_state.depth -= 1
            if self._routing_state.depth == 0:
                self._routing_state.seen_ids.clear()

    async def emit(self, event: RuntimeEvent) -> None:
        """Async wrapper."""
        self.emit_sync(event)

    def _abort_storm(self, trigger_event: RuntimeEvent) -> None:
        """Fires an emergency abort to the scheduler when a topology storm is detected."""
        abort_event = SchedulerEvent(
            parent_event_id=trigger_event.event_id,
            action="TOPOLOGY_STORM_ABORT",
            target_queue_id="GLOBAL",
            reason=f"Max propagation depth ({MAX_PROPAGATION_DEPTH}) breached."
        )
        # Bypassing depth check explicitly for the emergency abort
        self._journal.commit_sync(abort_event)
        self._dispatch_to_subscribers(abort_event)

    def _enforce_topology_rules(self, event: RuntimeEvent) -> None:
        """
        Explicit Scheduler Feedback Loop.
        This is where the topology reacts to its own failures.
        """
        if isinstance(event, LifecycleEvent) and event.is_dead:
            if self._scheduler:
                logger.warning(f"[Topology] HWND {event.hwnd} died. Routing ABORT to Scheduler.")
                abort_event = SchedulerEvent(
                    parent_event_id=event.event_id,
                    causal_lineage=event.causal_lineage + [event.event_id],
                    action="QUEUE_ABORT",
                    target_queue_id=str(event.hwnd),
                    reason="Lifecycle Invalidated (Dead Handle)"
                )
                # Emit recursively. The depth guard will protect us.
                self.emit_sync(abort_event)

    def _dispatch_to_subscribers(self, event: RuntimeEvent) -> None:
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.ensure_future(result)
                    except RuntimeError:
                        pass
            except Exception as exc:
                logger.error(f"[Topology] Handler {handler.__name__} raised exception on {event_type.__name__}: {exc}")

    def subscribe(self, event_type: type, handler: Callable) -> None:
        if not issubclass(event_type, RuntimeEvent):
            raise TypeError("event_type must be a subclass of RuntimeEvent")
        with self._log_lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def get_causal_lineage(self, event_id: str) -> List[RuntimeEvent]:
        with self._log_lock:
            history = []
            current_id = event_id
            while current_id:
                ev = next((e for e in self._event_log if e.event_id == current_id), None)
                if not ev:
                    break
                history.append(ev)
                current_id = ev.parent_event_id
            return history[::-1]

    def clear_log(self) -> None:
        with self._log_lock:
            self._event_log.clear()

# Singleton accessor (Legacy support)
_topology: Optional[RuntimeEventTopologyCoordinator] = None

def get_event_bus(memory_system=None) -> RuntimeEventTopologyCoordinator:
    global _topology
    if _topology is None:
        _topology = RuntimeEventTopologyCoordinator(memory_system=memory_system)
    return _topology