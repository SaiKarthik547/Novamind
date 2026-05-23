"""
core/replay/event_codec.py
Abstract protocol for WAL event storage.

Phase 11 introduces this abstraction to allow seamless future migration from 
JSONL to binary CBOR/mmap segments without breaking ReplayEngine logic.
"""
from typing import Protocol, Any, Dict
import json
from core.foundation.canonical import canonical_dumps


class EventStorageCodec(Protocol):
    def encode(self, event: Dict[str, Any]) -> bytes:
        """Serializes an event dictionary into transport/storage bytes."""
        ...

    def decode(self, data: bytes) -> Dict[str, Any]:
        """Deserializes bytes into an event dictionary."""
        ...


class JsonlEventCodec:
    """
    Current implementation using JSON Lines.
    Ensures canonical deterministic formatting on encode.
    """
    def encode(self, event: Dict[str, Any]) -> bytes:
        # Append newline to signify line boundaries for JSONL
        return (canonical_dumps(event) + "\n").encode("utf-8")

    def decode(self, data: bytes) -> Dict[str, Any]:
        # JSONL decodes line by line, so decode() expects a single valid line
        return json.loads(data.decode("utf-8").strip())
