import copy
import logging
from typing import Dict, Any, Callable

logger = logging.getLogger("RuntimeSnapshotProvider")

class RuntimeSnapshotProvider:
    """
    Phase 15: Immutable State Provider for UI.
    UI queries MUST NOT read live dictionaries from the Runtime, as that causes
    race conditions during concurrent intent execution.
    This component manages deep-copied state snapshots.
    """
    
    def __init__(self, state_supplier: Callable[[], Dict[str, Any]]):
        """
        state_supplier is a function (e.g. from RuntimeKernel) that provides
        the actual mutable state dictionary when called.
        """
        self._state_supplier = state_supplier
        self._latest_snapshot: Dict[str, Any] = {}
        
    def take_snapshot(self) -> None:
        """
        Called by the Runtime at deterministic boundaries (e.g., after an intent completes)
        to publish a safe, immutable copy of the state for observational clients.
        """
        # Deep copy ensures the UI can iterate the state without RuntimeLock violations
        live_state = self._state_supplier()
        self._latest_snapshot = copy.deepcopy(live_state)
        
    def get_snapshot(self) -> Dict[str, Any]:
        """
        Called by the UI or telemetry to read the current safe state.
        This is always a non-blocking, lock-free read of the last published snapshot.
        """
        return self._latest_snapshot
