import asyncio
import logging
from typing import AsyncGenerator, Dict, Any

logger = logging.getLogger("RuntimeEventStream")

class RuntimeEventStream:
    """
    Phase 15: Read-only Observational Event Stream for UI and Telemetry.
    Prevents UI components from interacting mutably with the Runtime,
    ensuring deterministic execution is completely isolated from observational yields.
    """
    
    def __init__(self):
        # We use an asyncio Queue to decouple production of events 
        # from their consumption by the UI.
        self._queues = []
        
    def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        Emits an event to all connected observational streams.
        Non-blocking. Does NOT yield to the asyncio event loop.
        """
        event = {
            "type": event_type,
            "payload": payload
        }
        for q in self._queues:
            # put_nowait ensures the runtime never blocks waiting for the UI
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event stream queue is full. Dropping observational event.")

    async def subscribe(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Allows the UI (e.g. Godot) to subscribe to runtime events
        without having references to the internal execution state.
        """
        q = asyncio.Queue(maxsize=1000)
        self._queues.append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self._queues.remove(q)
