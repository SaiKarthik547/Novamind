"""
core/canonical.py
Deterministic canonical serialization for NovaMind.

Why this exists:
  Replay validation and divergence detection require that identical logical
  states produce identical byte representations regardless of:
    - dict insertion order
    - floating-point repr differences (timestamps truncated to ms)
    - runtime environment

Rules:
  - Keys are sorted recursively.
  - Float timestamps are truncated to 3 decimal places (millisecond resolution).
  - None → JSON null (Python default).
  - Output is UTF-8 encoded with no extra whitespace.
  - SHA-256 hash is hex-encoded.
"""

import hashlib
import json
import math
from typing import Any


def _canonicalize(obj: Any) -> Any:
    """Recursively prepare an object for deterministic serialization."""
    if isinstance(obj, dict):
        return {k: _canonicalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None  # Explicitly block non-finite floats
        return round(obj, 3)  # ms-resolution determinism
    return obj


def canonical_dumps(obj: Any) -> str:
    """
    Returns a deterministic JSON string for any dict/list.
    Sorted keys, no whitespace, UTF-8 safe.
    """
    return json.dumps(_canonicalize(obj), separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(obj: Any) -> bytes:
    """Returns canonical_dumps encoded as UTF-8 bytes."""
    return canonical_dumps(obj).encode("utf-8")


def state_hash(obj: Any) -> str:
    """
    Returns a hex SHA-256 digest of the canonical serialization of obj.
    Used as a deterministic checkpoint for replay validation and
    divergence scoring between Python authoritative state and Godot
    observed state.
    """
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()
