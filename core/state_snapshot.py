import asyncio
import time
import uuid
import logging
from typing import Dict, Any, Optional

from core.snapshot_store import SnapshotStore
from core.canonical import state_hash
from core.synchronization import (
    get_snapshot_barrier, get_epoch_manager, get_runtime_clock, SnapshotBarrier, EpochManager
)

logger = logging.getLogger(__name__)

class StateSnapshotManager:
    """
    Coordinates authoritative runtime snapshots.

    Phase 7: Snapshots now use the tiered SnapshotBarrier to drain
    in-flight mutations before state capture. After a successful commit,
    the EpochManager advances to open a new epoch, eliminating
    mid-transition ambiguity in the event log.

    Read-only observers (metrics, heartbeats, logging) are never blocked.
    """

    def __init__(
        self,
        session_id: str,
        event_bus: Any,
        task_manager: Any,
        bridge_server: Any,
        agent_registry: Dict[str, Any],
        barrier: Optional[SnapshotBarrier] = None,
        epoch_manager: Optional[EpochManager] = None,
    ):
        self.session_id = session_id
        self.event_bus = event_bus
        self.task_manager = task_manager
        self.bridge_server = bridge_server
        self.agent_registry = agent_registry
        self.store = SnapshotStore(session_id)
        # Use the shared runtime primitives unless overridden (useful for tests)
        self.barrier = barrier or get_snapshot_barrier()
        self.epoch_manager = epoch_manager or get_epoch_manager()
        self.clock = get_runtime_clock()

        self.snapshot_version = "2.0.0"  # Phase 7 schema version

    async def trigger_snapshot(self, sequence_id: int) -> Optional[str]:
        """
        Executes an epoch-sealed, barrier-protected snapshot.

        Phase 7 flow:
          1. Enter SnapshotBarrier — drains in-flight mutations, blocks new ones
          2. Publish SNAPSHOT_BEGIN (consumers stop accepting new work)
          3. Capture authoritative state tagged with current epoch + logical clock
          4. Hash and persist
          5. Publish SNAPSHOT_COMMIT
          6. Exit barrier — EpochManager advances, mutations resume

        Returns the state_hash on success, None on abort.
        """
        if self.barrier.is_frozen:
            logger.warning("Snapshot already in progress. Ignoring trigger.")
            return None

        snapshot_id = str(uuid.uuid4())
        # Tick the clock before entering the barrier
        clock_at_begin = self.clock.tick()
        epoch_at_begin = self.epoch_manager.current

        try:
            async with self.barrier.snapshot_window(self.epoch_manager):
                # 1. Announce barrier to all subscribers
                self.event_bus.publish({
                    "type": "SNAPSHOT_BEGIN",
                    "snapshot_id": snapshot_id,
                    "sequence_id": sequence_id,
                    "epoch_id": epoch_at_begin,
                    "logical_clock": clock_at_begin,
                })

                # 2. Capture Authoritative State
                tasks_state = {}
                for tid, t in self.task_manager.tasks.items():
                    tasks_state[tid] = {
                        "id": t.id,
                        "description": t.description,
                        "status": t.status,
                        "created_at": t.created_at,
                        "completed_at": t.completed_at,
                        "parent_id": t.parent_id,
                        "assigned_agent": t.assigned_agent,
                        "result": t.result,
                        "error": t.error,
                        "tools_used": t.tools_used
                    }

                ipc_state = {
                    "bridge_mode": "PRODUCTION" if not getattr(self.bridge_server, "chaos_mode", False) else "CHAOS",
                    "degraded": getattr(self.bridge_server, "degraded", False),
                    "last_out_seq": getattr(self.bridge_server, "_out_seq", 0),
                    "reconciliation_queue_size": len(getattr(self.bridge_server, "reconciliation_queue", []))
                }

                agent_state = {}
                for name, agent in self.agent_registry.items():
                    if hasattr(agent, "get_state"):
                        agent_state[name] = agent.get_state()

                runtime_state = {
                    "tasks": tasks_state,
                    "agents": agent_state,
                    "ipc": ipc_state,
                    "heartbeat": getattr(self.bridge_server, "heartbeat_callback", lambda: {})()
                }

                # 3. Construct Schema (Phase 7: includes epoch + clock)
                snapshot_obj = {
                    "snapshot_id": snapshot_id,
                    "snapshot_version": self.snapshot_version,
                    "session_id": self.session_id,
                    "timestamp": time.time(),
                    "sequence_id": sequence_id,
                    "epoch_id": epoch_at_begin,
                    "logical_clock": clock_at_begin,
                    "runtime_state": runtime_state
                }

                # 4. Hash and Commit
                s_hash = state_hash(snapshot_obj)
                snapshot_obj["state_hash"] = s_hash

                self.store.save_snapshot(sequence_id, snapshot_obj)

                # 5. Release — signal commit before barrier exits and epoch advances
                self.event_bus.publish({
                    "type": "SNAPSHOT_COMMIT",
                    "snapshot_id": snapshot_id,
                    "state_hash": s_hash,
                    "epoch_id": epoch_at_begin,
                    "new_epoch_id": epoch_at_begin + 1,
                })

                logger.info(
                    f"[Snapshot] {snapshot_id[:8]} (seq={sequence_id}, "
                    f"epoch={epoch_at_begin}, clock={clock_at_begin}) → hash={s_hash[:16]}..."
                )
                return s_hash

        except Exception as e:
            logger.error(f"[Snapshot] Transaction {snapshot_id[:8]} failed: {e}")
            self.event_bus.publish({
                "type": "SNAPSHOT_ABORT",
                "snapshot_id": snapshot_id,
                "error": str(e)
            })
            return None

    def load_last_snapshot(self) -> Optional[dict]:
        """Loads the most recent snapshot for recovery boot."""
        return self.store.load_latest_snapshot()
