import json
import logging
from typing import Any

logger = logging.getLogger("IpcSerializer")

try:
    import cbor2
    HAS_CBOR2 = True
except ImportError:
    HAS_CBOR2 = False

class IpcSerializer:
    """
    Canonical binary encoding for IPC determinism.
    Prefers cbor2, falls back to deterministic JSON if missing.
    """
    @staticmethod
    def encode(payload: dict) -> bytes:
        if HAS_CBOR2:
            return cbor2.dumps(payload)
        else:
            # Deterministic JSON
            return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')

    @staticmethod
    def decode(data: bytes) -> dict:
        if HAS_CBOR2:
            return cbor2.loads(data)
        else:
            return json.loads(data.decode('utf-8'))
