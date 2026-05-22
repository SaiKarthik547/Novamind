import json
import asyncio
import logging
from pathlib import Path
import time
import uuid

logger = logging.getLogger(__name__)

class EventRecorder:
    def __init__(self, log_path: str = None, logs_dir: str = "logs/session_events"):
        if log_path:
            self.log_file = Path(log_path)
            self.session_id = self.log_file.stem.replace("session_", "")
        else:
            self.logs_dir = Path(logs_dir)
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self.session_id = str(uuid.uuid4())
            self.log_file = self.logs_dir / f"session_{self.session_id}.jsonl"
        
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._queue = asyncio.Queue()
        self._worker_task = None

    async def start(self):
        """Starts the background worker to write logs asynchronously."""
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info(f"EventRecorder started. Logging to {self.log_file}")

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
            
        logger.info("EventRecorder stopped.")

    def log_event(self, event_type: str, source_runtime: str, severity: str, payload: dict, correlation_id: str = None, msg_id: str = None):
        """
        Submits an event to the append-only JSONL log.
        This method is thread-safe as it pushes to an asyncio queue if a loop is running.
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
            # If no event loop is running in this thread, write directly (blocking)
            self._write_to_disk(event)

    async def _process_queue(self):
        """Background coroutine that pulls from the queue and writes to disk."""
        while True:
            event = await self._queue.get()
            self._write_to_disk(event)
            self._queue.task_done()

    def _write_to_disk(self, event: dict):
        """Blocking disk write. Opens in append mode."""
        try:
            from core.foundation.canonical import canonical_dumps
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(canonical_dumps(event) + "\n")
                f.flush()
                import os
                os.fsync(f.fileno())
        except Exception as e:
            logger.error(f"EventRecorder failed to write to disk: {e}")
