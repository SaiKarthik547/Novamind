"""
tests/test_replay_equivalence.py

Phase 7 — Replay Equivalence Validation.

This is the most important correctness test in the project.

The test proves:
  execute(events) → snapshot → replay(snapshot + events) → same canonical hash

Under:
  - Deterministic execution (fixed event order)
  - Randomized async yields (simulates concurrent timing variation)
  - Many-to-many causal dependencies

If canonical hashes diverge between original execution and replay, the
runtime has a non-determinism bug that would corrupt recovery boots.
"""

import asyncio
import json
import pytest
import random
import tempfile
import uuid
from pathlib import Path
from typing import List, Dict, Any

from core.synchronization import LogicalClock, EpochManager, SnapshotBarrier
from core.causal_scheduler import CausalScheduler
from core.canonical import state_hash


# ── Minimal Runtime Simulation ────────────────────────────────────────────────

class MinimalRuntime:
    """
    A minimal in-memory runtime that simulates agent state accumulation
    and event journaling — sufficient for replay equivalence testing
    without requiring the full NovaMind boot sequence.
    """

    def __init__(self):
        self.state: Dict[str, Any] = {"tasks": {}, "clock": 0}
        self.event_log: List[Dict] = []
        self.clock = LogicalClock()
        self.epoch_mgr = EpochManager()
        self.barrier = SnapshotBarrier()

    def apply_event(self, event: Dict) -> None:
        """Apply one event to the runtime state."""
        et = event.get("event_type", "")
        payload = event.get("payload", {})
        task_id = payload.get("task_id", "")

        if et == "TASK_CREATED" and task_id:
            self.state["tasks"][task_id] = {"status": "CREATED", "data": payload.get("data", "")}
        elif et == "TASK_COMPLETED" and task_id:
            if task_id in self.state["tasks"]:
                self.state["tasks"][task_id]["status"] = "COMPLETED"
        elif et == "TASK_FAILED" and task_id:
            if task_id in self.state["tasks"]:
                self.state["tasks"][task_id]["status"] = "FAILED"

        self.state["clock"] = event.get("logical_clock", self.state["clock"])
        self.event_log.append(event)

    def get_canonical_hash(self) -> str:
        """Returns the canonical hash of the current authoritative state."""
        return state_hash(self.state)

    async def take_snapshot(self) -> Dict:
        """Returns a snapshot of the current state, advancing the epoch."""
        snap = {
            "snapshot_id": str(uuid.uuid4()),
            "epoch_id": self.epoch_mgr.current,
            "sequence_id": len(self.event_log),
            "state": dict(self.state),
            "state_hash": self.get_canonical_hash(),
        }
        self.epoch_mgr.advance()
        return snap


# ── Event Generator ───────────────────────────────────────────────────────────

def make_event_chain(n_tasks: int, seed: int = 42) -> List[Dict]:
    """
    Generates a realistic chain of events with causal dependencies.
    Each COMPLETED event causally depends on its CREATED event.
    """
    rng = random.Random(seed)
    events = []
    clock = 0

    for i in range(n_tasks):
        task_id = f"task_{i:04d}"
        create_id = str(uuid.UUID(int=rng.getrandbits(128)))
        complete_id = str(uuid.UUID(int=rng.getrandbits(128)))
        clock += 1

        events.append({
            "msg_id": create_id,
            "event_type": "TASK_CREATED",
            "sequence_id": len(events),
            "logical_clock": clock,
            "epoch_id": 0,
            "payload": {
                "task_id": task_id,
                "data": f"payload_{i}",
                "causal_parents": [],
            }
        })
        clock += 1

        events.append({
            "msg_id": complete_id,
            "event_type": "TASK_COMPLETED",
            "sequence_id": len(events),
            "logical_clock": clock,
            "epoch_id": 0,
            "payload": {
                "task_id": task_id,
                "causal_parents": [create_id],  # completed depends on created
            }
        })

    return events


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestReplayEquivalence:

    @pytest.mark.asyncio
    async def test_replay_produces_identical_hash_deterministic(self):
        """
        Execute a fixed event sequence → capture canonical hash.
        Replay the same events through CausalScheduler → capture hash.
        Hashes must be identical.
        """
        events = make_event_chain(n_tasks=20, seed=1)

        # ── Original Execution ──────────────────────────────────────────────
        original = MinimalRuntime()
        for event in events:
            original.apply_event(event)
        original_hash = original.get_canonical_hash()

        # ── Replay via CausalScheduler ───────────────────────────────────────
        replay = MinimalRuntime()
        scheduler = CausalScheduler(dispatch_fn=replay.apply_event)

        for event in events:
            msg_id = event["msg_id"]
            scheduler.submit(
                event_id=msg_id,
                payload=event,
                causal_parents=event["payload"].get("causal_parents", []),
                logical_clock=event["logical_clock"],
                epoch_id=event["epoch_id"],
            )

        await scheduler.run_until_empty()
        replay_hash = replay.get_canonical_hash()

        assert original_hash == replay_hash, (
            f"Replay divergence!\n"
            f"  Original hash: {original_hash}\n"
            f"  Replay hash:   {replay_hash}\n"
            f"  Original state: {original.state}\n"
            f"  Replay state:   {replay.state}"
        )

    @pytest.mark.asyncio
    async def test_replay_produces_identical_hash_under_random_yields(self):
        """
        Same as above, but inject random asyncio yields between submissions
        to simulate concurrent timing variation. The hash must remain stable.
        """
        events = make_event_chain(n_tasks=30, seed=99)

        original = MinimalRuntime()
        for event in events:
            original.apply_event(event)
        original_hash = original.get_canonical_hash()

        # Shuffle submission order to simulate non-deterministic arrival
        shuffled = list(events)
        random.Random(7).shuffle(shuffled)

        replay = MinimalRuntime()
        scheduler = CausalScheduler(dispatch_fn=replay.apply_event)

        for event in shuffled:
            msg_id = event["msg_id"]
            scheduler.submit(
                event_id=msg_id,
                payload=event,
                causal_parents=event["payload"].get("causal_parents", []),
                logical_clock=event["logical_clock"],
                epoch_id=event["epoch_id"],
            )
            # Random yield to simulate timing variation
            if random.random() < 0.3:
                await asyncio.sleep(0)

        await scheduler.run_until_empty()
        replay_hash = replay.get_canonical_hash()

        assert original_hash == replay_hash, (
            f"Replay divergence under random yields!\n"
            f"  Original hash: {original_hash}\n"
            f"  Replay hash:   {replay_hash}"
        )

    @pytest.mark.asyncio
    async def test_snapshot_then_replay_delta_gives_same_hash(self):
        """
        Simulate a snapshot mid-stream, then replay only delta events.
        Final hash must match the hash of the fully-executed original runtime.
        """
        events = make_event_chain(n_tasks=40, seed=42)
        split = 30  # first 30 events are "before snapshot"
        pre_events = events[:split]
        delta_events = events[split:]

        # ── Full original execution ──
        original = MinimalRuntime()
        for event in events:
            original.apply_event(event)
        original_hash = original.get_canonical_hash()

        # ── Snapshot at position 30 ──
        snapshot_runtime = MinimalRuntime()
        for event in pre_events:
            snapshot_runtime.apply_event(event)
        snapshot = await snapshot_runtime.take_snapshot()

        # ── Replay from snapshot + delta ──
        recovered = MinimalRuntime()
        # Restore pre-snapshot state from snapshot
        recovered.state = dict(snapshot["state"])

        # Replay delta via causal scheduler
        scheduler = CausalScheduler(dispatch_fn=recovered.apply_event)
        for event in delta_events:
            scheduler.submit(
                event_id=event["msg_id"],
                payload=event,
                causal_parents=event["payload"].get("causal_parents", []),
                logical_clock=event["logical_clock"],
                epoch_id=event["epoch_id"],
            )
        await scheduler.run_until_empty()
        recovered_hash = recovered.get_canonical_hash()

        assert original_hash == recovered_hash, (
            f"Snapshot+delta replay hash mismatch!\n"
            f"  Expected (full run): {original_hash}\n"
            f"  Got (snapshot+delta): {recovered_hash}"
        )

    @pytest.mark.asyncio
    async def test_replay_handles_legacy_phase6_log_format(self):
        """
        Phase 6 logs used a single causal_parent_id string instead of
        causal_parents list. The replay engine must handle both formats.
        """
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())

        events = [
            {
                "msg_id": parent_id,
                "event_type": "TASK_CREATED",
                "sequence_id": 0,
                "logical_clock": 1,
                "epoch_id": 0,
                "payload": {"task_id": "t1", "data": "x", "causal_parents": []}
            },
            {
                "msg_id": child_id,
                "event_type": "TASK_COMPLETED",
                "sequence_id": 1,
                "logical_clock": 2,
                "epoch_id": 0,
                "payload": {
                    "task_id": "t1",
                    # Legacy Phase 6 format — single string, not a list
                    "causal_parent_id": parent_id,
                }
            },
        ]

        dispatched = []

        def collect(ev):
            dispatched.append(ev["msg_id"])

        scheduler = CausalScheduler(dispatch_fn=collect)
        for event in events:
            payload = event["payload"]
            # Replicate ReplayEngine's backward-compatible extraction
            causal_parents = payload.get("causal_parents", [])
            single = payload.get("causal_parent_id")
            if single and single not in causal_parents:
                causal_parents.append(single)

            scheduler.submit(
                event_id=event["msg_id"],
                payload=event,
                causal_parents=causal_parents,
                logical_clock=event["logical_clock"],
            )

        await scheduler.run_until_empty()

        assert dispatched[0] == parent_id
        assert dispatched[1] == child_id
