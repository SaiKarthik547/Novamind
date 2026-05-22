"""
tests/test_async_concurrency.py

Phase 7 — Concurrency Stress Tests for SnapshotBarrier and CausalScheduler.

Tests:
  1. Mutation gate correctly blocks writers when a snapshot is active
  2. Read-only observers are never blocked by the snapshot barrier
  3. 100 concurrent mutations — zero state tearing after barrier completes
  4. Epoch advances exactly once per snapshot cycle
  5. CausalScheduler dispatches events in logical clock order
  6. CausalScheduler respects many-to-many dependencies
  7. Deadlock detection fires when circular dependencies exist
"""

import asyncio
import pytest
import uuid

from core.sync.synchronization import LogicalClock, EpochManager, SnapshotBarrier
from core.orchestration.causal_scheduler import CausalScheduler


# ── 1. LogicalClock ───────────────────────────────────────────────────────────

class TestLogicalClock:

    def test_initial_value_is_zero(self):
        clock = LogicalClock()
        assert clock.value == 0

    def test_tick_increments(self):
        clock = LogicalClock()
        v1 = clock.tick()
        v2 = clock.tick()
        assert v1 == 1
        assert v2 == 2

    def test_update_lamport_rule(self):
        """max(local, received) + 1"""
        clock = LogicalClock()
        clock.tick()        # local = 1
        v = clock.update(5) # max(1, 5) + 1 = 6
        assert v == 6

    def test_update_no_op_when_local_ahead(self):
        clock = LogicalClock()
        for _ in range(10):
            clock.tick()    # local = 10
        v = clock.update(3) # max(10, 3) + 1 = 11
        assert v == 11

    def test_snapshot_is_non_mutating(self):
        clock = LogicalClock()
        clock.tick()
        s = clock.snapshot()
        assert s == 1
        assert clock.value == 1  # no change


# ── 2. EpochManager ───────────────────────────────────────────────────────────

class TestEpochManager:

    def test_starts_at_zero(self):
        em = EpochManager()
        assert em.current == 0

    def test_advance_increments(self):
        em = EpochManager()
        new_epoch = em.advance()
        assert new_epoch == 1
        assert em.current == 1

    def test_sealed_history_recorded(self):
        em = EpochManager()
        em.advance()
        em.advance()
        history = em.get_sealed_history()
        assert len(history) == 2
        assert history[0]["sealed_epoch"] == 0
        assert history[1]["sealed_epoch"] == 1


# ── 3. SnapshotBarrier — mutation gate ───────────────────────────────────────

class TestSnapshotBarrier:

    @pytest.mark.asyncio
    async def test_mutations_complete_before_barrier_seals(self):
        """
        Barrier should NOT seal until all in-flight mutations complete.
        We launch a mutation that takes a brief moment, then trigger a snapshot.
        The snapshot must wait for the mutation to finish.
        """
        barrier = SnapshotBarrier()
        em = EpochManager()
        mutation_completed = False

        async def slow_mutation():
            nonlocal mutation_completed
            async with barrier.mutation_window():
                await asyncio.sleep(0.05)  # simulate work
                mutation_completed = True

        async def do_snapshot():
            async with barrier.snapshot_window(em):
                # By the time we reach here, mutation must be complete
                assert mutation_completed, "Snapshot sealed before mutation finished!"

        # Launch mutation, then snapshot concurrently
        await asyncio.gather(slow_mutation(), do_snapshot())
        assert mutation_completed

    @pytest.mark.asyncio
    async def test_new_mutations_blocked_during_snapshot(self):
        """
        Once a snapshot freeze is requested, new mutations must wait until
        the snapshot exits.

        Correct structure: snapshot and late mutation run concurrently via
        asyncio.gather(). An asyncio.Event is used for precise coordination:
          1. Snapshot signals 'frozen' once it's inside the barrier.
          2. Mutation attempts to enter — is blocked because freeze=True.
          3. Snapshot sleeps briefly, then exits.
          4. Mutation proceeds and sets the flag.
        """
        barrier = SnapshotBarrier()
        em = EpochManager()
        frozen_event = asyncio.Event()
        mutation_ran = asyncio.Event()
        mutation_entered_while_frozen = False

        async def do_snapshot():
            async with barrier.snapshot_window(em):
                frozen_event.set()          # signal: barrier is now active
                await asyncio.sleep(0.08)   # hold barrier briefly
                # At this point mutation must NOT have run yet
                assert not mutation_ran.is_set(), \
                    "Mutation slipped through active snapshot barrier!"

        async def late_mutation():
            await frozen_event.wait()       # wait until snapshot is frozen
            # This must block until snapshot exits
            async with barrier.mutation_window():
                mutation_ran.set()

        await asyncio.gather(do_snapshot(), late_mutation())
        assert mutation_ran.is_set(), "Mutation never ran after barrier released"

    @pytest.mark.asyncio
    async def test_epoch_advances_after_snapshot(self):
        """Epoch must advance exactly once per successful snapshot."""
        barrier = SnapshotBarrier()
        em = EpochManager()
        assert em.current == 0

        async with barrier.snapshot_window(em):
            pass  # snapshot body

        assert em.current == 1  # advanced exactly once

    @pytest.mark.asyncio
    async def test_epoch_does_not_advance_on_abort(self):
        """If an exception occurs inside the snapshot window, epoch must NOT advance."""
        barrier = SnapshotBarrier()
        em = EpochManager()

        with pytest.raises(RuntimeError):
            async with barrier.snapshot_window(em):
                raise RuntimeError("Simulated snapshot failure")

        assert em.current == 0  # no advance on error

    @pytest.mark.asyncio
    async def test_100_concurrent_mutations_no_tearing(self):
        """
        Launch 100 concurrent mutations. After a snapshot completes,
        verify the mutation counter is internally consistent (no half-counts).
        """
        barrier = SnapshotBarrier()
        em = EpochManager()
        mutation_log = []

        async def mutate(i: int):
            async with barrier.mutation_window():
                await asyncio.sleep(0)      # yield to simulate async work
                mutation_log.append(i)

        # Launch 100 mutations and one snapshot concurrently
        async def snapshot():
            await asyncio.sleep(0.01)       # let some mutations start
            async with barrier.snapshot_window(em):
                # The snapshot must observe a consistent in_flight count of zero
                assert barrier._mutation_count == 0, \
                    f"State tearing! {barrier._mutation_count} in-flight during snapshot"

        tasks = [mutate(i) for i in range(100)]
        await asyncio.gather(*tasks, snapshot())

        assert len(set(mutation_log)) == 100  # all mutations completed, no duplicates


# ── 4. CausalScheduler ───────────────────────────────────────────────────────

class TestCausalScheduler:

    @pytest.mark.asyncio
    async def test_events_dispatched_in_clock_order(self):
        """
        When two events have no dependency between them, they must be
        dispatched in ascending logical clock order.
        """
        dispatched = []

        def collect(payload):
            dispatched.append(payload["id"])

        scheduler = CausalScheduler(dispatch_fn=collect)
        scheduler.submit("b", {"id": "b"}, logical_clock=5)
        scheduler.submit("a", {"id": "a"}, logical_clock=2)
        scheduler.submit("c", {"id": "c"}, logical_clock=8)

        await scheduler.run_until_empty()
        assert dispatched == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_single_parent_dependency_respected(self):
        """Child must not be dispatched before its parent."""
        dispatched = []

        def collect(payload):
            dispatched.append(payload["id"])

        scheduler = CausalScheduler(dispatch_fn=collect)
        scheduler.submit("child", {"id": "child"}, causal_parents=["parent"], logical_clock=1)
        scheduler.submit("parent", {"id": "parent"}, causal_parents=[], logical_clock=2)

        await scheduler.run_until_empty()
        # parent dispatched before child despite higher clock
        assert dispatched.index("parent") < dispatched.index("child")

    @pytest.mark.asyncio
    async def test_many_to_many_dependencies(self):
        """An event with two parents must wait for BOTH parents."""
        dispatched = []

        def collect(payload):
            dispatched.append(payload["id"])

        scheduler = CausalScheduler(dispatch_fn=collect)
        scheduler.submit("p1", {"id": "p1"}, logical_clock=1)
        scheduler.submit("p2", {"id": "p2"}, logical_clock=2)
        # child depends on BOTH p1 and p2
        scheduler.submit("child", {"id": "child"}, causal_parents=["p1", "p2"], logical_clock=3)

        await scheduler.run_until_empty()
        p1_idx = dispatched.index("p1")
        p2_idx = dispatched.index("p2")
        child_idx = dispatched.index("child")
        assert child_idx > p1_idx
        assert child_idx > p2_idx

    @pytest.mark.asyncio
    async def test_deadlock_resolution_does_not_hang(self):
        """
        If events have circular dependencies (A→B, B→A), the scheduler
        must detect and resolve without hanging.
        """
        dispatched = []

        def collect(payload):
            dispatched.append(payload["id"])

        scheduler = CausalScheduler(dispatch_fn=collect)
        scheduler.submit("a", {"id": "a"}, causal_parents=["b"], logical_clock=1)
        scheduler.submit("b", {"id": "b"}, causal_parents=["a"], logical_clock=2)

        # Must complete without hanging (deadlock resolution fires)
        await asyncio.wait_for(scheduler.run_until_empty(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_scheduler_trace_populated(self):
        """Trace log must record every scheduler decision."""
        dispatched = []

        def collect(payload):
            dispatched.append(payload["id"])

        scheduler = CausalScheduler(dispatch_fn=collect)
        scheduler.submit("x", {"id": "x"}, logical_clock=1)
        await scheduler.run_until_empty()

        trace = scheduler.get_trace()
        assert len(trace) >= 2  # at least "submitted" + "dispatched"
        actions = {e["action"] for e in trace}
        assert "submitted" in actions
        assert "dispatched" in actions
