import sys
import json
import logging
import traceback
from typing import Dict, Any

# Ensure it can find the core module when run as a script
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ipc.worker_protocol import FrameType, WorkerIdentity, IpcFrame

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WorkerBase")

class WorkerBase:
    """
    Base class for isolated effect executors.
    Listens on stdin for execution requests, dispatches them, and replies on stdout.
    """
    def __init__(self):
        self._seq_num = 0
        self.identity = WorkerIdentity() # Will be populated by handshake
        self._running = True

    def _send_frame(self, frame_type: int, payload: dict, correlation_id: str = ""):
        self._seq_num += 1
        frame = {
            "seq_num": self._seq_num,
            "type": frame_type,
            "identity": self.identity.dict(),
            "payload": payload,
            "timestamp": 0.0, # Not strictly needed from worker side in simple setup
            "correlation_id": correlation_id
        }
        sys.stdout.write(json.dumps(frame) + "\n")
        sys.stdout.flush()

    def handle_request(self, payload: dict) -> dict:
        """Override in subclasses to perform actual work."""
        raise NotImplementedError("Subclasses must implement handle_request")

    def run(self):
        logger.info("Worker started, awaiting handshake...")
        for line in sys.stdin:
            if not self._running:
                break
            
            try:
                data = json.loads(line)
                frame_type = data["type"]
                payload = data.get("payload", {})
                correlation_id = data.get("correlation_id", "")
                
                if frame_type == FrameType.HANDSHAKE_SYN.value:
                    self.identity.supervisor_nonce = payload.get("nonce", "")
                    # Send ACK
                    self._send_frame(FrameType.HANDSHAKE_ACK.value, {}, correlation_id)
                    logger.info("Handshake complete.")
                    
                elif frame_type == FrameType.EXECUTE_REQUEST.value:
                    try:
                        result = self.handle_request(payload)
                        self._send_frame(FrameType.EXECUTE_RESULT.value, {"success": True, "result": result}, correlation_id)
                    except Exception as e:
                        logger.error(f"Execution error: {e}")
                        self._send_frame(FrameType.EXECUTE_RESULT.value, {"success": False, "error": str(e), "trace": traceback.format_exc()}, correlation_id)
                        
                elif frame_type == FrameType.TERMINATE.value:
                    logger.info("Termination requested.")
                    self._running = False
                    break
                    
            except Exception as e:
                logger.error(f"Worker protocol error: {e}")
                self._send_frame(FrameType.WORKER_PANIC.value, {"error": str(e)})
                
        logger.info("Worker exiting.")
        sys.exit(0)
