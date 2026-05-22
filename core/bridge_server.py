import asyncio
import json
import uuid
import logging
from typing import Dict, Any, Callable, Awaitable, Optional
import websockets

from shared.protocol.events import MessageType, validate_message

logger = logging.getLogger(__name__)

class BridgeServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.connected_client: Optional[websockets.WebSocketServerProtocol] = None
        self.server: Optional[websockets.serve] = None
        self.message_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[None]]] = {}
        self.heartbeat_callback: Optional[Callable[[], dict]] = None
        self.is_running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def register_handler(self, msg_type: str, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        self.message_handlers[msg_type] = handler

    async def _handle_client(self, websocket: websockets.WebSocketServerProtocol):
        if self.connected_client is not None:
            logger.warning("Another client attempted to connect, rejecting.")
            await websocket.close(1008, "Only one client allowed")
            return

        self.connected_client = websocket
        logger.info(f"Godot Client connected from {websocket.remote_address}")

        try:
            async for message in websocket:
                await self._process_message(message)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Godot Client disconnected cleanly")
        except Exception as e:
            logger.error(f"Godot Client connection error: {e}")
        finally:
            self.connected_client = None
            logger.info("Godot Client connection cleaned up")

    async def _process_message(self, raw_message: str):
        try:
            message = json.loads(raw_message)
            if not validate_message(message):
                logger.error("Incoming message failed schema validation. Force disconnecting Godot client.")
                if self.connected_client:
                    await self.connected_client.close(code=1003, reason="Protocol Validation Failed")
                self.connected_client = None
                return
                
            msg_type = message.get("message_type")
            event_type = message.get("event_type")
            
            if msg_type == MessageType.HEARTBEAT:
                await self.send_message(MessageType.HEARTBEAT, event_type="SYSTEM_HEARTBEAT", payload={"status": "pong"})
                return

            logger.info(f"Received {msg_type}: {event_type}")
            
            handler = self.message_handlers.get(msg_type)
            if handler:
                asyncio.create_task(handler(message))
            else:
                logger.warning(f"No handler registered for message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse incoming message: {raw_message}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def send_message(self, msg_type: str, event_type: str, payload: dict = None, correlation_id: str = "") -> bool:
        if not self.connected_client:
            logger.warning("Cannot send message, no client connected")
            return False

        from shared.protocol.events import PROTOCOL_VERSION
        message = {
            "protocol_version": PROTOCOL_VERSION,
            "message_type": msg_type,
            "event_type": event_type,
            "payload": payload or {},
            "timestamp": asyncio.get_event_loop().time(),
            "msg_id": str(uuid.uuid4()),
            "correlation_id": correlation_id or str(uuid.uuid4())
        }
        
        if not validate_message(message):
            logger.error("Attempted to send invalid message schema")
            return False

        try:
            await self.connected_client.send(json.dumps(message))
            if msg_type != MessageType.HEARTBEAT:
                logger.debug(f"Sent {msg_type}: {event_type}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    def send_message_threadsafe(self, msg_type: str, event_type: str, payload: dict = None, correlation_id: str = "") -> bool:
        """
        Thread-safe wrapper to allow background agents to emit websocket messages 
        without raising 'attached to a different loop' errors.
        """
        if not self.is_running or not self._loop:
            logger.warning(f"BridgeServer not running, dropping threadsafe message: {msg_type}:{event_type}")
            return False
            
        if self._loop.is_closed():
            return False

        try:
            asyncio.run_coroutine_threadsafe(self.send_message(msg_type, event_type, payload, correlation_id), self._loop)
            return True
        except Exception as e:
            logger.error(f"Failed to schedule threadsafe message: {e}")
            return False

    async def _heartbeat_loop(self):
        while self.is_running:
            if self.connected_client:
                payload = {"status": "ping"}
                if self.heartbeat_callback:
                    try:
                        payload["authoritative_state"] = self.heartbeat_callback()
                    except Exception as e:
                        logger.error(f"Heartbeat callback failed: {e}")
                
                await self.send_message(MessageType.HEARTBEAT, event_type="SYSTEM_HEARTBEAT", payload=payload)
            await asyncio.sleep(5) # 5 second heartbeat

    async def start(self):
        self.is_running = True
        self._loop = asyncio.get_running_loop()
        self.server = await websockets.serve(self._handle_client, self.host, self.port)
        logger.info(f"Bridge Server listening on ws://{self.host}:{self.port}")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self):
        self.is_running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        logger.info("Bridge Server stopped")
