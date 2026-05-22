import asyncio
import json
import uuid
import logging
from typing import Dict, Any, Callable, Awaitable, Optional
import websockets

logger = logging.getLogger(__name__)

class MessageType:
    COMMAND = "COMMAND"
    EVENT = "EVENT"
    STATE_UPDATE = "STATE_UPDATE"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    SYSTEM = "SYSTEM"

class BridgeServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.connected_client: Optional[websockets.WebSocketServerProtocol] = None
        self.server: Optional[websockets.serve] = None
        self.message_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[None]]] = {}
        self.is_running = False
        self._heartbeat_task: Optional[asyncio.Task] = None

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
            data = json.loads(raw_message)
            msg_type = data.get("type")
            action = data.get("action")
            
            if msg_type == MessageType.HEARTBEAT:
                # Echo heartbeat back
                await self.send_message(MessageType.HEARTBEAT, action="pong")
                return

            logger.info(f"Received {msg_type}: {action}")
            
            handler = self.message_handlers.get(msg_type)
            if handler:
                asyncio.create_task(handler(data))
            else:
                logger.warning(f"No handler registered for message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse incoming message: {raw_message}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def send_message(self, msg_type: str, action: str, payload: dict = None) -> bool:
        if not self.connected_client:
            logger.warning("Cannot send message, no client connected")
            return False

        message = {
            "type": msg_type,
            "action": action,
            "payload": payload or {},
            "timestamp": asyncio.get_event_loop().time(),
            "msg_id": str(uuid.uuid4())
        }

        try:
            await self.connected_client.send(json.dumps(message))
            if msg_type != MessageType.HEARTBEAT:
                logger.debug(f"Sent {msg_type}: {action}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def _heartbeat_loop(self):
        while self.is_running:
            if self.connected_client:
                await self.send_message(MessageType.HEARTBEAT, action="ping")
            await asyncio.sleep(5) # 5 second heartbeat

    async def start(self):
        self.is_running = True
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
