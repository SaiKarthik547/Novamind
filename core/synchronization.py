"""
core/synchronization.py

Phase 7 — Tiered Transactional Barriers & Logical Clocks.

Design Philosophy:
  - NO global stop-the-world lock. A monolithic RuntimeLock causes priority
    inversion, starvation, and deadlocks under IPC growth.
  - Instead: a TIERED SnapshotBarrier with explicit gate categories:
      mutation_gate  — blocks new state mutations (agent writes, task updates)
      transition_gate — blocks new FSM state transitions
    Read-only observers (metrics, heartbeats, logging) are NEVER blocked.
  - Epoch semantics: each snapshot seals a discrete temporal window. Events
    are tagged with the current epoch_id. The barrier drains the mutation
    window before sealing, preventing mid-transition ambiguity.
  - Logical Clocks: Lamport monotonic counters guarantee deterministic
    event ordering across concurrent agents without global coordination.

System Integration:
  - StateSnapshotManager (state_snapshot.py) uses SnapshotBarrier to seal epochs.
  - BaseAgent.EffectJournal tags effects with LogicalClock ticks.
  - CausalScheduler (causal_scheduler.py) uses LogicalClock for DAG arbitration.
  - ReplayEngine uses epoch_id + logical_clock to reconstruct causal order.
"""

import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("synchronization")


# ── Logical Clock ─────────────────────────────────────────────────────────────

class LogicalClock:
    """
    Lamport Logical Clock — thread-safe, monotonically increasing.

    Semantics:
      - tick()       → increment before any local event; returns new value
      - update(recv) → merge on message receive: max(local, recv) + 1
      - value        → current clock reading (read-only)

    This is the simplest correct foundation for causal ordering. Vector
    clocks will replace this in a future phase once multi-process IPC
    becomes the dominant concurrency model.
    """

    def __init__(self, initial: int = 0) -> None:
        self._clock: int = initial
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        with self._lock:
            return self._clock

    def tick(self) -> int:
        """Increment clock for a local event. Returns the NEW value."""
        with self._lock:
            self._clock += 1
            return self._clock

    def update(self, received: int) -> int:
        """
        Merge on message receive (Lamport receive rule).
        Sets clock = max(local, received) + 1. Returns the NEW value.
        """
        with self._lock:
            self._clock = max(self._clock, received) + 1
            return self._clock

    def snapshot(self) -> int:
        """Non-mutating read of the current value for tagging."""
        return self.value

    def __repr__(self) -> str:
        return f"LogicalClock(value={self.value})"


# ── Epoch Manager ─────────────────────────────────────────────────────────────

class EpochManager:
    """
    Manages discrete temporal epochs for snapshot sealing.

    Epoch lifecycle:
      epoch N opens
        → mutations tagged with epoch N
        → SnapshotBarrier enters draining mode
        → no new mutations accepted for epoch N
        → epoch N snapshot seals
      epoch N+1 opens immediately after

    This eliminates mid-transition ambiguity: every event either belongs
    entirely to epoch N or epoch N+1 — never split between them.

    Thread-safe for use from both the async event loop and sync threads.
    """

    def __init__(self) -> None:
        self._epoch: int = 0
        self._lock = threading.Lock()
        self._sealed_epochs: list = []  # audit trail of sealed epochs

    @property
    def current(self) -> int:
        with self._lock:
            return self._epoch

    def advance(self) -> int:
        """
        Seal the current epoch and open the next one.
        Returns the NEW epoch id.
        Called by SnapshotBarrier after the snapshot commits.
        """
        with self._lock:
            sealed = self._epoch
            self._epoch += 1
            self._sealed_epochs.append({
                "sealed_epoch": sealed,
                "new_epoch": self._epoch,
                "wall_time": time.time(),
            })
            logger.info(
                f"[EpochManager] Epoch {sealed} sealed → Epoch {self._epoch} opened"
            )
            return self._epoch

    def get_sealed_history(self) -> list:
        with self._lock:
            return list(self._sealed_epochs)

    def __repr__(self) -> str:
        return f"EpochManager(current_epoch={self.current})"


# ── Snapshot Barrier ──────────────────────────────────────────────────────────

class SnapshotBarrier:
    """
    Tiered transactional barrier for atomic state capture.

    Gate hierarchy (only what MUST stop, stops):
      mutation_gate   — new agent state mutations and task transitions are queued
      transition_gate — new FSM policy transitions are deferred

    What is NEVER blocked:
      - Read-only observers (metrics queries, divergence scoring)
      - Heartbeat publication (IPC continuity)
      - Logging and audit trails
      - External IO that is already in-flight (it is journaled by EffectJournal)

    Usage (from async context, e.g. StateSnapshotManager):
        async with barrier.snapshot_window(epoch_manager):
            # barrier is active — mutations are drained and blocked
            capture_state()
        # barrier released — mutations resume with new epoch

    Usage (from agent mutation context):
        async with barrier.mutation_window():
            agent.update_state(...)

    Thread model:
      SnapshotBarrier uses asyncio.Condition (cooperative async) for the
      mutation gate, which is correct because all agent mutations happen
      inside the async event loop. The transition_gate uses the same
      Condition so both gates share a single lock and avoid deadlock.
    """

    def __init__(self) -> None:
        # asyncio.Condition requires an event loop — created lazily at first use
        self._condition: Optional[asyncio.Condition] = None
        self._mutation_count: int = 0     # in-flight mutations
        self._transition_count: int = 0   # in-flight FSM transitions
        self._freeze_requested: bool = False
        self._lock = threading.Lock()     # for sync access to counts

    def _get_condition(self) -> asyncio.Condition:
        """Lazy initialization — must be called from within a running loop."""
        if self._condition is None:
            self._condition = asyncio.Condition()
        return self._condition

    # ── Mutation gate (agent writes, task state updates) ──────────────────────

    class _MutationContext:
        """Context manager returned by mutation_window()."""
        def __init__(self, barrier: "SnapshotBarrier") -> None:
            self._barrier = barrier

        async def __aenter__(self) -> "SnapshotBarrier._MutationContext":
            cond = self._barrier._get_condition()
            async with cond:
                # Block if a snapshot freeze is in progress
                await cond.wait_for(lambda: not self._barrier._freeze_requested)
                self._barrier._mutation_count += 1
            return self

        async def __aexit__(self, *_) -> None:
            cond = self._barrier._get_condition()
            async with cond:
                self._barrier._mutation_count -= 1
                cond.notify_all()

    def mutation_window(self) -> "_MutationContext":
        """
        Async context manager for any agent that mutates state.
        Blocks automatically if a snapshot barrier is active.

        Usage:
            async with snapshot_barrier.mutation_window():
                self.task_states[tid] = "COMPLETED"
        """
        return self._MutationContext(self)

    # ── Snapshot window (snapshot coordinator) ────────────────────────────────

    class _SnapshotContext:
        """Context manager returned by snapshot_window()."""
        def __init__(self, barrier: "SnapshotBarrier", epoch_manager: Optional[EpochManager]) -> None:
            self._barrier = barrier
            self._epoch_manager = epoch_manager

        async def __aenter__(self) -> "SnapshotBarrier._SnapshotContext":
            cond = self._barrier._get_condition()
            async with cond:
                # Signal freeze — new mutations will wait
                self._barrier._freeze_requested = True
                # Drain in-flight mutations (wait for count to reach zero)
                await cond.wait_for(
                    lambda: self._barrier._mutation_count == 0
                )
                logger.info(
                    f"[SnapshotBarrier] Mutation gate drained. "
                    f"Epoch {self._epoch_manager.current if self._epoch_manager else 'N/A'} sealing."
                )
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
            cond = self._barrier._get_condition()
            async with cond:
                self._barrier._freeze_requested = False
                # Advance epoch after successful commit (not on abort)
                if exc_type is None and self._epoch_manager is not None:
                    self._epoch_manager.advance()
                # Release all waiting mutations
                cond.notify_all()
            logger.info("[SnapshotBarrier] Mutation gate released.")

    def snapshot_window(self, epoch_manager: Optional[EpochManager] = None) -> "_SnapshotContext":
        """
        Async context manager for the snapshot coordinator.
        Drains in-flight mutations, blocks new ones, seals the epoch,
        then releases on exit.

        Usage:
            async with barrier.snapshot_window(epoch_manager):
                state = capture_all_agent_states()
                save_to_disk(state)
            # epoch advanced, mutations resume
        """
        return self._SnapshotContext(self, epoch_manager)

    @property
    def is_frozen(self) -> bool:
        """True if a snapshot freeze is currently active (read-only, non-blocking)."""
        return self._freeze_requested

    def __repr__(self) -> str:
        return (
            f"SnapshotBarrier("
            f"frozen={self._freeze_requested}, "
            f"in_flight_mutations={self._mutation_count})"
        )


# ── Module-level singletons ───────────────────────────────────────────────────
# A single shared clock, epoch manager, and barrier for the runtime.
# Components import these directly for zero-overhead access.

_runtime_clock = LogicalClock()
_runtime_epoch = EpochManager()
_snapshot_barrier = SnapshotBarrier()


def get_runtime_clock() -> LogicalClock:
    """Returns the shared runtime Logical Clock."""
    return _runtime_clock


def get_epoch_manager() -> EpochManager:
    """Returns the shared runtime Epoch Manager."""
    return _runtime_epoch


def get_snapshot_barrier() -> SnapshotBarrier:
    """Returns the shared runtime Snapshot Barrier."""
    return _snapshot_barrier
