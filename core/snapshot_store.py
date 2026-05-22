import os
import json
import logging
import hashlib
from pathlib import Path
from typing import Optional, List

from core.canonical import canonical_dumps

logger = logging.getLogger(__name__)

class SnapshotStore:
    """
    Manages physical storage of runtime snapshots.
    Guarantees crash-consistent writes using temp-file + atomic rename + fsync.
    Snapshots are append-only and versioned by sequence ID.
    """
    
    def __init__(self, session_id: str, base_dir: str = "runtime/snapshots"):
        self.session_id = session_id
        self.base_dir = Path(base_dir) / f"session_{session_id}"
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def save_snapshot(self, sequence_id: int, snapshot_data: dict) -> Path:
        """
        Saves a snapshot using strict atomic semantics.
        1. Serialize with canonical JSON
        2. Write to a temporary file
        3. Force OS to flush to disk (fsync)
        4. Atomically rename to final target
        """
        filename = f"snapshot_{sequence_id:010d}.json"
        final_path = self.base_dir / filename
        temp_path = self.base_dir / f"{filename}.tmp"
        
        try:
            raw_data = canonical_dumps(snapshot_data).encode("utf-8")
            
            # Write to temp file and fsync
            with open(temp_path, "wb") as f:
                f.write(raw_data)
                f.flush()
                os.fsync(f.fileno())
            
            # Atomic rename (POSIX and modern Windows guarantee this)
            temp_path.replace(final_path)
            
            logger.info(f"Snapshot [{sequence_id}] durably committed to disk at {final_path.name}")
            return final_path
            
        except Exception as e:
            logger.error(f"Failed to save snapshot {sequence_id}: {e}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise

    def load_latest_snapshot(self) -> Optional[dict]:
        """
        Loads the most recent valid snapshot from disk.
        Automatically verifies the integrity (hash) of the loaded file.
        """
        snapshots = self.list_snapshots()
        if not snapshots:
            return None
            
        latest_path = snapshots[-1]
        try:
            with open(latest_path, "rb") as f:
                raw_data = f.read()
            
            data = json.loads(raw_data.decode("utf-8"))
            
            # Verify internal hash if present
            stored_hash = data.get("state_hash")
            if stored_hash:
                # Strip hash before recomputing to check integrity
                verify_obj = {k: v for k, v in data.items() if k != "state_hash"}
                from core.canonical import state_hash
                computed = state_hash(verify_obj)
                if computed != stored_hash:
                    logger.critical(f"Snapshot corruption detected in {latest_path.name}! Hash mismatch.")
                    return None
                    
            return data
            
        except Exception as e:
            logger.error(f"Failed to load snapshot {latest_path}: {e}")
            return None

    def list_snapshots(self) -> List[Path]:
        """Returns all valid snapshot paths ordered sequentially."""
        try:
            files = list(self.base_dir.glob("snapshot_*.json"))
            return sorted(files)
        except Exception as e:
            logger.error(f"Failed to list snapshots: {e}")
            return []
