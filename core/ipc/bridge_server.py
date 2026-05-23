"""
core/bridge_server.py
NovaMind WebSocket IPC server — Protocol 1.0.0

Key guarantees:
  - Every outgoing message carries a monotonically increasing sequence_id.
  - Incoming msg_id duplicates are silently discarded (idempotency).
  - Incoming sequence gaps trigger bounded reconciliation, NOT immediate disconnect.
  - Protocol/schema violations always force disconnect (1003).
  - Optional chaos_mode for CI/testing injects: drops, duplicates, delays.
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

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
# Max out-of-order messages buffered before declaring desync.
_OOO_QUEUE_LIMIT = 32
# Idempotency cache: how many recent msg_ids to remember (circular).
_IDEMPOTENCY_CACHE_SIZE = 4096


class BridgeServer:
    """
    Single-client WebSocket IPC server between the Python Ecosystem and Godot.

    Architecture:
        Transport ordering  → sequence_id (monotonic int per connection)
        Semantic causality  → causal_parent_id (set by callers)
        Idempotency         → msg_id LRU cache (discard duplicates silently)
        Chaos mode          → probabilistic packet manipulation for CI

    Modes:
        validation_mode=True  → strict fail-fast on sequence gap (CI)
        validation_mode=False → bounded reconciliation queue (production)
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        chaos_mode: bool = False,
        validation_mode: bool = False,
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

        # Outgoing sequence (monotonic, per server lifetime)
        self._out_seq: int = 0

        # Incoming sequence tracking (reset per connection)
        self._in_seq_expected: int = 0
        self._ooo_queue: list = []      # buffered out-of-order messages
        self._degraded: bool = False    # True while waiting for resync

        # Idempotency cache (circular deque of seen msg_ids)
        self._seen_msg_ids: deque = deque(maxlen=_IDEMPOTENCY_CACHE_SIZE)

        # Handlers and callbacks
        self.message_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[None]]] = {}
        self.heartbeat_callback: Optional[Callable[[], dict]] = None

        # Violation callback — injected by RuntimeAuditor
        self.on_invariant_violation: Optional[Callable[[dict], None]] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def register_handler(self, msg_type: str, handler: Callable):
        self.message_handlers[msg_type] = handler

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def _handle_client(self, websocket: websockets.WebSocketServerProtocol):
        if self.connected_client is not None:
            logger.warning("Rejecting second client — only one allowed.")
            await websocket.close(1008, "Only one client allowed")
            return

        self.connected_client = websocket
        self._reset_incoming_sequence()
        logger.info(f"Godot Client connected from {websocket.remote_address}")

        try:
            async for raw in websocket:
                await self._receive(raw)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Godot Client disconnected cleanly.")
        except Exception as e:
            logger.error(f"Godot connection error: {e}")
        finally:
            self.connected_client = None
            self._reset_incoming_sequence()
            logger.info("Godot Client connection cleaned up.")

    def _reset_incoming_sequence(self):
        self._in_seq_expected = 0
        self._ooo_queue.clear()
        self._degraded = False

    # ── Incoming message pipeline ─────────────────────────────────────────────

    async def _receive(self, raw: str):
        # 1. Parse JSON
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"[Bridge] Non-JSON payload received, ignoring.")
            return

        # 2. Schema validation — always enforced
        if not validate_message(msg):
            logger.error("[Bridge] Schema violation → force disconnect (1003).")
            if self.connected_client:
                await self.connected_client.close(1003, "Protocol Validation Failed")
            self.connected_client = None
            return

        # 3. Idempotency — discard duplicates silently
        mid = msg["msg_id"]
        if mid in self._seen_msg_ids:
            logger.debug(f"[Bridge] Duplicate msg_id {mid[:8]}… discarded.")
            return
        self._seen_msg_ids.append(mid)

        # 4. Transport sequence ordering
        seq = msg["sequence_id"]
        if not await self._handle_sequence(msg, seq):
            return  # Out of order; buffered or rejected

        # 5. Dispatch
        await self._dispatch(msg)

    async def _handle_sequence(self, msg: dict, seq: int) -> bool:
        """
        Returns True if the message should be dispatched now.
        Returns False if it was buffered or dropped.

        Validation mode: strict fail-fast on gap.
        Production mode: bounded reconciliation queue.
        """
        if seq == self._in_seq_expected:
            self._in_seq_expected += 1
            # Drain any buffered OOO messages that are now in-order
            await self._drain_ooo_queue()
            return True

        if seq < self._in_seq_expected:
            # Sequence regressed — transport duplicate or replay artifact
            logger.warning(
                f"[Bridge] Sequence regression: expected {self._in_seq_expected}, got {seq}. Discarding."
            )
            return False

        # seq > expected: gap detected
        gap = seq - self._in_seq_expected
        logger.warning(f"[Bridge] Sequence gap of {gap} detected (expected {self._in_seq_expected}, got {seq}).")

        if self.validation_mode:
            logger.error("[Bridge] Validation mode: gap → force disconnect (1003).")
            if self.connected_client:
                await self.connected_client.close(1003, "Sequence Gap — Validation Mode")
            self.connected_client = None
            return False

        # Production mode: buffer and enter degraded
        if len(self._ooo_queue) >= _OOO_QUEUE_LIMIT:
            logger.error(
                f"[Bridge] OOO queue full ({_OOO_QUEUE_LIMIT} msgs). "
                "Declaring desync — closing connection."
            )
            if self.connected_client:
                await self.connected_client.close(1011, "OOO Queue Overflow — Desync")
            self.connected_client = None
            return False

        self._ooo_queue.append(msg)
        self._ooo_queue.sort(key=lambda m: m["sequence_id"])
        self._degraded = True
        logger.info(f"[Bridge] Buffered OOO message seq={seq}. Queue depth: {len(self._ooo_queue)}.")
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
        msg_type = msg["message_type"]
        event_type = msg["event_type"]

        if msg_type == MessageType.HEARTBEAT:
            # Echo back with authoritative state
            auth = {}
            if self.heartbeat_callback:
                try:
                    auth = self.heartbeat_callback()
                except Exception as e:
                    logger.error(f"[Bridge] Heartbeat callback error: {e}")
            await self.send_message(
                MessageType.HEARTBEAT,
                EventType.SYSTEM_HEARTBEAT,
                payload={"status": "pong", "authoritative_state": auth},
                causal_parent_id=msg["msg_id"],
            )
            return

        logger.info(f"[Bridge] ← {msg_type}:{event_type} seq={msg['sequence_id']}")
        handler = self.message_handlers.get(msg_type)
        if handler:
            asyncio.create_task(handler(msg))
        else:
            logger.warning(f"[Bridge] No handler for message_type '{msg_type}'")

    async def trigger_reconciliation(self, authoritative_state: dict):
        """
        Forces Godot to accept Python's truth (Python wins mismatch).
        """
        logger.warning("[Bridge] Triggering formal RECONCILIATION_REQUEST to client.")
        await self.send_message(
            msg_type="SYSTEM",
            event_type="RECONCILIATION_REQUEST",
            payload={"authoritative_state": authoritative_state}
        )
        self._degraded = True

    # ── Outgoing ──────────────────────────────────────────────────────────────

    async def send_message(
        self,
        msg_type: str,
        event_type: str,
        payload: dict = None,
        correlation_id: str = "",
        causal_parent_id: str = None,
    ) -> bool:
        if not self.connected_client:
            return False

        # Chaos: probabilistic drop (Tier 1 only — no payload mutation)
        if self.chaos_mode:
            if random.random() < 0.05:      # 5% drop
                logger.debug("[Chaos] Dropped outgoing packet.")
                return True
            if random.random() < 0.03:      # 3% duplicate
                logger.debug("[Chaos] Duplicating outgoing packet.")
                await self._emit(msg_type, event_type, payload, correlation_id, causal_parent_id)
            if random.random() < 0.02:      # 2% delay
                await asyncio.sleep(random.uniform(0.05, 0.3))

        return await self._emit(msg_type, event_type, payload, correlation_id, causal_parent_id)

    async def _emit(self, msg_type, event_type, payload, correlation_id, causal_parent_id) -> bool:
        mid = str(uuid.uuid4())
        seq = self._out_seq
        self._out_seq += 1

        msg = {
            "protocol_version": PROTOCOL_VERSION,
            "message_type": msg_type,
            "event_type": event_type,
            "sequence_id": seq,
            "causal_parent_id": causal_parent_id,
            "payload": payload or {},
            "timestamp": time.time(),  # L6-B: real Unix timestamp, not monotonic loop counter
            "msg_id": mid,
            "correlation_id": correlation_id or str(uuid.uuid4()),
        }

        if not validate_message(msg):
            logger.error(f"[Bridge] Outgoing message failed validation (seq={seq}). Dropped.")
            self._out_seq -= 1  # Rollback seq so there's no gap
            return False

        try:
            await self.connected_client.send(json.dumps(msg))
            if msg_type != MessageType.HEARTBEAT:
                logger.debug(f"[Bridge] → {msg_type}:{event_type} seq={seq}")
            return True
        except Exception as e:
            logger.error(f"[Bridge] Send failed (seq={seq}): {e}")
            return False

    def send_message_threadsafe(
        self,
        msg_type: str,
        event_type: str,
        payload: dict = None,
        correlation_id: str = "",
        causal_parent_id: str = None,
    ) -> bool:
        """
        Marshal a send from any background thread into the server's asyncio loop.
        """
        if not self.is_running or not self._loop or self._loop.is_closed():
            logger.warning(f"[Bridge] Threadsafe drop — server not ready: {msg_type}:{event_type}")
            return False
        try:
            asyncio.run_coroutine_threadsafe(
                self.send_message(msg_type, event_type, payload, correlation_id, causal_parent_id),
                self._loop,
            )
            return True
        except Exception as e:
            logger.error(f"[Bridge] Threadsafe scheduling failed: {e}")
            return False

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self):
        while self.is_running:
            await asyncio.sleep(5)
            if self.connected_client:
                payload = {"status": "ping", "degraded": self._degraded}
                if self.heartbeat_callback:
                    try:
                        payload["authoritative_state"] = self.heartbeat_callback()
                    except Exception as e:
                        logger.error(f"[Bridge] Heartbeat callback failed: {e}")
                await self.send_message(
                    MessageType.HEARTBEAT, EventType.SYSTEM_HEARTBEAT, payload=payload
                )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self.is_running = True
        self._loop = asyncio.get_running_loop()
        self.server = await websockets.serve(self._handle_client, self.host, self.port)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        mode = "CHAOS" if self.chaos_mode else ("VALIDATION" if self.validation_mode else "PRODUCTION")
        logger.info(f"[Bridge] Listening on ws://{self.host}:{self.port} [{mode} mode]")

    async def stop(self):
        self.is_running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        logger.info("[Bridge] Server stopped.")
