"""
core/ipc/bridge_server.py

Phase 18: Godot Synchronization Boundary (CQRS & Observability Egress)
Enforces a strict non-authoritative UI. The Bridge is purely a transport adapter.
Godot observations (Egress) are loss-tolerant and decoupled via RuntimeEventStream.
Godot commands (Ingress) are fire-and-forget Intent submissions.
Reconciliation is demoted to a non-mutating synchronization request.
"""

import asyncio
import json
import time
import uuid
import random
import logging
from collections import deque
from typing import Any, Callable, Dict, Optional, Awaitable

import websockets

from shared.protocol.events import (
    MessageType, EventType, PROTOCOL_VERSION, validate_message
)
from core.runtime.runtime_event_stream import RuntimeEventStream
from core.orchestration.event_bus import get_event_bus
from core.contracts.runtime_events import ExecutionEvent, ExecutionState, SchedulerEvent

logger = logging.getLogger(__name__)

_OOO_QUEUE_LIMIT = 32
_IDEMPOTENCY_CACHE_SIZE = 4096

class BridgeServer:
    """
    CQRS WebSocket IPC server between the Python Ecosystem and Godot.
    Strictly isolated from orchestration authority.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        chaos_mode: bool = False,
        validation_mode: bool = False,
        event_stream: Optional[RuntimeEventStream] = None
    ):
        self.host = host
        self.port = port
        self.chaos_mode = chaos_mode
        self.validation_mode = validation_mode

        self.connected_client: Optional[websockets.WebSocketServerProtocol] = None
        self.server: Optional[websockets.serve] = None
        self.is_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._egress_task: Optional[asyncio.Task] = None

        self._out_seq: int = 0
        self._in_seq_expected: int = 0
        self._ooo_queue: list = []
        self._degraded: bool = False
        self._seen_msg_ids: deque = deque(maxlen=_IDEMPOTENCY_CACHE_SIZE)

        # The egress pipeline from the Orchestrator
        self._event_stream = event_stream or RuntimeEventStream()
        self._topology = get_event_bus()

        self.message_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[None]]] = {}

    def register_handler(self, msg_type: str, handler: Callable):
        self.message_handlers[msg_type] = handler

    async def _handle_client(self, websocket: websockets.WebSocketServerProtocol):
        if self.connected_client is not None:
            logger.warning("[Bridge] Rejecting second client — only one allowed.")
            await websocket.close(1008, "Only one client allowed")
            return

        self.connected_client = websocket
        self._reset_incoming_sequence()
        logger.info(f"[Bridge] Godot Client connected from {websocket.remote_address}")

        try:
            async for raw in websocket:
                await self._receive(raw)
        except websockets.exceptions.ConnectionClosed:
            logger.info("[Bridge] Godot Client disconnected cleanly.")
        except Exception as e:
            logger.error(f"[Bridge] Godot connection error: {e}")
        finally:
            self.connected_client = None
            self._reset_incoming_sequence()
            logger.info("[Bridge] Godot Client connection cleaned up.")

    def _reset_incoming_sequence(self):
        self._in_seq_expected = 0
        self._ooo_queue.clear()
        self._degraded = False

    async def _receive(self, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not validate_message(msg):
            if self.connected_client:
                await self.connected_client.close(1003, "Protocol Validation Failed")
            self.connected_client = None
            return

        mid = msg["msg_id"]
        if mid in self._seen_msg_ids:
            return
        self._seen_msg_ids.append(mid)

        seq = msg["sequence_id"]
        if not await self._handle_sequence(msg, seq):
            return

        await self._dispatch(msg)

    async def _handle_sequence(self, msg: dict, seq: int) -> bool:
        """Transport integrity bounds. Does not affect orchestration topology."""
        if seq == self._in_seq_expected:
            self._in_seq_expected += 1
            await self._drain_ooo_queue()
            return True

        if seq < self._in_seq_expected:
            return False

        if self.validation_mode:
            if self.connected_client:
                await self.connected_client.close(1003, "Sequence Gap")
            self.connected_client = None
            return False

        if len(self._ooo_queue) >= _OOO_QUEUE_LIMIT:
            if self.connected_client:
                await self.connected_client.close(1011, "OOO Queue Overflow")
            self.connected_client = None
            return False

        self._ooo_queue.append(msg)
        self._ooo_queue.sort(key=lambda m: m["sequence_id"])
        self._degraded = True
        return False

    async def _drain_ooo_queue(self):
        while self._ooo_queue:
            nxt = self._ooo_queue[0]
            if nxt["sequence_id"] == self._in_seq_expected:
                self._ooo_queue.pop(0)
                self._in_seq_expected += 1
                await self._dispatch(nxt)
            else:
                break
        if not self._ooo_queue:
            self._degraded = False

    async def _dispatch(self, msg: dict):
        """
        CQRS Ingress: Fire-and-forget.
        We do NOT wait for orchestration execution.
        Godot commands immediately become PENDING ExecutionEvents.
        """
        msg_type = msg["message_type"]
        
        if msg_type == MessageType.HEARTBEAT:
            # Simple transport pong
            await self.send_message(MessageType.HEARTBEAT, EventType.SYSTEM_HEARTBEAT, payload={"status": "pong"})
            return

        handler = self.message_handlers.get(msg_type)
        if handler:
            # We schedule it as a fire-and-forget task so we don't block the transport read loop
            asyncio.create_task(handler(msg))
        else:
            # Default CQRS submission if no specific transport handler exists
            intent_event = ExecutionEvent(
                state=ExecutionState.PENDING,
                payload=msg.get("payload", {})
            )
            self._topology.emit_sync(intent_event)

    def trigger_reconciliation(self, authoritative_state: dict):
        """
        DEMOTED: No longer mutates state or forces Godot synchronization.
        Simply submits a request to the Topology Coordinator.
        """
        logger.info("[Bridge] Demoted trigger_reconciliation called. Submitting IntentRequest.")
        sync_event = SchedulerEvent(
            action="UI_RECONCILIATION_REQUESTED",
            target_queue_id="GLOBAL",
            reason="UI requested state resync."
        )
        self._topology.emit_sync(sync_event)

    # ── Egress Pipeline ───────────────────────────────────────────────────────

    async def _egress_loop(self):
        """
        Consumes the isolated RuntimeEventStream and blasts it to Godot.
        Because RuntimeEventStream is lossy (drops on full queue), 
        Godot lag NEVER backpressures the Execution Topology.
        """
        async for event_dict in self._event_stream.subscribe():
            if not self.connected_client:
                continue
            
            # Translate topology event into transport envelope
            event_type = event_dict.get("_event_type", "UNKNOWN_EVENT")
            await self.send_message(
                msg_type="STATE_UPDATE",
                event_type=event_type,
                payload=event_dict
            )

    async def send_message(self, msg_type: str, event_type: str, payload: dict = None) -> bool:
        """Internal transport emission. Not called directly by Orchestrator anymore."""
        if not self.connected_client:
            return False

        if self.chaos_mode and random.random() < 0.05:
            return True

        mid = str(uuid.uuid4())
        seq = self._out_seq
        self._out_seq += 1

        msg = {
            "protocol_version": PROTOCOL_VERSION,
            "message_type": msg_type,
            "event_type": event_type,
            "sequence_id": seq,
            "payload": payload or {},
            "timestamp": time.time(),
            "msg_id": mid,
            "correlation_id": str(uuid.uuid4()),
        }

        try:
            await self.connected_client.send(json.dumps(msg))
            return True
        except Exception as e:
            logger.debug(f"[Bridge] Egress failed (seq={seq}): {e}")
            return False

    async def _heartbeat_loop(self):
        while self.is_running:
            await asyncio.sleep(5)
            if self.connected_client:
                await self.send_message(MessageType.HEARTBEAT, EventType.SYSTEM_HEARTBEAT, payload={"degraded": self._degraded})

    async def start(self):
        self.is_running = True
        self._loop = asyncio.get_running_loop()
        self.server = await websockets.serve(self._handle_client, self.host, self.port)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._egress_task = asyncio.create_task(self._egress_loop())
        logger.info(f"[Bridge] Listening on ws://{self.host}:{self.port}")

    async def stop(self):
        self.is_running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._egress_task:
            self._egress_task.cancel()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
