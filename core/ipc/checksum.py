"""
core/ipc/checksum.py
Dual Checksum Strategy for Phase 11 IPC.

- CRC32: Used strictly for fast transport corruption detection.
- BLAKE2b: Used for authoritative semantic integrity hashing (WAL/Replay safe).
"""

import zlib
import hashlib


def compute_transport_checksum(data: bytes) -> int:
    """
    Computes a CRC32 checksum for transport corruption scanning.
    Returns a 32-bit unsigned integer.
    """
    return zlib.crc32(data) & 0xFFFFFFFF


def verify_transport_checksum(data: bytes, expected_checksum: int) -> bool:
    """
    Verifies that the CRC32 checksum of data matches expected_checksum.
    """
    return compute_transport_checksum(data) == expected_checksum


def compute_integrity_hash(data: bytes) -> bytes:
    """
    Computes a BLAKE2b hash (32 bytes) for authoritative integrity validation.
    Used for WAL recording and replay deterministic equivalence.
    """
    return hashlib.blake2b(data, digest_size=32).digest()


def verify_integrity_hash(data: bytes, expected_hash: bytes) -> bool:
    """
    Verifies the BLAKE2b hash of the data matches the expected 32-byte hash.
    """
    return compute_integrity_hash(data) == expected_hash
