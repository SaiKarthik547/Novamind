import logging
from pathlib import Path

from core.replay.event_recorder import EventRecorder
from core.state.state_snapshot import StateSnapshotManager

logger = logging.getLogger(__name__)

class RuntimeStore:
    """
    Unified persistence facade for NovaMind.
    Combines EventRecorder (deltas) with StateSnapshotManager (checkpoints).

    Phase 7: trigger_snapshot() is now async because StateSnapshotManager
    uses the tiered SnapshotBarrier (asyncio-based) for mutation draining.
    """
    def __init__(self, session_id: str, event_bus, task_manager, bridge_server, agent_registry: dict):
        self.session_id = session_id

        # We explicitly isolate session logs by UUID now
        log_dir = Path("runtime/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"session_{session_id}.jsonl"

        self.event_recorder = EventRecorder(log_path=str(log_path))

        self.snapshot_manager = StateSnapshotManager(
            session_id=session_id,
            event_bus=event_bus,
            task_manager=task_manager,
            bridge_server=bridge_server,
            agent_registry=agent_registry
        )

    def get_session_log_path(self) -> Path:
        return Path(self.event_recorder.log_file)

    async def trigger_snapshot(self, sequence_id: int):
        """Async: delegates to the barrier-protected StateSnapshotManager."""
        return await self.snapshot_manager.trigger_snapshot(sequence_id)

    def load_latest_snapshot(self):
        return self.snapshot_manager.load_last_snapshot()
