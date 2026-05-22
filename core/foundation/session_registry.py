import os
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class SessionRegistry:
    """
    Maintains the record of active and historical sessions.
    Crucial for crash continuity across process restarts.
    """
    def __init__(self, registry_file: str = "runtime/session_registry.json"):
        self.registry_path = Path(registry_file)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.sessions = []
        self._load_registry()

    def _load_registry(self):
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load session registry: {e}")
                self.sessions = []

    def _save_registry(self):
        # Crash-consistent temp write
        temp_path = self.registry_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(self.registry_path)
        except Exception as e:
            logger.error(f"Failed to save session registry: {e}")

    def create_new_session(self) -> str:
        """Registers a new session UUID and sets it as the latest."""
        session_id = str(uuid.uuid4())
        self.sessions.append({"session_id": session_id, "status": "active"})
        self._save_registry()
        return session_id

    def get_latest_session(self) -> Optional[str]:
        """Returns the UUID of the most recent session, if any exist."""
        if not self.sessions:
            return None
        return self.sessions[-1]["session_id"]
        
    def mark_session_closed(self, session_id: str):
        for s in self.sessions:
            if s["session_id"] == session_id:
                s["status"] = "closed"
        self._save_registry()
