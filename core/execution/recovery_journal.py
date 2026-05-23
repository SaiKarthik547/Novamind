import os
import json
import logging
import threading
from typing import Dict, Any

from core.execution.execution_intent import ExecutionIntent
from core.execution.intent_execution_state import IntentExecutionState

logger = logging.getLogger("RecoveryJournal")

class RecoveryJournal:
    """
    P13D-1: Kernel Write-Ahead Log for execution intents.
    Enforces durability before any intent is dispatched to an adapter.
    """
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'RecoveryJournal':
        with cls._lock:
            if cls._instance is None:
                # We can place the journal in .novamind directory or similar.
                # Using a generic path for now.
                journal_dir = os.path.join(os.getcwd(), ".novamind", "kernel")
                os.makedirs(journal_dir, exist_ok=True)
                journal_path = os.path.join(journal_dir, "recovery.wal")
                cls._instance = cls(journal_path)
            return cls._instance

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._fd_lock = threading.Lock()
        self._fd = None
        self._open()

    def _open(self):
        with self._fd_lock:
            if self._fd is None:
                mode = "a" if os.path.exists(self.filepath) else "w"
                self._fd = open(self.filepath, mode)

    def log_transition(self, intent_id: str, state: IntentExecutionState, payload: Dict[str, Any] = None):
        """
        Appends the state transition to the journal and issues an fsync barrier.
        """
        record = {
            "intent_id": intent_id,
            "state": state.value,
            "payload": payload or {}
        }
        
        with self._fd_lock:
            if self._fd is None:
                self._open()
            
            try:
                self._fd.write(json.dumps(record) + "\n")
                self._fd.flush()
                os.fsync(self._fd.fileno()) # WAL Persistence Barrier
            except Exception as e:
                logger.error(f"Failed to write to RecoveryJournal: {e}")
                raise RuntimeError(f"WAL Persistence Barrier failed: {e}")

    def close(self):
        with self._fd_lock:
            if self._fd:
                self._fd.close()
                self._fd = None
