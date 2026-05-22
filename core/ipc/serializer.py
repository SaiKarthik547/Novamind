"""
core/ipc/serializer.py
Canonical Serializer Abstraction using CBOR.

Rules enforced:
1. Canonical CBOR encoding (sorted keys, deterministic size).
2. Deep schema validation before serialization.
3. No arbitrary objects, classes, or implicit encodings.
4. Floats must not be NaN or Infinity.
"""

import cbor2
import math
from typing import Any


class SerializationError(Exception):
    pass


def _validate_schema(obj: Any, path: str = "$") -> None:
    """
    Recursively validates that the object only contains allowed primitive types.
    Allowed: dict, list, int, str, bool, bytes, None.
    Rejects float NaN and Infinity.
    """
    if obj is None:
        return
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, int):
        return
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise SerializationError(f"Float NaN or Infinity not allowed at {path}")
        return
    elif isinstance(obj, str):
        return
    elif isinstance(obj, bytes):
        return
    elif isinstance(obj, list) or isinstance(obj, tuple):
        for idx, item in enumerate(obj):
            _validate_schema(item, f"{path}[{idx}]")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise SerializationError(f"Dictionary keys must be strings. Found {type(key)} at {path}")
            _validate_schema(value, f"{path}.{key}")
    else:
        raise SerializationError(f"Prohibited type {type(obj)} found at {path}")


def serialize(obj: dict) -> bytes:
    """
    Validates and canonicalizes the payload into CBOR bytes.
    """
    if not isinstance(obj, dict):
        raise SerializationError("Root payload must be a dictionary.")
    
    _validate_schema(obj)
    
    try:
        # Canonical flag enforces sorted keys and deterministic lengths
        return cbor2.dumps(obj, canonical=True)
    except Exception as e:
        raise SerializationError(f"CBOR serialization failed: {e}")


def deserialize(data: bytes) -> dict:
    """
    Deserializes CBOR bytes back into a payload.
    Validates the structure post-deserialization.
    """
    try:
        obj = cbor2.loads(data)
    except Exception as e:
        raise SerializationError(f"CBOR deserialization failed: {e}")
        
    if not isinstance(obj, dict):
        raise SerializationError("Deserialized root payload is not a dictionary.")
        
    _validate_schema(obj)
    return obj
