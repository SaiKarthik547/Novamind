"""
core/replay/replay_engine.py

Phase 11 — Week 3: WAL Hardening
Deterministic Replay Engine with Cryptographic Hash Chaining and Segmentation.
"""

import json
import logging
from enum import Enum, auto
from pathlib import Path
from typing import Iterator, Optional, List

from core.replay.replay_cursor import ReplayCursor
from core.foundation.canonical import state_hash
from core.orchestration.causal_scheduler import CausalScheduler, make_causal_scheduler
from core.replay.event_codec import JsonlEventCodec

logger = logging.getLogger(__name__)


class ReplayMode(Enum):
    STRICT = auto()      # Crash immediately on cryptographic divergence or missing hashes.
    DIAGNOSTIC = auto()  # Continue while logging divergence. Allows legacy fallback.
    FORENSIC = auto()    # Replay historically invalid states intentionally.
    SALVAGE = auto()     # Replay perfectly until corruption boundary, halt, return safe cursor.


class ReplayEngine:
    def __init__(self, mode: ReplayMode = ReplayMode.STRICT):
        self.mode = mode
        self.cursor: Optional[ReplayCursor] = None
        self._codec = JsonlEventCodec()
        self._legacy_fallback_active = False

    def _discover_segments(self, session_dir: Path) -> List[Path]:
        """Reads the manifest to find segments, or falls back to lexicographical."""
        manifest_file = session_dir / "manifest.json"
        segments = []
        
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    count = manifest.get("segment_count", 0)
                    for i in range(count):
                        p = session_dir / f"{i:05d}.jsonl"
                        if p.exists():
                            segments.append(p)
                return segments
            except Exception as e:
                logger.warning(f"Failed to read manifest.json, falling back to lexicographical: {e}")
        
        # Fallback to lexicographical discovery (useful for legacy single-file dirs)
        # If it's a legacy flat file, handle it
        if session_dir.is_file():
            return [session_dir]
            
        for path in sorted(session_dir.glob("*.jsonl")):
            segments.append(path)
            
        return segments

    def _read_deltas(self, session_dir: Path, min_sequence: int) -> Iterator[dict]:
        if not session_dir.exists():
            return

        segments = self._discover_segments(session_dir)
        expected_last_hash = None
        is_first_event = True

        for segment_path in segments:
            segment_id = segment_path.stem
            
            with open(segment_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                        
                    try:
                        event = self._codec.decode(line.encode("utf-8"))
                    except Exception as e:
                        msg = f"Corrupt data at {segment_id}:{line_num}"
                        if self.mode == ReplayMode.STRICT:
                            raise ValueError(msg)
                        elif self.mode == ReplayMode.SALVAGE:
                            logger.warning(f"{msg} - SALVAGE boundary reached.")
                            return
                        logger.error(msg)
                        continue

                    # Legacy Fallback Logic
                    if is_first_event:
                        is_first_event = False
                        if "previous_hash" not in event:
                            if self.mode in (ReplayMode.DIAGNOSTIC, ReplayMode.SALVAGE, ReplayMode.FORENSIC):
                                logger.warning(f"Legacy WAL detected. Disabling strict hash chaining.")
                                self._legacy_fallback_active = True
                            else:
                                raise ValueError("Legacy WAL detected in STRICT mode. Hash chaining is missing.")

                    # Cryptographic Validation
                    if not self._legacy_fallback_active:
                        stored_hash = event.pop("event_hash", None)
                        stored_prev = event.get("previous_hash")
                        
                        # Verify Chain
                        if expected_last_hash is not None and stored_prev != expected_last_hash:
                            msg = f"Chain divergence at {segment_id}:{line_num}. Expected {expected_last_hash}, got {stored_prev}"
                            if self.mode == ReplayMode.STRICT:
                                raise ValueError(msg)
                            elif self.mode == ReplayMode.SALVAGE:
                                logger.warning(f"{msg} - SALVAGE boundary reached.")
                                event["event_hash"] = stored_hash # restore
                                return
                            logger.error(msg)

                        # Verify Identity
                        actual_hash = state_hash(event)
                        if actual_hash != stored_hash:
                            msg = f"Event forgery/corruption at {segment_id}:{line_num}. Hash mismatch."
                            if self.mode == ReplayMode.STRICT:
                                raise ValueError(msg)
                            elif self.mode == ReplayMode.SALVAGE:
                                logger.warning(f"{msg} - SALVAGE boundary reached.")
                                event["event_hash"] = stored_hash # restore
                                return
                            logger.error(msg)
                            
                        # Advance Chain
                        expected_last_hash = stored_hash
                        event["event_hash"] = stored_hash  # Restore for downstream

                    # Track physical location
                    event["_segment_id"] = segment_id
                    event["_line_num"] = line_num

                    seq = event.get("sequence_id", -1)
                    if seq > min_sequence or seq == -1:
                        yield event

    def _submit_to_scheduler(self, scheduler: CausalScheduler, events: List[dict]) -> int:
        submitted = 0
        for event in events:
            msg_id = event.get("msg_id") or event.get("sequence_id") or str(id(event))
            payload = event.get("payload", {})

            causal_parents: List[str] = payload.get("causal_parents", [])
            single_parent = payload.get("causal_parent_id")
            if single_parent and single_parent not in causal_parents:
                causal_parents.append(single_parent)

            logical_clock: int = event.get("logical_clock", event.get("sequence_id", 0))
            epoch_id: int = event.get("epoch_id", 0)

            scheduler.submit(
                event_id=str(msg_id),
                payload=event,
                causal_parents=[str(p) for p in causal_parents],
                logical_clock=logical_clock,
                epoch_id=epoch_id,
            )
            submitted += 1

        return submitted

    async def execute_recovery(self, snapshot: Optional[dict], session_dir: Path, event_bus) -> bool:
        snapshot_seq = snapshot.get("sequence_id", 0) if snapshot else 0
        self.cursor = ReplayCursor(snapshot_seq)

        logger.info(f"[ReplayEngine] Starting replay from seq={snapshot_seq} mode={self.mode.name}")

        try:
            all_deltas = list(self._read_deltas(session_dir, snapshot_seq))
        except ValueError as e:
            logger.critical(f"[ReplayEngine] Recovery aborted: {e}")
            return False

        logger.info(f"[ReplayEngine] Loaded {len(all_deltas)} valid events.")

        if not all_deltas:
            return True

        scheduler = make_causal_scheduler(dispatch_fn=event_bus.publish)
        n_submitted = self._submit_to_scheduler(scheduler, all_deltas)
        
        n_dispatched = await scheduler.run_until_empty()
        logger.info(f"[ReplayEngine] Causal replay complete. Dispatched={n_dispatched} / Submitted={n_submitted}")

        if n_dispatched < n_submitted:
            msg = f"[ReplayEngine] {n_submitted - n_dispatched} events un-dispatched. Possible cycle."
            if self.mode == ReplayMode.STRICT:
                logger.critical(msg)
                return False
            logger.warning(msg)

        if all_deltas:
            last_event = all_deltas[-1]
            last_seq = last_event.get("sequence_id", snapshot_seq)
            
            # Use precise segment cursor tracking for Phase 11
            self.cursor.advance(
                event_sequence=last_seq,
                segment_id=last_event.get("_segment_id", "00000"),
                byte_offset=0, # byte offset tracking omitted from naive jsonl read
                event_index=last_event.get("_line_num", 0),
                event_hash=last_event.get("event_hash")
            )
            self.cursor.events_processed = n_dispatched

        return True

    def execute_recovery_sync(self, snapshot: Optional[dict], session_dir: Path, event_bus) -> bool:
        import asyncio
        try:
            return asyncio.run(self.execute_recovery(snapshot, session_dir, event_bus))
        except RuntimeError:
            logger.error("[ReplayEngine] Cannot run sync recovery inside async loop.")
            return False
