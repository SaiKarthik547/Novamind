"""
core/ipc/frame_codec.py
Binary framing codec for Phase 11 IPC.

Header Layout (83 bytes total):
[Magic]           4 bytes (ASCII 'NMIP')
[Version]         3 bytes (Major, Minor, Patch)
[HeaderLength]    2 bytes (uint16)
[FrameType]       1 byte (uint8 mapping to MessageType)
[Flags]           1 byte (uint8)
[SequenceID]      8 bytes (uint64)
[CorrelationID]   16 bytes (UUID bytes)
[TimestampNS]     8 bytes (uint64)
[PayloadLength]   4 bytes (uint32)
[PayloadIntegrity]32 bytes (BLAKE2b digest)
[HeaderChecksum]  4 bytes (uint32 CRC32)

Followed by Payload (CBOR encoded bytes).
"""

import struct
import uuid
import time
from typing import Dict, Any, Tuple

from core.contracts.runtime_events import PROTOCOL_VERSION, MessageType
from core.ipc.checksum import compute_transport_checksum

MAGIC_BYTES = b"NMIP"
HEADER_FORMAT = ">4s BBB H B B Q 16s Q I 32s I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_PAYLOAD_SIZE = 16 * 1024 * 1024  # 16 MB

class FrameTypeEnum:
    UNKNOWN = 0
    COMMAND = 1
    EVENT = 2
    STATE_UPDATE = 3
    ERROR = 4
    HEARTBEAT = 5
    SYSTEM = 6

_MSG_TYPE_TO_ENUM = {
    MessageType.COMMAND: FrameTypeEnum.COMMAND,
    MessageType.EVENT: FrameTypeEnum.EVENT,
    MessageType.STATE_UPDATE: FrameTypeEnum.STATE_UPDATE,
    MessageType.ERROR: FrameTypeEnum.ERROR,
    MessageType.HEARTBEAT: FrameTypeEnum.HEARTBEAT,
    MessageType.SYSTEM: FrameTypeEnum.SYSTEM,
}
_ENUM_TO_MSG_TYPE = {v: k for k, v in _MSG_TYPE_TO_ENUM.items()}


class FrameCodecError(Exception):
    """Implementation stub"""


def parse_protocol_version(ver_str: str) -> Tuple[int, int, int]:
    try:
        parts = [int(x) for x in ver_str.split(".")]
        return parts[0], parts[1], parts[2]
    except (ValueError, IndexError):
        return 0, 0, 0


def format_protocol_version(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def pack_frame_header(
    msg_type: str,
    sequence_id: int,
    correlation_id: str,
    payload_length: int,
    payload_integrity: bytes,
    flags: int = 0,
    timestamp_ns: int = None
) -> bytes:
    """
    Packs the binary header. The header checksum is computed and appended.
    """
    if payload_length > MAX_PAYLOAD_SIZE:
        raise FrameCodecError(f"Payload size {payload_length} exceeds 16MB limit.")
        
    major, minor, patch = parse_protocol_version(PROTOCOL_VERSION)
    frame_type_val = _MSG_TYPE_TO_ENUM.get(msg_type, FrameTypeEnum.UNKNOWN)
    
    if timestamp_ns is None:
        timestamp_ns = time.time_ns()
        
    try:
        corr_bytes = uuid.UUID(correlation_id).bytes
    except ValueError:
        corr_bytes = b'\x00' * 16  # fallback if not a valid UUID string

    # Pack everything EXCEPT the header checksum (use 0 for now)
    header_without_checksum = struct.pack(
        ">4s BBB H B B Q 16s Q I 32s",
        MAGIC_BYTES,
        major, minor, patch,
        HEADER_SIZE,
        frame_type_val,
        flags,
        sequence_id,
        corr_bytes,
        timestamp_ns,
        payload_length,
        payload_integrity
    )

    # Compute CRC32 over the header_without_checksum
    header_checksum = compute_transport_checksum(header_without_checksum)

    # Pack the final header WITH the checksum
    header = struct.pack(
        HEADER_FORMAT,
        MAGIC_BYTES,
        major, minor, patch,
        HEADER_SIZE,
        frame_type_val,
        flags,
        sequence_id,
        corr_bytes,
        timestamp_ns,
        payload_length,
        payload_integrity,
        header_checksum
    )
    return header


def unpack_frame_header(data: bytes) -> Dict[str, Any]:
    """
    Unpacks and validates a binary header.
    Returns a dict containing the parsed header fields.
    Raises FrameCodecError on validation failure.
    """
    if len(data) < HEADER_SIZE:
        raise FrameCodecError(f"Insufficient data for header. Expected {HEADER_SIZE}, got {len(data)}.")
        
    try:
        unpacked = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    except struct.error as e:
        raise FrameCodecError(f"Failed to unpack header: {e}")

    (
        magic, major, minor, patch, hdr_len, frame_type_val, flags, 
        sequence_id, corr_bytes, timestamp_ns, payload_length, 
        payload_integrity, header_checksum
    ) = unpacked

    if magic != MAGIC_BYTES:
        raise FrameCodecError(f"Invalid magic bytes: expected {MAGIC_BYTES}, got {magic}")

    # Validate Header Checksum
    header_without_checksum = data[:HEADER_SIZE - 4]
    expected_checksum = compute_transport_checksum(header_without_checksum)
    if header_checksum != expected_checksum:
        raise FrameCodecError(f"Header checksum mismatch. Expected {expected_checksum}, got {header_checksum}.")

    if payload_length > MAX_PAYLOAD_SIZE:
        raise FrameCodecError(f"Payload length {payload_length} exceeds 16MB limit.")

    protocol_ver = format_protocol_version(major, minor, patch)
    msg_type = _ENUM_TO_MSG_TYPE.get(frame_type_val, "UNKNOWN")
    correlation_id = str(uuid.UUID(bytes=corr_bytes))

    return {
        "protocol_version": protocol_ver,
        "header_length": hdr_len,
        "message_type": msg_type,
        "flags": flags,
        "sequence_id": sequence_id,
        "correlation_id": correlation_id,
        "timestamp_ns": timestamp_ns,
        "payload_length": payload_length,
        "payload_integrity": payload_integrity,
        "header_checksum": header_checksum,
    }