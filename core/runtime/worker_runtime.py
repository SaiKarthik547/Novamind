import logging
import subprocess
import threading
import time
import uuid
import json
from typing import Dict, Optional, Callable

from core.ipc.worker_protocol import WorkerState, FrameType, WorkerIdentity, IpcFrame

logger = logging.getLogger("WorkerSupervisor")

class WorkerSupervisor:
    """
    Supervises a single isolated worker process.
    Maintains the FSM, IPC channel, and health monitoring.
    """
    def __init__(self, worker_cmd: list[str], identity: WorkerIdentity):
        self.worker_cmd = worker_cmd
        self.identity = identity
        self.state = WorkerState.BOOTING
        
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._seq_num = 0
        
        # IPC Queues/Callbacks
        self.on_message: Optional[Callable[[IpcFrame], None]] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        with self._lock:
            if self.state != WorkerState.BOOTING:
                return

            logger.info(f"Starting worker {self.identity.worker_id}...")
            # Using stdin/stdout for IPC. 
            # In a hardened system, this would be under a restricted Job Object.
            self.process = subprocess.Popen(
                self.worker_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, # For JSON framing ease. Binary for CBOR later.
                bufsize=1
            )
            
            self._monitor_thread = threading.Thread(
                target=self._io_loop,
                daemon=True,
                name=f"WorkerIO-{self.identity.worker_id[:8]}"
            )
            self._monitor_thread.start()
            
            # Send Handshake SYN
            self.send_frame(FrameType.HANDSHAKE_SYN, {"nonce": self.identity.supervisor_nonce})

    def stop(self):
        with self._lock:
            if self.state in (WorkerState.DEAD, WorkerState.TERMINATING):
                return
            self.state = WorkerState.TERMINATING
            self._stop_event.set()
            
            if self.process:
                self.send_frame(FrameType.TERMINATE, {})
                try:
                    self.process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Worker {self.identity.worker_id} hung. Killing.")
                    self.process.kill()
                    
            self.state = WorkerState.DEAD

    def _io_loop(self):
        while not self._stop_event.is_set() and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break # EOF
                
                try:
                    data = json.loads(line)
                    self._handle_incoming(data)
                except json.JSONDecodeError:
                    logger.error(f"Worker {self.identity.worker_id} sent invalid JSON IPC frame: {line.strip()}")
            except Exception as e:
                logger.error(f"Worker {self.identity.worker_id} IPC read error: {e}")
                break
                
        with self._lock:
            self.state = WorkerState.DEAD
        logger.info(f"Worker {self.identity.worker_id} process terminated.")

    def _handle_incoming(self, data: dict):
        # Convert back to enum/objects (skipping strict validation for brevity here)
        try:
            frame_type = FrameType(data["type"])
            if frame_type == FrameType.HANDSHAKE_ACK:
                with self._lock:
                    self.state = WorkerState.READY
                    logger.info(f"Worker {self.identity.worker_id} READY.")
            elif frame_type == FrameType.WORKER_PANIC:
                with self._lock:
                    self.state = WorkerState.DEGRADED
                    logger.critical(f"Worker {self.identity.worker_id} PANIC: {data.get('payload')}")
            
            if self.on_message:
                frame = IpcFrame(
                    seq_num=data["seq_num"],
                    type=frame_type,
                    identity=self.identity,
                    payload=data["payload"],
                    timestamp=data["timestamp"],
                    correlation_id=data.get("correlation_id", "")
                )
                self.on_message(frame)
        except Exception as e:
            logger.error(f"Error handling frame: {e}")

    def send_frame(self, frame_type: FrameType, payload: dict, correlation_id: str = ""):
        with self._lock:
            self._seq_num += 1
            frame = IpcFrame(
                seq_num=self._seq_num,
                type=frame_type,
                identity=self.identity,
                payload=payload,
                correlation_id=correlation_id
            )
            data_str = json.dumps(frame.dict()) + "\n"
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.write(data_str)
                    self.process.stdin.flush()
                except Exception as e:
                    logger.error(f"Failed to send to worker {self.identity.worker_id}: {e}")
                    self.state = WorkerState.DEGRADED
