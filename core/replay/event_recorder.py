"""core/replay/event_recorder.py

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

from core.foundation.canonical import state_hash, canonicalize
from core.contracts.runtime_events import RuntimeEvent

logger = logging.getLogger(__name__)

MAX_SEGMENT_BYTES = 64 * 1024 * 1024  # 64 MB
MAX_SEGMENT_EVENTS = 100_000


class RecoveryJournal:
    """Cryptographically chained, causal WAL (Write-Ahead Log).
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
        """Synchronous durability barrier.
        Appends the event, chains the hash, and fsyncs immediately.
        Must be called BEFORE topological propagation.
        """
        # Canonicalize first (enums -> declared values) so the hashed bytes
        # and the persisted line describe the SAME logical payload. Enums in
        # plain json.dumps would otherwise fall to default=str (e.g.
        # "ExecutionState.PENDING") while the hash covered "PENDING",
        # breaking any later chain recomputation from the stored line.
        payload = canonicalize(asdict(event))
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


# Transitional compatibility alias.
# Some modules currently import EventRecorder from this package. This alias exists
# only to avoid a mass import rewrite before the canonical journal authority is chosen.
# It must NOT be treated as the canonical event recorder for the convergence program.

# Provide a compatibility wrapper so legacy callers (e.g. test_split_brain_recovery.py)
# can use start()/log_event()/stop() against the canonical RecoveryJournal.
# This wrapper is callable as EventRecorder(log_dir, session_id) to match the
# original RecoveryJournal constructor API, and delegates durability to the journal.


class EventRecorderCompat:
    """Compatibility wrapper for legacy EventRecorder API.

    Accepts the same constructor signature as the original RecoveryJournal
    (log_dir, session_id) and provides start()/log_event()/stop() methods
    while delegating durability to the internal RecoveryJournal instance.
    """

    def __init__(self, log_dir: str = None, session_id: str = None):
        self._journal = RecoveryJournal(log_dir=log_dir, session_id=session_id)
        self._started = False

    @property
    def session_dir(self) -> Path:
        """Delegate session_dir to the underlying RecoveryJournal."""
        return self._journal.session_dir

    async def start(self) -> None:
        """Legacy start — RecoveryJournal uses commit_sync; this is a no-op stub."""
        self._started = True

    async def stop(self) -> None:
        """Legacy stop — flush and close the journal."""
        if self._journal:
            self._journal.close()

    def log_event(self, *args, **kwargs) -> None:
        """Legacy log_event — delegate to commit_sync via canonical API.

        Accepts (name, category, level, data) or any signature; adapt as needed.
        The canonical API is journal.commit_sync(event: RuntimeEvent).
        For legacy callers we accept varargs and build a minimal RuntimeEvent.
        """
        try:
            if len(args) >= 4:
                name, category, level, data = args[0], args[1], args[2], args[3]
            else:
                name, category, level, data = str(args[0]) if args else "UNKNOWN", "core", "info", {}
            from core.contracts.runtime_events import RuntimeEvent
            # RuntimeEvent is a frozen dataclass with fields: event_id, timestamp, parent_event_id, causal_lineage, payload
            # Build a minimal event from the legacy (name, category, level, data) signature
            # and embed the legacy metadata in the payload for later interpretation.
            legacy_payload = {
                "_legacy_name": name,
                "_legacy_category": category,
                "_legacy_level": level,
                "_legacy_data": data
            }
            event = RuntimeEvent(event_id=str(uuid.uuid4()),
                                 timestamp=__import__('time').monotonic(),
                                 parent_event_id=None,
                                 causal_lineage=[],
                                 payload=legacy_payload)
            self._journal.commit_sync(event)
        except Exception:
            logger.warning(f"[EventRecorderCompat] log_event failed: {args}", exc_info=True)


# Provide EventRecorder as the compatibility alias so existing imports
# (e.g. from core.replay.event_recorder import EventRecorder) resolve without
# merging journal architectures. It supports start()/log_event()/stop()
# while delegating durability to the canonical RecoveryJournal.
EventRecorder = EventRecorderCompat