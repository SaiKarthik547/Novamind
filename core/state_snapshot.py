import time
import uuid
import logging
from typing import Dict, Any, Optional

from core.snapshot_store import SnapshotStore
from core.canonical import state_hash

logger = logging.getLogger(__name__)

class StateSnapshotManager:
    """
    Coordinates authoritative runtime snapshots.
    Uses EventBus to enforce atomic barriers (SNAPSHOT_BEGIN / COMMIT / ABORT).
    """

    def __init__(self, session_id: str, event_bus: Any, task_manager: Any, bridge_server: Any, agent_registry: Dict[str, Any]):
        self.session_id = session_id
        self.event_bus = event_bus
        self.task_manager = task_manager
        self.bridge_server = bridge_server
        self.agent_registry = agent_registry
        self.store = SnapshotStore(session_id)
        
        self.snapshot_version = "1.0.0"
        self._is_snapshotting = False

    def trigger_snapshot(self, sequence_id: int) -> Optional[str]:
        """
        Executes a lightweight runtime transaction to capture the state.
        Returns the new state_hash if successful, or None if aborted.
        """
        if self._is_snapshotting:
            logger.warning("Snapshot already in progress. Ignoring trigger.")
            return None
            
        self._is_snapshotting = True
        snapshot_id = str(uuid.uuid4())
        
        try:
            # 1. Atomic Barrier: Freeze queues and block transitions
            self.event_bus.publish({
                "type": "SNAPSHOT_BEGIN",
                "snapshot_id": snapshot_id,
                "sequence_id": sequence_id
            })
            
            # 2. Capture Authoritative State
            # We must serialize the tasks manually to respect the deterministic schema
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
            
            # 3. Construct Schema
            snapshot_obj = {
                "snapshot_id": snapshot_id,
                "snapshot_version": self.snapshot_version,
                "session_id": self.session_id,
                "timestamp": time.time(),
                "sequence_id": sequence_id,
                "runtime_state": runtime_state
            }
            
            # 4. Hash and Commit
            s_hash = state_hash(snapshot_obj)
            snapshot_obj["state_hash"] = s_hash
            
            self.store.save_snapshot(sequence_id, snapshot_obj)
            
            # 5. Release Barrier
            self.event_bus.publish({
                "type": "SNAPSHOT_COMMIT",
                "snapshot_id": snapshot_id,
                "state_hash": s_hash
            })
            
            logger.info(f"Snapshot {snapshot_id} (seq {sequence_id}) completed. Hash: {s_hash[:16]}...")
            return s_hash
            
        except Exception as e:
            logger.error(f"Snapshot transaction {snapshot_id} failed: {e}")
            self.event_bus.publish({
                "type": "SNAPSHOT_ABORT",
                "snapshot_id": snapshot_id,
                "error": str(e)
            })
            return None
        finally:
            self._is_snapshotting = False

    def load_last_snapshot(self) -> Optional[dict]:
        """Loads the most recent snapshot for recovery boot."""
        return self.store.load_latest_snapshot()
