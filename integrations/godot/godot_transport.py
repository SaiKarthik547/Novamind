import logging
import queue
from typing import Optional

from integrations.godot.godot_bridge_protocol import GodotTelemetryMessage, GodotMessagePriority

logger = logging.getLogger("GodotTransport")

class GodotTransport:
    """
    Dedicated IPC Bridge for Godot visualization.
    Enforces backpressure to guarantee that Godot UI stuttering NEVER blocks Kernel Execution.
    """
    def __init__(self, max_queue_size: int = 500):
        self._queue = queue.Queue(maxsize=max_queue_size)

    def dispatch(self, message: GodotTelemetryMessage) -> None:
        """
        Sends telemetry to Godot.
        Strictly enforces priority dropping policies to preserve Kernel execution flow.
        """
        try:
            if message.priority == GodotMessagePriority.BACKGROUND_PRIORITY:
                # Drop instantly if the queue is > 50% full to save resources
                if self._queue.qsize() > (self._queue.maxsize / 2):
                    return
                self._queue.put_nowait(message)
                
            elif message.priority == GodotMessagePriority.UI_PRIORITY:
                # Standard drop if completely full
                self._queue.put_nowait(message)
                
            elif message.priority == GodotMessagePriority.CRITICAL_PRIORITY:
                # Wait briefly (e.g. 50ms) before dropping, since it's an Approval Request
                self._queue.put(message, timeout=0.05)
                
        except queue.Full:
            logger.warning(f"Godot Transport queue full. Dropped {message.msg_type.name} (Priority: {message.priority.name})")

    def read_frame(self) -> Optional[GodotTelemetryMessage]:
        """Called by the IPC listener serving Godot to fetch the next frame."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None
