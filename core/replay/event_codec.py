"""
core/replay/event_codec.py
Abstract protocol for WAL event storage.

Phase 11 introduces this abstraction to allow seamless future migration from 
JSONL to binary CBOR/mmap segments without breaking ReplayEngine logic.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict , Protocol
import json
from core.foundation.canonical import canonical_dumps


class EventStorageCodec(ABC):
    @abstractmethod
    def encode(self, event: Dict[str, Any]) -> bytes:
        """Serializes an event dictionary into transport/storage bytes."""
        raise NotImplementedError("Subclasses must implement encode()")

    @abstractmethod
    def decode(self, data: bytes) -> Dict[str, Any]:
        """Deserializes bytes into an event dictionary."""
        raise NotImplementedError("Subclasses must implement decode()")


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
