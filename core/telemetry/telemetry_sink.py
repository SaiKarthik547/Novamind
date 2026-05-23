import json
import logging
import os
import threading
from typing import Optional

from core.telemetry.telemetry_event import TelemetryEvent

logger = logging.getLogger("TelemetrySink")

class TelemetrySink:
    """
    Structured JSONL telemetry persistence engine for diagnostics and FORENSIC events.
    Thread-safe synchronous append.
    """
    def __init__(self, log_path: str):
        self.log_path = log_path
        self._lock = threading.Lock()
        self._file = None

    def open(self):
        with self._lock:
            if self._file is None:
                # Ensure directory exists
                os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
                self._file = open(self.log_path, "a", encoding="utf-8")

    def close(self):
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None

    def record_event(self, event: TelemetryEvent):
        """Append event to the JSONL log."""
        try:
            line = json.dumps(event.to_dict()) + "\n"
            with self._lock:
                if self._file:
                    self._file.write(line)
                    self._file.flush()
                else:
                    # Fallback to standard logging if file not open
                    logger.debug(f"Sink closed. Event: {line.strip()}")
        except Exception as e:
            logger.error(f"Failed to write telemetry to sink: {e}")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
