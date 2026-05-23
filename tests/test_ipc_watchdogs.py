import pytest
import time
from core.ipc.binary_transport import BinaryTransport, TransportState
from core.contracts.runtime_events import MessageType

class DummyTransport(BinaryTransport):
    def __init__(self):
        super().__init__()
        self.in_buffer = b""
        self.out_buffer = b""
        
    def _connect_impl(self):
        """Implementation stub"""
        
    def _disconnect_impl(self):
        """Implementation stub"""
        
    def _read_bytes(self, n, timeout):
        start = time.time()
        while len(self.in_buffer) < n:
            if time.time() - start > timeout:
                return b""
            time.sleep(0.01)
        chunk = self.in_buffer[:n]
        self.in_buffer = self.in_buffer[n:]
        return chunk
        
    def _write_bytes(self, data):
        self.out_buffer += data
        
    def _flush(self):
        """Implementation stub"""

def test_stale_heartbeat_rejection():
    # Construct a dummy transport
    transport = DummyTransport()
    # Mock states
    transport.state = TransportState.ACTIVE
    transport._last_heartbeat_seq = 10
    
    # Send older heartbeat (seq=5)
    # the frame reader expects a full binary payload, so let's just test _handle_frame directly
    frame = {
        "sequence_id": 5,
        "message_type": MessageType.HEARTBEAT,
        "protocol_version": "1.0.0",
        "payload": {},
        "timestamp_ns": 0,
        "correlation_id": ""
    }
    
    transport._handle_frame(frame)
    
    # It should be rejected, meaning _last_heartbeat_seq shouldn't drop
    assert transport._last_heartbeat_seq == 10
    
    # Now send valid heartbeat
    frame["sequence_id"] = 11
    transport._handle_frame(frame)
    assert transport._last_heartbeat_seq == 11