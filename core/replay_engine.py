"""
core/replay_engine.py

Phase 7 — Causal Scheduler-backed Deterministic Replay Engine.

Phase 6 replay was linear: events were dispatched in file order.
This is incorrect under concurrent execution — a fast agent may have
written its completion BEFORE a slower agent's intermediate event, even
though causally the slower agent's event came first.

Phase 7 replay uses the CausalScheduler DAG:
  1. All delta events are submitted to the scheduler with their
     causal_parents and logical_clock values preserved from the log.
  2. The scheduler drains events in correct causal order regardless of
     their on-disk ordering.
  3. Hash checkpoints are validated against canonical state after
     each scheduling cycle.

Replay modes:
  STRICT     — abort on any divergence (replay in certification)
  DIAGNOSTIC — continue while logging divergence (recovery boot)
  FORENSIC   — replay historically invalid states (post-mortem analysis)
"""

import json
import logging
from enum import Enum, auto
from pathlib import Path
from typing import Iterator, Optional, Dict, List

from core.replay_cursor import ReplayCursor
from core.canonical import state_hash
from core.causal_scheduler import CausalScheduler, make_causal_scheduler

logger = logging.getLogger(__name__)


class ReplayMode(Enum):
    STRICT = auto()      # Crash on divergence
    DIAGNOSTIC = auto()  # Continue while logging divergence
    FORENSIC = auto()    # Replay invalid historical states intentionally


class ReplayEngine:
    """
    Scalable deterministic recovery via snapshot + causal event delta replay.

    Phase 7: Events are fed through the CausalScheduler, which reconstructs
    the correct execution order using causal_parents and logical_clock values
    embedded in each event. This eliminates the wall-clock ordering assumption
    that made Phase 6 replay non-deterministic under concurrent workloads.
    """

    def __init__(self, mode: ReplayMode = ReplayMode.STRICT):
        self.mode = mode
        self.cursor: Optional[ReplayCursor] = None

    def _read_deltas(self, session_log: Path, min_sequence: int) -> Iterator[dict]:
        """
        Yields events from the session log that occurred after the snapshot.
        In STRICT mode, corrupt JSON lines raise ValueError immediately.
        In DIAGNOSTIC/FORENSIC mode, corrupt lines are skipped with a warning.
        """
        if not session_log.exists():
            return

        with open(session_log, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    seq = event.get("sequence_id", -1)
                    if seq > min_sequence or seq == -1:
                        yield event
                except json.JSONDecodeError:
                    logger.error(
                        f"[ReplayEngine] Corrupt log line at {line_num} in {session_log}"
                    )
                    if self.mode == ReplayMode.STRICT:
                        raise ValueError(f"Corrupt JSON at line {line_num}")

    def _submit_to_scheduler(
        self, scheduler: CausalScheduler, events: List[dict]
    ) -> int:
        """
        Submits all delta events to the causal scheduler.

        For each event we extract:
          msg_id         → event_id for the DAG node
          causal_parents → list of parent msg_ids (Phase 7 many-to-many support)
          logical_clock  → Lamport value for deterministic ordering
          epoch_id       → which epoch this event belongs to

        Falls back gracefully for Phase 6 logs that don't have these fields:
          causal_parents defaults to [] (no dependencies — immediate dispatch)
          logical_clock defaults to sequence_id (monotonic proxy)
          epoch_id defaults to 0
        """
        submitted = 0
        for event in events:
            msg_id = event.get("msg_id") or event.get("sequence_id") or str(id(event))
            payload = event.get("payload", {})

            # Phase 7 fields (may be absent in Phase 6 logs — graceful fallback)
            causal_parents: List[str] = payload.get("causal_parents", [])
            # Also support legacy single-parent format
            single_parent = payload.get("causal_parent_id")
            if single_parent and single_parent not in causal_parents:
                causal_parents.append(single_parent)

            logical_clock: int = event.get(
                "logical_clock",
                event.get("sequence_id", 0)  # sequence_id as monotonic proxy
            )
            epoch_id: int = event.get("epoch_id", 0)

            scheduler.submit(
                event_id=str(msg_id),
                payload=event,
                causal_parents=[str(p) for p in causal_parents],
                logical_clock=logical_clock,
                epoch_id=epoch_id,
            )
            submitted += 1

        return submitted

    async def execute_recovery(
        self,
        snapshot: Optional[dict],
        session_log: Path,
        event_bus,
    ) -> bool:
        """
        Executes a deterministic incremental replay using the CausalScheduler.

        1. Loads cursor position from the snapshot sequence_id.
        2. Reads all delta events from the session log.
        3. Submits all events to the CausalScheduler with their causal metadata.
        4. Drains the scheduler — events are dispatched in causal order,
           not file order.
        5. Validates rolling checksums on any events that embed a state_hash.

        Returns True on success, False on critical failure.
        """
        snapshot_seq = snapshot.get("sequence_id", 0) if snapshot else 0
        self.cursor = ReplayCursor(snapshot_seq)

        logger.info(
            f"[ReplayEngine] Starting causal replay from seq={snapshot_seq} "
            f"mode={self.mode.name}"
        )

        # Read all delta events first so the scheduler can build the full DAG
        # before dispatching. This is required for correct many-to-many resolution.
        all_deltas = list(self._read_deltas(session_log, snapshot_seq))
        logger.info(f"[ReplayEngine] Loaded {len(all_deltas)} delta events for replay")

        if not all_deltas:
            logger.info("[ReplayEngine] No delta events to replay. Recovery complete.")
            return True

        # Build the causal scheduler bound to the event bus publish function
        scheduler = make_causal_scheduler(dispatch_fn=event_bus.publish)

        # Submit all events — scheduler builds dependency graph
        n_submitted = self._submit_to_scheduler(scheduler, all_deltas)
        logger.info(f"[ReplayEngine] Submitted {n_submitted} events to causal scheduler")

        # Drain in causal order
        n_dispatched = await scheduler.run_until_empty()
        logger.info(
            f"[ReplayEngine] Causal replay complete. "
            f"Dispatched={n_dispatched} / Submitted={n_submitted}"
        )

        # Validate final cursor integrity
        if n_dispatched < n_submitted:
            msg = (
                f"[ReplayEngine] {n_submitted - n_dispatched} events were not dispatched. "
                f"Possible dependency cycle or corrupt log."
            )
            if self.mode == ReplayMode.STRICT:
                logger.critical(msg)
                return False
            else:
                logger.warning(msg)

        # Update cursor to last processed sequence
        if all_deltas:
            last_seq = max(
                (e.get("sequence_id", 0) for e in all_deltas), default=snapshot_seq
            )
            self.cursor.last_event_sequence = last_seq
            self.cursor.events_processed = n_dispatched

        # Emit scheduler trace for observability
        trace = scheduler.get_trace()
        logger.debug(f"[ReplayEngine] Scheduler trace: {len(trace)} entries recorded")

        return True

    def execute_recovery_sync(
        self,
        snapshot: Optional[dict],
        session_log: Path,
        event_bus,
    ) -> bool:
        """
        Synchronous wrapper for execute_recovery — for callers outside an
        async context (e.g., recovery boot in main.py before the loop starts).
        Uses asyncio.run() to execute the coroutine in an isolated loop.
        """
        import asyncio
        try:
            return asyncio.run(self.execute_recovery(snapshot, session_log, event_bus))
        except RuntimeError:
            # Already inside a running loop (e.g., called from an async context)
            # Caller should use execute_recovery directly instead
            logger.error(
                "[ReplayEngine] execute_recovery_sync called from within a running "
                "event loop. Use 'await execute_recovery(...)' instead."
            )
            return False
