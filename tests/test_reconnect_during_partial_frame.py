import pytest
from core.ipc.frame_reader import FrameReader, FrameReadError
from core.ipc.frame_writer import FrameWriter
from core.contracts.runtime_events import MessageType

def test_partial_frame_truncation_aborts_safely():
    # 1. Write full frame to memory
    buf = bytearray()
    writer = FrameWriter(lambda b: buf.extend(b), lambda: None)
    writer.write_frame(MessageType.COMMAND, sequence_id=1, correlation_id="123e4567-e89b-12d3-a456-426614174000", payload={"a": 1})
    
    # 2. Truncate it
    truncated_buf = bytes(buf[:50]) # Header is 83 bytes, so it's truncated mid-header
    
    read_cursor = [0]
    def mock_read(n, timeout):
        chunk = truncated_buf[read_cursor[0]:read_cursor[0]+n]
        read_cursor[0] += len(chunk)
        return chunk

    reader = FrameReader(mock_read)
    
    # 3. Read it - should raise connection closed
    with pytest.raises(FrameReadError, match="Connection closed mid-frame"):
        reader.read_frame(timeout=0.1)

def test_corrupt_residue_resync():
    # 1. Corrupt residue
    residue = b"GARBAGE_DATA_FROM_DEAD_CONNECTION"
    
    # 2. Add valid frame after it
    buf = bytearray(residue)
    writer = FrameWriter(lambda b: buf.extend(b), lambda: None)
    writer.write_frame(MessageType.EVENT, sequence_id=2, correlation_id="123e4567-e89b-12d3-a456-426614174000", payload={"b": 2})
    
    stream = bytes(buf)
    read_cursor = [0]
    def mock_read(n, timeout):
        chunk = stream[read_cursor[0]:read_cursor[0]+n]
        read_cursor[0] += len(chunk)
        return chunk
        
    reader = FrameReader(mock_read)
    
    # 3. Reading should silently consume the residue, resync on NMIP, and return the valid frame!
    frame = reader.read_frame(timeout=1.0)
    assert frame is not None
    assert frame["sequence_id"] == 2
    assert frame["message_type"] == MessageType.EVENT
    assert frame["payload"] == {"b": 2}
