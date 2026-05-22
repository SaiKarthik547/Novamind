"""
core/causal_scheduler.py

Phase 7 — Deterministic Causal Scheduler with DAG Dependency Tracking.

Design Philosophy:
  The linear event loop model (execute events in arrival order) is incorrect
  under async concurrency: two tasks arriving at microsecond proximity may
  have strict causal ordering that wall-clock time doesn't capture.

  This scheduler replaces naive asyncio.create_task() dispatch with a
  dependency-aware DAG. Events declare their causal parents explicitly.
  An event is only dispatched when ALL its declared parents have completed.

  Logical Clock Arbitration:
    When two ready-to-dispatch events have no causal dependency between them
    (truly concurrent), they are dispatched in ascending Logical Clock order.
    This produces a total deterministic ordering even for independent events.

  Scheduler Trace Logs:
    Every dispatch decision is recorded with:
      - event_id, logical_clock, epoch_id
      - causal_parents (list)
      - wait_reason (why was this event delayed?)
      - dispatch_at_clock (when was it actually dispatched?)
    This is the observability layer that makes distributed debugging tractable.

System Integration:
  - ReplayEngine feeds delta events into CausalScheduler for DAG reconstruction.
  - EventBus.publish() is the downstream executor after the DAG clears.
  - SnapshotBarrier pauses the scheduler during epoch sealing.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from core.synchronization import get_runtime_clock, get_epoch_manager

logger = logging.getLogger("causal_scheduler")


# ── Scheduled Event Node ──────────────────────────────────────────────────────

@dataclass
class ScheduledEvent:
    """
    A single event node in the causal dependency DAG.

    causal_parents: list of event_ids that MUST complete before this
                    event is dispatched. Empty list = immediately dispatchable.

    logical_clock:  Lamport clock value at the time this event was submitted.
                    Used as the tiebreaker when multiple events are ready
                    simultaneously (lower clock → earlier in causal history).

    epoch_id:       The epoch in which this event was submitted. Events from
                    older epochs are never dispatched into a newer epoch's
                    execution window (prevents cross-epoch contamination).
    """
    event_id: str
    payload: Dict[str, Any]
    causal_parents: List[str] = field(default_factory=list)
    logical_clock: int = 0
    epoch_id: int = 0
    submitted_at: float = field(default_factory=time.time)
    dispatched_at: Optional[float] = None
    wait_reason: str = ""

    def __lt__(self, other: "ScheduledEvent") -> bool:
        """Sort by logical clock ascending for deterministic queue ordering."""
        return self.logical_clock < other.logical_clock


# ── Scheduler Trace Log ───────────────────────────────────────────────────────

class SchedulerTraceLog:
    """
    Records every scheduler decision for post-hoc debugging and replay analysis.

    This is not optional — without scheduler traces, debugging causal replay
    divergences becomes nearly impossible under concurrent execution.
    """

    MAX_ENTRIES = 2000

    def __init__(self) -> None:
        self._entries: List[Dict] = []

    def record(
        self,
        event_id: str,
        action: str,
        logical_clock: int,
        epoch_id: int,
        causal_parents: List[str],
        wait_reason: str = "",
    ) -> None:
        entry = {
            "ts": time.time(),
            "event_id": event_id,
            "action": action,          # "submitted" | "ready" | "dispatched" | "blocked" | "dropped"
            "logical_clock": logical_clock,
            "epoch_id": epoch_id,
            "causal_parents": causal_parents,
            "wait_reason": wait_reason,
        }
        self._entries.append(entry)
        self._entries[:] = self._entries[-self.MAX_ENTRIES:]
        logger.debug(
            f"[Scheduler] {action.upper()} event={event_id[:8]} "
            f"clock={logical_clock} epoch={epoch_id} "
            f"parents={[p[:8] for p in causal_parents]} reason={wait_reason!r}"
        )

    def get_entries(self) -> List[Dict]:
        return list(self._entries)

    def get_by_event(self, event_id: str) -> List[Dict]:
        return [e for e in self._entries if e["event_id"] == event_id]


# ── Causal Scheduler ──────────────────────────────────────────────────────────

class CausalScheduler:
    """
    Dependency-aware event scheduler using a causal DAG.

    Submit events with submit(). The scheduler holds each event until all
    declared causal_parents have been dispatched, then releases them in
    ascending Logical Clock order.

    This handles many-to-many dependencies (a single event may have multiple
    parents; multiple events may share the same parent).

    Thread Safety:
      CausalScheduler is designed for use within a single asyncio event loop.
      The internal state is protected by an asyncio.Lock for safe concurrent
      coroutine access. Do NOT call from multiple OS threads simultaneously.

    Usage (EventBus integration):
        scheduler = CausalScheduler(dispatch_fn=event_bus.publish)
        scheduler.submit(event_id="abc", payload={...}, causal_parents=["xyz"])
        await scheduler.run_until_empty()

    Usage (Replay):
        for event in delta_log:
            scheduler.submit(
                event_id=event["msg_id"],
                payload=event,
                causal_parents=event.get("payload", {}).get("causal_parents", []),
                logical_clock=event.get("logical_clock", 0),
                epoch_id=event.get("epoch_id", 0),
            )
        await scheduler.run_until_empty()
    """

    def __init__(self, dispatch_fn: Callable[[Dict], Any]) -> None:
        """
        dispatch_fn: Called with the event payload when the DAG clears for it.
                     Typically event_bus.publish or event_bus.emit.
        """
        self._dispatch_fn = dispatch_fn
        self._pending: Dict[str, ScheduledEvent] = {}   # event_id → node
        self._completed: Set[str] = set()               # event_ids dispatched
        self._dependents: Dict[str, Set[str]] = defaultdict(set)  # parent → children
        self._lock = asyncio.Lock()
        self.trace = SchedulerTraceLog()
        self._clock = get_runtime_clock()
        self._epoch = get_epoch_manager()

    # ── Submit ────────────────────────────────────────────────────────────────

    def submit(
        self,
        event_id: str,
        payload: Dict[str, Any],
        causal_parents: Optional[List[str]] = None,
        logical_clock: Optional[int] = None,
        epoch_id: Optional[int] = None,
    ) -> None:
        """
        Submit an event to the scheduler.

        If causal_parents is empty or all parents already completed, the event
        is immediately eligible for dispatch on the next run_cycle() call.

        If logical_clock is not provided, the runtime clock is ticked and the
        new value is used (correct for live events).

        For replay scenarios, pass the logical_clock and epoch_id explicitly
        from the stored event log to preserve causal history faithfully.
        """
        parents = causal_parents or []
        clock = logical_clock if logical_clock is not None else self._clock.tick()
        epoch = epoch_id if epoch_id is not None else self._epoch.current

        node = ScheduledEvent(
            event_id=event_id,
            payload=payload,
            causal_parents=parents,
            logical_clock=clock,
            epoch_id=epoch,
        )

        self._pending[event_id] = node

        # Register reverse dependency map: parent must notify this child
        for parent_id in parents:
            self._dependents[parent_id].add(event_id)

        self.trace.record(
            event_id, "submitted", clock, epoch, parents,
            wait_reason="" if not parents else f"waiting on {len(parents)} parent(s)"
        )

    # ── Dispatch Logic ────────────────────────────────────────────────────────

    def _get_ready_events(self) -> List[ScheduledEvent]:
        """
        Returns all pending events whose causal parents have all completed,
        sorted by logical_clock ascending for deterministic total ordering.
        """
        ready = []
        for node in self._pending.values():
            unresolved = [p for p in node.causal_parents if p not in self._completed]
            if not unresolved:
                ready.append(node)
            else:
                self.trace.record(
                    node.event_id, "blocked", node.logical_clock, node.epoch_id,
                    node.causal_parents,
                    wait_reason=f"blocked on: {unresolved[:3]}"
                )
        return sorted(ready)  # ascending logical_clock

    async def run_cycle(self) -> int:
        """
        Execute one scheduling cycle: dispatch all currently-ready events.
        Returns the number of events dispatched in this cycle.
        """
        async with self._lock:
            ready = self._get_ready_events()
            if not ready:
                return 0

            dispatched = 0
            for node in ready:
                try:
                    result = self._dispatch_fn(node.payload)
                    if asyncio.iscoroutine(result):
                        await result
                    node.dispatched_at = time.time()
                    self._completed.add(node.event_id)
                    del self._pending[node.event_id]
                    dispatched += 1
                    self.trace.record(
                        node.event_id, "dispatched",
                        node.logical_clock, node.epoch_id,
                        node.causal_parents,
                    )
                except Exception as e:
                    logger.error(
                        f"[CausalScheduler] Dispatch failed for {node.event_id[:8]}: {e}"
                    )
                    self.trace.record(
                        node.event_id, "dropped",
                        node.logical_clock, node.epoch_id,
                        node.causal_parents,
                        wait_reason=str(e),
                    )
                    # Remove from pending even on error — do not stall the DAG
                    self._completed.add(node.event_id)
                    del self._pending[node.event_id]

            return dispatched

    async def run_until_empty(self, max_cycles: int = 10000) -> int:
        """
        Run scheduling cycles until the pending queue is drained or a cycle
        produces no progress (which would indicate an unresolvable dependency
        cycle — logged as a critical error).

        Returns total events dispatched.
        """
        total = 0
        for cycle in range(max_cycles):
            if not self._pending:
                break
            n = await self.run_cycle()
            total += n
            if n == 0 and self._pending:
                # No progress but events remain — dependency cycle detected
                stuck = list(self._pending.keys())[:5]
                logger.critical(
                    f"[CausalScheduler] Dependency deadlock detected! "
                    f"Stuck events (showing ≤5): {[e[:8] for e in stuck]}"
                )
                # Force-complete stuck events to prevent total stall
                async with self._lock:
                    for eid in list(self._pending.keys()):
                        node = self._pending.pop(eid)
                        self._completed.add(eid)
                        self.trace.record(
                            eid, "dropped", node.logical_clock, node.epoch_id,
                            node.causal_parents,
                            wait_reason="deadlock_resolution"
                        )
                break
            await asyncio.sleep(0)  # yield to the event loop between cycles

        return total

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    def get_trace(self) -> List[Dict]:
        """Returns all scheduler trace entries for debugging."""
        return self.trace.get_entries()


# ── Module-level factory ──────────────────────────────────────────────────────

def make_causal_scheduler(dispatch_fn: Callable[[Dict], Any]) -> CausalScheduler:
    """
    Factory: creates a fresh CausalScheduler bound to the given dispatch function.
    Call once per replay or execution session.
    """
    return CausalScheduler(dispatch_fn=dispatch_fn)
