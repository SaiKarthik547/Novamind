import pytest
import math
from core.ipc.serializer import serialize, deserialize, SerializationError
from core.ipc.frame_codec import pack_frame_header, unpack_frame_header, FrameCodecError, MAGIC_BYTES
from core.contracts.runtime_events import MessageType
from core.ipc.checksum import compute_integrity_hash

def test_canonical_cbor():
    # Enforces keys are sorted and no arbitrary objects are allowed
    payload_1 = {"b": 2, "a": 1}
    payload_2 = {"a": 1, "b": 2}
    
    b1 = serialize(payload_1)
    b2 = serialize(payload_2)
    assert b1 == b2, "Serialization is not canonical (deterministic)"
    
    dec = deserialize(b1)
    assert dec == {"a": 1, "b": 2}

def test_schema_rejection():
    # Reject floats NaN/Inf
    with pytest.raises(SerializationError):
        serialize({"val": math.nan})
        
    with pytest.raises(SerializationError):
        serialize({"val": float("inf")})
        
    # Reject sets
    with pytest.raises(SerializationError):
        serialize({"val": {1, 2, 3}})
        
    # Reject non-string keys
    with pytest.raises(SerializationError):
        serialize({1: "a"})

def test_frame_codec_roundtrip():
    payload = {"command": "jump"}
    payload_bytes = serialize(payload)
    integrity = compute_integrity_hash(payload_bytes)
    
    header = pack_frame_header(
        msg_type=MessageType.COMMAND,
        sequence_id=42,
        correlation_id="123e4567-e89b-12d3-a456-426614174000",
        payload_length=len(payload_bytes),
        payload_integrity=integrity,
        flags=1
    )
    
    unpacked = unpack_frame_header(header)
    assert unpacked["message_type"] == MessageType.COMMAND
    assert unpacked["sequence_id"] == 42
    assert unpacked["flags"] == 1
    assert unpacked["payload_length"] == len(payload_bytes)
    assert unpacked["payload_integrity"] == integrity
    assert unpacked["correlation_id"] == "123e4567-e89b-12d3-a456-426614174000"

def test_frame_codec_header_checksum_validation():
    payload_bytes = serialize({"test": 1})
    integrity = compute_integrity_hash(payload_bytes)
    
    header = pack_frame_header(
        msg_type=MessageType.COMMAND,
        sequence_id=42,
        correlation_id="123e4567-e89b-12d3-a456-426614174000",
        payload_length=len(payload_bytes),
        payload_integrity=integrity
    )
    
    # Mutate header to simulate corruption
    mutated = bytearray(header)
    mutated[10] ^= 0xFF
    
    with pytest.raises(FrameCodecError, match="Header checksum mismatch"):
        unpack_frame_header(bytes(mutated))
