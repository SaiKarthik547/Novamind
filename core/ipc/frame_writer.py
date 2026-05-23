"""
core/ipc/frame_writer.py
Synchronous binary frame writer for Phase 11 IPC.

- Calculates checksums over canonical CBOR payloads.
- Ensures flush acknowledgment tracking for exactly-once semantics.
"""

import logging
from typing import Callable, Any

from core.ipc.frame_codec import pack_frame_header
from core.ipc.serializer import serialize
from core.ipc.checksum import compute_integrity_hash

logger = logging.getLogger(__name__)


class FrameWriteError(Exception):
    """Implementation stub"""


class FrameWriter:
    def __init__(self, write_func: Callable[[bytes], None], flush_func: Callable[[], None]):
        """
        write_func(bytes) should write bytes to the transport.
        flush_func() should block until the write buffer is fully flushed.
        """
        self.write_func = write_func
        self.flush_func = flush_func
        self._unacknowledged_writes = 0

    def write_frame(
        self,
        msg_type: str,
        sequence_id: int,
        correlation_id: str,
        payload: dict,
        flags: int = 0
    ) -> None:
        """
        Serializes, frames, and writes the message synchronously.
        """
        # 1. Serialize (Canonical CBOR + Schema Validation)
        payload_bytes = serialize(payload)
        
        # 2. Integrity Hash (BLAKE2b)
        payload_integrity = compute_integrity_hash(payload_bytes)
        payload_length = len(payload_bytes)
        
        # 3. Pack Header (with CRC32 Header Checksum)
        header_bytes = pack_frame_header(
            msg_type=msg_type,
            sequence_id=sequence_id,
            correlation_id=correlation_id,
            payload_length=payload_length,
            payload_integrity=payload_integrity,
            flags=flags
        )
        
        # 4. Write to transport
        try:
            self.write_func(header_bytes)
            if payload_length > 0:
                self.write_func(payload_bytes)
            self._unacknowledged_writes += 1
        except Exception as e:
            logger.error(f"[FrameWriter] Write failed: {e}")
            raise FrameWriteError(f"Transport write failed: {e}")

    def flush(self) -> None:
        """
        Flushes the underlying transport buffer and clears the unacknowledged write count.
        """
        if self._unacknowledged_writes > 0:
            try:
                self.flush_func()
                self._unacknowledged_writes = 0
            except Exception as e:
                logger.error(f"[FrameWriter] Flush failed: {e}")
                raise FrameWriteError(f"Transport flush failed: {e}")