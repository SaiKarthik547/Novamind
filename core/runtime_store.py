import logging
from pathlib import Path

from core.event_recorder import EventRecorder
from core.state_snapshot import StateSnapshotManager

logger = logging.getLogger(__name__)

class RuntimeStore:
    """
    Unified persistence facade for NovaMind.
    Combines EventRecorder (deltas) with StateSnapshotManager (checkpoints).
    """
    def __init__(self, session_id: str, event_bus, task_manager, bridge_server, agent_registry: dict):
        self.session_id = session_id
        
        # We explicitly isolate session logs by UUID now
        log_dir = Path("runtime/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"session_{session_id}.jsonl"
        
        # Pass the specific log path to EventRecorder
        # (Assuming EventRecorder can take a custom path, else we will modify it later)
        self.event_recorder = EventRecorder(log_path=str(log_path))
        
        self.snapshot_manager = StateSnapshotManager(
            session_id=session_id,
            event_bus=event_bus,
            task_manager=task_manager,
            bridge_server=bridge_server,
            agent_registry=agent_registry
        )

    def get_session_log_path(self) -> Path:
        return Path(self.event_recorder.log_path)

    def trigger_snapshot(self, sequence_id: int):
        return self.snapshot_manager.trigger_snapshot(sequence_id)

    def load_latest_snapshot(self):
        return self.snapshot_manager.load_last_snapshot()
