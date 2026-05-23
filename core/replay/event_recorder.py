import json
import asyncio
import logging
from pathlib import Path
import time
import uuid
import os

from core.foundation.canonical import canonical_dumps, state_hash
from core.replay.event_codec import JsonlEventCodec

logger = logging.getLogger(__name__)

MAX_SEGMENT_BYTES = 64 * 1024 * 1024  # 64 MB
MAX_SEGMENT_EVENTS = 100_000

class EventRecorder:
    """
    Phase 11: Cryptographically chained, checkpoint-segmented Write-Ahead Log.
    Uses EventStorageCodec to encode events safely.
    Maintains a manifest.json tracking lineage across segments.
    """
    def __init__(self, log_dir: str = None, session_id: str = None, log_path: str = None):
        # L2-C: log_path compatibility — main.py may pass log_path instead of log_dir/session_id
        if log_path is not None:
            from pathlib import Path as _Path
            _lp = _Path(log_path)
            if log_dir is None:
                log_dir = str(_lp.parent)
            if session_id is None:
                # Strip 'session_' prefix if present
                stem = _lp.stem
                session_id = stem[len("session_"):] if stem.startswith("session_") else stem

        self.session_id = session_id or str(uuid.uuid4())
        base_dir = Path(log_dir) if log_dir else Path("runtime/logs")
        self.session_dir = base_dir / f"session_{self.session_id}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        self.manifest_file = self.session_dir / "manifest.json"
        self._codec = JsonlEventCodec()
        
        self._queue = asyncio.Queue()
        self._worker_task = None
        
        self._segment_index = 0
        self._current_file = None
        self._current_file_path = None
        self._current_segment_bytes = 0
        self._current_segment_events = 0
        
        self._last_hash = None
        self._checkpoint_segments = []
        
        self._init_manifest()
        self._open_segment(0)

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
            "protocol_version": "1.0.0",
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
        logger.info(f"[EventRecorder] Opened new segment: {self._current_file_path.name}")

    def _rotate_segment(self, is_checkpoint: bool = False):
        if is_checkpoint:
            self._checkpoint_segments.append(self._segment_index)
        self._open_segment(self._segment_index + 1)

    async def start(self):
        """Starts the background worker to write logs asynchronously."""
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info(f"EventRecorder started. Logging to directory {self.session_dir}")

    async def stop(self):
        """Stops the worker and flushes the queue."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        # Flush remaining
        while not self._queue.empty():
            event = self._queue.get_nowait()
            self._write_to_disk(event)
            
        if self._current_file:
            self._current_file.close()
            self._current_file = None
            
        logger.info("EventRecorder stopped.")

    def log_event(self, event_type: str, source_runtime: str, severity: str, payload: dict, correlation_id: str = None, msg_id: str = None):
        """
        Submits an event to the WAL.
        """
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "source_runtime": source_runtime,
            "severity": severity,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "msg_id": msg_id or str(uuid.uuid4()),
            "payload": payload
        }

        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            self._write_to_disk(event)

    def log_intent_event(
        self,
        lifecycle_event: str,
        intent_id: str,
        capability: str,
        authority_origin: str,
        determinism_class: str,
        payload_summary: dict = None,
        error: str = None,
        parent_intent_id: str = None,
    ):
        """
        L2-C: WAL lifecycle event for ExecutionIntents.
        These events are AUTHORITATIVE — recovery and replay key off them.
        They are SEPARATE from generic log_event telemetry.

        Lifecycle events: INTENT_CREATED, INTENT_DISPATCHED, INTENT_RUNNING,
        INTENT_VERIFYING, INTENT_COMPLETED, INTENT_FAILED, INTENT_COMPENSATING,
        INTENT_COMPENSATED, INTENT_ABORTED, INTENT_REJECTED.
        """
        _terminal_errors = {"INTENT_FAILED", "INTENT_ABORTED", "INTENT_REJECTED", "INTENT_COMPENSATING"}
        severity = "ERROR" if lifecycle_event in _terminal_errors else "INFO"
        self.log_event(
            event_type=lifecycle_event,
            source_runtime="KERNEL_INTENT",
            severity=severity,
            payload={
                "intent_id": intent_id,
                "parent_intent_id": parent_intent_id,
                "capability": capability,
                "authority_origin": authority_origin,
                "determinism_class": determinism_class,
                "payload_summary": payload_summary or {},
                "error": error,
            },
            correlation_id=intent_id,
        )

    async def _process_queue(self):
        """Background coroutine that pulls from the queue and writes to disk."""
        while True:
            event = await self._queue.get()
            self._write_to_disk(event)
            self._queue.task_done()

    def _write_to_disk(self, event: dict):
        """Blocking disk write. Calculates hash chain, serializes, appends, fsyncs."""
        try:
            # 1. Cryptographic Chaining
            event["previous_hash"] = self._last_hash
            
            # The event_hash strictly excludes itself to prevent recursive instability
            event.pop("event_hash", None)
            
            # Calculate canonical hash of the pure lineage node
            current_hash = state_hash(event)
            event["event_hash"] = current_hash
            self._last_hash = current_hash

            # 2. Encode
            data = self._codec.encode(event)
            data_len = len(data)

            # 3. Size Ceiling Pre-check
            if self._current_segment_bytes + data_len > MAX_SEGMENT_BYTES or self._current_segment_events >= MAX_SEGMENT_EVENTS:
                self._rotate_segment()

            # 4. Write & Sync
            self._current_file.write(data.decode("utf-8")) # JSONL codec returns utf-8 bytes, open() expects str
            self._current_file.flush()
            os.fsync(self._current_file.fileno())

            self._current_segment_bytes += data_len
            self._current_segment_events += 1

            # 5. Checkpoint Rotation (Post-Write)
            if event["event_type"] == "SNAPSHOT_COMMIT":
                self._rotate_segment(is_checkpoint=True)

        except Exception as e:
            logger.error(f"EventRecorder failed to write to disk: {e}")
