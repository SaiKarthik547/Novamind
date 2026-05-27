"""
core/orchestration/event_bus.py

Phase 15/16: Runtime Event Topology Coordinator
Transitions the architecture from "direct-call coordinated" to "event-topology coordinated".

WARNING: Do NOT let this become KernelFacade v2.
This class is exclusively a routing + synchronization authority.
It does NOT own execution, it does NOT own lifecycles, it only routes their consequences.
"""

import asyncio
import logging
import threading
from typing import Callable, List, Optional, Dict

from core.contracts.runtime_events import (
    RuntimeEvent, LifecycleEvent, ExecutionEvent, 
    VerificationEvent, SchedulerEvent, TelemetryEvent
)
from core.execution.execution_scheduler import ExecutionScheduler

logger = logging.getLogger("RuntimeEventTopology")

class RuntimeEventTopologyCoordinator:
    """
    Thread-safe synchronization and routing authority.
    Only accepts strongly-typed RuntimeEvent subclasses.
    """

    def __init__(self, scheduler: Optional[ExecutionScheduler] = None, memory_system=None):
        self._subscribers: Dict[type, List[Callable]] = {}
        self._event_log: List[RuntimeEvent] = []
        self._memory = memory_system
        self._scheduler = scheduler
        
        self._log_lock = threading.Lock()
        self._verification_lock = threading.Lock() # Sequential verification routing guarantee

    def set_scheduler(self, scheduler: ExecutionScheduler) -> None:
        """Inject the scheduler to allow closed-loop convergence routing."""
        self._scheduler = scheduler

    def emit_sync(self, event: RuntimeEvent) -> None:
        """
        Synchronous topological routing. 
        """
        if not isinstance(event, RuntimeEvent):
            logger.error("[Topology] Rejected untyped event emission. Must be a RuntimeEvent.")
            return

        # 1. Topological Guarantees & Closed-Loop Routing
        self._enforce_topology_rules(event)

        # 2. Sequential Guarantee for Verification
        if isinstance(event, VerificationEvent):
            with self._verification_lock:
                self._dispatch_to_subscribers(event)
        else:
            self._dispatch_to_subscribers(event)

        # 3. Memory/Replay Persistence (Transitional, still in-memory for now)
        with self._log_lock:
            if len(self._event_log) > 5000:
                self._event_log.pop(0)
            self._event_log.append(event)

        # Legacy telemetry fallback
        if self._memory and isinstance(event, TelemetryEvent):
            try:
                self._memory.log_system_event(
                    "TELEMETRY",
                    details=event.message,
                    severity=event.severity
                )
            except Exception as e:
                logger.debug(f"[Topology] Memory logging failed: {e}")

    async def emit(self, event: RuntimeEvent) -> None:
        """Async wrapper."""
        # For now, map to sync to maintain sequential strictness in the topology
        self.emit_sync(event)

    def _enforce_topology_rules(self, event: RuntimeEvent) -> None:
        """
        Explicit Scheduler Feedback Loop.
        This is where the topology reacts to its own failures.
        """
        if isinstance(event, LifecycleEvent) and event.is_dead:
            if self._scheduler:
                logger.warning(f"[Topology] HWND {event.hwnd} died. Routing ABORT to Scheduler.")
                # We could directly call the scheduler, but for pure event architecture, 
                # we just emit a secondary SchedulerEvent which the scheduler would be subscribed to.
                abort_event = SchedulerEvent(
                    parent_event_id=event.event_id,
                    action="QUEUE_ABORT",
                    target_queue_id=str(event.hwnd),
                    reason="Lifecycle Invalidated (Dead Handle)"
                )
                self.emit_sync(abort_event)

    def _dispatch_to_subscribers(self, event: RuntimeEvent) -> None:
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        
        for handler in handlers:
            try:
                result = handler(event)
                # If the handler is an async coroutine, we schedule it fire-and-forget
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.ensure_future(result)
                    except RuntimeError:
                        # No running loop in this thread
                        pass
            except Exception as exc:
                logger.error(f"[Topology] Handler {handler.__name__} raised exception on {event_type.__name__}: {exc}")

    def subscribe(self, event_type: type, handler: Callable) -> None:
        if not issubclass(event_type, RuntimeEvent):
            raise TypeError("event_type must be a subclass of RuntimeEvent")
        with self._log_lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def get_causal_lineage(self, event_id: str) -> List[RuntimeEvent]:
        """Reconstructs the execution history for a given event ID."""
        with self._log_lock:
            # Naive lookup for foundational phase
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
    elif memory_system and _topology._memory is None:
        _topology._memory = memory_system
    return _topology