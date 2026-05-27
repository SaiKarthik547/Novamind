"""
core/runtime/runtime_event_stream.py

Phase 15/16: Observability Egress Layer
Purely read-only egress for UI (Godot) and telemetry.
Wired directly to the RuntimeEventTopologyCoordinator.
Strictly enforces loss-tolerance: UI lag must NEVER cause backpressure on the Execution Kernel.
"""

import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, Type
import json
from dataclasses import asdict

from core.contracts.runtime_events import RuntimeEvent
from core.orchestration.event_bus import get_event_bus

logger = logging.getLogger("RuntimeEventStream")

class RuntimeEventStream:
    """
    Read-only Observational Event Stream for UI and Telemetry.
    Prevents UI components from interacting mutably with the Runtime,
    ensuring deterministic execution is completely isolated from observational yields.
    """
    
    def __init__(self):
        self._queues = []
        self._topology = get_event_bus()
        
        # Subscribe to all RuntimeEvents to broadcast them out to observability clients
        self._topology.subscribe(RuntimeEvent, self._on_topology_event)
        
    def _on_topology_event(self, event: RuntimeEvent) -> None:
        """
        Callback from the Event Topology Coordinator.
        Transforms the typed dataclass into a serialized dict for UI consumption.
        """
        try:
            payload = asdict(event)
            # Add the exact class name for UI deserialization switching
            payload["_event_type"] = event.__class__.__name__
            self.broadcast(payload)
        except Exception as e:
            logger.debug(f"[RuntimeEventStream] Serialization failed for observability: {e}")

    def broadcast(self, payload: Dict[str, Any]) -> None:
        """
        Emits an event to all connected observational streams.
        Non-blocking. Does NOT yield to the asyncio event loop.
        Loss-Tolerant: Drops events if UI queues are full.
        """
        for q in self._queues:
            try:
                # put_nowait ensures the runtime never blocks waiting for the UI
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # IMPORTANT: Observability must be loss-tolerant. 
                # If telemetry fills up, we drop it to save the orchestration kernel.
                pass

    async def subscribe(self) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Allows the UI (e.g. Godot) to subscribe to runtime events
        without having references to the internal execution state.
        """
        q = asyncio.Queue(maxsize=1000) # Strict boundary to prevent memory explosion
        self._queues.append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self._queues.remove(q)
