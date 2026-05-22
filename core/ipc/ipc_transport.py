import struct
import logging
import queue
from typing import Optional
from io import BytesIO

from core.ipc.ipc_serializer import IpcSerializer
from core.ipc.worker_protocol import IpcFrame, FrameType, WorkerIdentity

logger = logging.getLogger("IpcTransport")

class IpcCorruptionError(Exception):
    pass

class IpcTransport:
    """
    Deterministic IPC Transport with framed binary protocol, backpressure,
    and partial frame recovery.
    """
    FRAME_HEADER_FMT = ">I"  # 4-byte big-endian length
    HEADER_SIZE = struct.calcsize(FRAME_HEADER_FMT)
    MAX_FRAME_SIZE = 10 * 1024 * 1024  # 10 MB limit
    MAX_QUEUE_SIZE = 1000

    def __init__(self, in_stream, out_stream):
        self.in_stream = in_stream
        self.out_stream = out_stream
        
        # Bounded queues for backpressure
        self.send_queue = queue.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self.recv_queue = queue.Queue(maxsize=self.MAX_QUEUE_SIZE)
        
        self._buffer = bytearray()

    def send_frame(self, frame: IpcFrame):
        """Encodes and sends a frame with a length prefix."""
        try:
            payload = IpcSerializer.encode(frame.dict())
            if len(payload) > self.MAX_FRAME_SIZE:
                raise ValueError(f"Frame exceeds MAX_FRAME_SIZE: {len(payload)}")
                
            header = struct.pack(self.FRAME_HEADER_FMT, len(payload))
            self.out_stream.write(header + payload)
            self.out_stream.flush()
        except Exception as e:
            logger.error(f"IPC Send Error: {e}")
            raise

    def receive_pump(self):
        """
        Reads from stream, handles partial frames, and queues completed frames.
        Returns False on EOF.
        """
        try:
            chunk = self.in_stream.read(4096)
            if not chunk:
                return False
                
            self._buffer.extend(chunk)
            
            while len(self._buffer) >= self.HEADER_SIZE:
                frame_len = struct.unpack(self.FRAME_HEADER_FMT, self._buffer[:self.HEADER_SIZE])[0]
                
                if frame_len > self.MAX_FRAME_SIZE:
                    self._buffer.clear()
                    raise IpcCorruptionError(f"Corrupt IPC Frame length: {frame_len}")
                    
                if len(self._buffer) >= self.HEADER_SIZE + frame_len:
                    # We have a full frame
                    payload = bytes(self._buffer[self.HEADER_SIZE:self.HEADER_SIZE + frame_len])
                    del self._buffer[:self.HEADER_SIZE + frame_len]
                    
                    try:
                        data = IpcSerializer.decode(payload)
                        # Reconstruct object
                        frame = IpcFrame(
                            seq_num=data["seq_num"],
                            type=FrameType(data["type"]),
                            identity=WorkerIdentity(**data["identity"]),
                            payload=data["payload"],
                            timestamp=data["timestamp"],
                            correlation_id=data["correlation_id"]
                        )
                        self.recv_queue.put_nowait(frame)
                    except queue.Full:
                        logger.error("IPC Recv Queue Full (Backpressure). Dropping frame.")
                    except Exception as e:
                        logger.error(f"Failed to decode valid frame: {e}")
                        raise IpcCorruptionError(f"Decode error: {e}")
                else:
                    break # Wait for more data
            return True
        except Exception as e:
            logger.error(f"IPC Receive Pump Error: {e}")
            return False

    def get_frame(self, block: bool = True, timeout: Optional[float] = None) -> Optional[IpcFrame]:
        try:
            return self.recv_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None
