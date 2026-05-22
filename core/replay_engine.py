import json
import logging
from enum import Enum, auto
from pathlib import Path
from typing import Iterator, Optional, Dict

from core.replay_cursor import ReplayCursor
from core.canonical import state_hash

logger = logging.getLogger(__name__)

class ReplayMode(Enum):
    STRICT = auto()     # Crash on divergence
    DIAGNOSTIC = auto() # Continue while logging divergence
    FORENSIC = auto()   # Replay invalid historical states intentionally

class ReplayEngine:
    """
    Scalable recovery via snapshot + event delta replay.
    Supports rolling checksum validation to prevent scaling bottlenecks.
    """
    
    def __init__(self, mode: ReplayMode = ReplayMode.STRICT):
        self.mode = mode
        self.cursor: Optional[ReplayCursor] = None

    def _read_deltas(self, session_log: Path, min_sequence: int) -> Iterator[dict]:
        """Yields events from the session log that occurred after the snapshot."""
        if not session_log.exists():
            return

        with open(session_log, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    # Use sequence_id if available, fallback to processing all if legacy
                    seq = event.get("sequence_id", -1)
                    if seq > min_sequence or seq == -1:
                        yield event
                except json.JSONDecodeError:
                    logger.error(f"[ReplayEngine] Corrupt log line at {line_num} in {session_log}")
                    if self.mode == ReplayMode.STRICT:
                        raise ValueError(f"Corrupt JSON at line {line_num}")

    def execute_recovery(self, snapshot: Optional[dict], session_log: Path, event_bus) -> bool:
        """
        Executes a deterministic incremental replay.
        1. Loads cursor from snapshot sequence
        2. Streams delta events
        3. Validates rolling checksums (if embedded)
        4. Publishes events to the provided EventBus
        """
        snapshot_seq = snapshot.get("sequence_id", 0) if snapshot else 0
        self.cursor = ReplayCursor(snapshot_seq)
        
        logger.info(f"[ReplayEngine] Starting replay from sequence {snapshot_seq} in {self.mode.name} mode")
        
        for event in self._read_deltas(session_log, snapshot_seq):
            seq = event.get("sequence_id", -1)
            
            # Advance cursor
            if seq != -1 and not self.cursor.advance(seq):
                msg = f"Sequence gap detected at event {seq}. Expected {self.cursor.last_event_sequence + 1}"
                if self.mode == ReplayMode.STRICT:
                    logger.critical(f"[ReplayEngine] {msg}")
                    return False
                else:
                    logger.warning(f"[ReplayEngine] {msg}. Continuing due to mode {self.mode.name}")
                    # Force advance in non-strict modes
                    self.cursor.last_event_sequence = seq
                    self.cursor.events_processed += 1
            
            # Rolling checksum validation (if event has embedded hash, like intermediate checkpoints)
            embedded_hash = event.get("payload", {}).get("state_hash")
            if embedded_hash:
                verify_obj = {k: v for k, v in event.get("payload", {}).items() if k != "state_hash"}
                computed = state_hash(verify_obj)
                if computed != embedded_hash:
                    h_msg = f"Replay divergence! Hash mismatch at seq {seq}"
                    if self.mode == ReplayMode.STRICT:
                        logger.critical(f"[ReplayEngine] {h_msg}")
                        return False
                    else:
                        logger.warning(f"[ReplayEngine] {h_msg}")
            
            # Publish event into the runtime
            event_bus.publish(event)
            
        logger.info(f"[ReplayEngine] Replay complete. Processed {self.cursor.events_processed} delta events.")
        return True
