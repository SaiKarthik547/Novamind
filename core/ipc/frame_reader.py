"""
core/ipc/frame_reader.py
Synchronous binary frame reader for Phase 11 IPC.

- Enforces hard read timeouts.
- Performs stream resynchronization on invalid magic bytes.
- Never allocates payload buffers before validating the header limits.
"""

import time
import logging
from typing import Callable, Optional, Dict, Any

from core.ipc.frame_codec import (
    HEADER_SIZE, unpack_frame_header, MAGIC_BYTES, 
    FrameCodecError, MAX_PAYLOAD_SIZE
)
from core.ipc.serializer import deserialize, SerializationError
from core.ipc.checksum import verify_integrity_hash

logger = logging.getLogger(__name__)

FRAME_READ_TIMEOUT = 5.0  # seconds


class FrameReadError(Exception):
    """Implementation stub"""


class FrameReader:
    def __init__(self, read_func: Callable[[int, float], bytes]):
        """
        read_func(n, timeout) should block and return exactly n bytes,
        or less if connection closes/times out.
        """
        self.read_func = read_func

    def _read_exact(self, n: int, timeout: float) -> bytes:
        start_time = time.time()
        buf = bytearray()
        while len(buf) < n:
            remaining = n - len(buf)
            time_left = timeout - (time.time() - start_time)
            if time_left <= 0:
                raise FrameReadError(f"Read timeout after {timeout}s")
                
            chunk = self.read_func(remaining, time_left)
            if not chunk:
                # EOF
                if len(buf) == 0:
                    return b""
                raise FrameReadError("Connection closed mid-frame")
            buf.extend(chunk)
        return bytes(buf)

    def _resync_stream(self, timeout: float) -> bytes:
        """
        Scans the stream one byte at a time until MAGIC_BYTES is found.
        """
        logger.warning("[FrameReader] Stream desynchronized. Scanning for magic bytes...")
        start_time = time.time()
        buf = bytearray()
        
        while True:
            time_left = timeout - (time.time() - start_time)
            if time_left <= 0:
                raise FrameReadError(f"Resync timeout after {timeout}s")
                
            b = self.read_func(1, time_left)
            if not b:
                raise FrameReadError("Connection closed during resync")
                
            buf.extend(b)
            if buf.endswith(MAGIC_BYTES):
                logger.info(f"[FrameReader] Stream resynchronized after discarding {len(buf) - 4} bytes.")
                return MAGIC_BYTES

    def read_frame(self, timeout: float = FRAME_READ_TIMEOUT) -> Optional[Dict[str, Any]]:
        """
        Reads a single binary frame synchronously.
        Returns the deserialized payload Dict plus header metadata.
        Returns None on clean EOF (no bytes read).
        Raises FrameReadError on corruption, timeout, or validation failure.
        """
        # 1. Read first 4 bytes (Magic)
        try:
            magic = self._read_exact(4, timeout)
        except FrameReadError as e:
            if "Connection closed mid-frame" in str(e):
                raise
            return None  # clean EOF or timeout on first byte
            
        if not magic:
            return None

        if magic != MAGIC_BYTES:
            # Corruption detected immediately, attempt resync
            magic = self._resync_stream(timeout)

        # 2. Read the rest of the header
        rest_of_header_len = HEADER_SIZE - 4
        rest_of_header = self._read_exact(rest_of_header_len, timeout)
        header_bytes = magic + rest_of_header
        
        try:
            header = unpack_frame_header(header_bytes)
        except FrameCodecError as e:
            logger.error(f"[FrameReader] Header validation failed: {e}")
            raise FrameReadError(f"Corrupt header: {e}")

        payload_length = header["payload_length"]
        expected_integrity = header["payload_integrity"]

        # 3. Security Boundary: We already checked payload_length against MAX_PAYLOAD_SIZE 
        # inside unpack_frame_header. Now it is safe to allocate.
        if payload_length == 0:
            payload_bytes = b""
        else:
            payload_bytes = self._read_exact(payload_length, timeout)

        # 4. Integrity Validation (BLAKE2b)
        if not verify_integrity_hash(payload_bytes, expected_integrity):
            logger.error("[FrameReader] Payload integrity checksum mismatch.")
            raise FrameReadError("Payload integrity checksum mismatch.")

        # 5. Deserialization
        try:
            payload = deserialize(payload_bytes)
        except SerializationError as e:
            logger.error(f"[FrameReader] Payload deserialization failed: {e}")
            raise FrameReadError(f"Deserialization failed: {e}")

        header["payload"] = payload
        return header