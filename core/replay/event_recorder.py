"""
core/replay/event_recorder.py

Phase 17: Replay Convergence (RecoveryJournal)
Transitions from "telemetry append log" to "causal synchronization preservation layer".
Guarantees fsync-before-propagation to preserve topological determinism across crashes.
"""

import json
import logging
from pathlib import Path
import time
import uuid
import os
from dataclasses import asdict
import threading

from core.foundation.canonical import state_hash
from core.contracts.runtime_events import RuntimeEvent

logger = logging.getLogger(__name__)

MAX_SEGMENT_BYTES = 64 * 1024 * 1024  # 64 MB
MAX_SEGMENT_EVENTS = 100_000

class RecoveryJournal:
    """
    Cryptographically chained, causal WAL (Write-Ahead Log).
    No longer an async queue; enforces synchronous durability (fsync).
    """
    def __init__(self, log_dir: str = None, session_id: str = None):
        self.session_id = session_id or str(uuid.uuid4())
        base_dir = Path(log_dir) if log_dir else Path("runtime/logs")
        self.session_dir = base_dir / f"session_{self.session_id}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        self.manifest_file = self.session_dir / "manifest.json"
        
        self._segment_index = 0
        self._current_file = None
        self._current_file_path = None
        self._current_segment_bytes = 0
        self._current_segment_events = 0
        
        self._last_hash = None
        self._checkpoint_segments = []
        
        self._write_lock = threading.Lock()
        
        self._init_manifest()
        self._open_segment(0)
        logger.info(f"[RecoveryJournal] Initialized causal durability at {self.session_dir}")

    def _init_manifest(self):
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    self._segment_index = manifest.get("segment_count", 0)
                    self._checkpoint_segments = manifest.get("checkpoint_segments", [])
            except json.JSONDecodeError:
                pass
        self._update_manifest()

    def _update_manifest(self):
        manifest = {
            "session_id": self.session_id,
            "protocol_version": "1.1.0",
            "segment_count": self._segment_index + 1,
            "created_at_ns": time.time_ns(),
            "last_segment": f"{self._segment_index:05d}.jsonl",
            "checkpoint_segments": self._checkpoint_segments
        }
        temp_file = self.manifest_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp_file.replace(self.manifest_file)

    def _open_segment(self, index: int):
        if self._current_file:
            self._current_file.close()
            
        self._segment_index = index
        self._current_segment_bytes = 0
        self._current_segment_events = 0
        self._current_file_path = self.session_dir / f"{index:05d}.jsonl"
        self._current_file = open(self._current_file_path, "a", encoding="utf-8")
        self._update_manifest()

    def _rotate_segment(self, is_checkpoint: bool = False):
        if is_checkpoint:
            self._checkpoint_segments.append(self._segment_index)
        self._open_segment(self._segment_index + 1)

    def commit_sync(self, event: RuntimeEvent) -> None:
        """
        Synchronous durability barrier.
        Appends the event, chains the hash, and fsyncs immediately.
        Must be called BEFORE topological propagation.
        """
        payload = asdict(event)
        payload["_event_type"] = event.__class__.__name__
        
        with self._write_lock:
            try:
                # 1. Cryptographic Chaining of Causal Topology
                # Incorporate previous hash + current causal topology footprint
                hashable_node = {
                    "event_id": payload.get("event_id"),
                    "parent_event_id": payload.get("parent_event_id"),
                    "causal_lineage": payload.get("causal_lineage", []),
                    "previous_hash": self._last_hash,
                    "payload": payload
                }
                current_hash = state_hash(hashable_node)
                payload["topology_hash"] = current_hash
                payload["previous_hash"] = self._last_hash
                self._last_hash = current_hash

                # 2. Serialize
                data_str = json.dumps(payload, default=str) + "\n"
                data_bytes_len = len(data_str.encode("utf-8"))

                # 3. Size Ceiling Pre-check
                if self._current_segment_bytes + data_bytes_len > MAX_SEGMENT_BYTES or self._current_segment_events >= MAX_SEGMENT_EVENTS:
                    self._rotate_segment()

                # 4. FSYNC DURABILITY BARRIER
                self._current_file.write(data_str)
                self._current_file.flush()
                os.fsync(self._current_file.fileno())

                self._current_segment_bytes += data_bytes_len
                self._current_segment_events += 1

                # 5. Logical Checkpoint Trigger (Placeholder for Quiescence hook)
                if event.__class__.__name__ == "SchedulerEvent" and payload.get("action") == "TOPOLOGY_QUIESCENT":
                    self._rotate_segment(is_checkpoint=True)

            except Exception as e:
                logger.error(f"[RecoveryJournal] Fatal durability failure: {e}")
                # A WAL failure must crash the system, as replay determinism is lost
                raise RuntimeError(f"WAL fsync failed, causal determinism lost: {e}")

    def close(self):
        if self._current_file:
            self._current_file.flush()
            os.fsync(self._current_file.fileno())
            self._current_file.close()
            self._current_file = None
