"""
core/ipc/binary_transport.py
Abstract layered protocol for binary transport, enforcing State Machine and Watchdogs.
"""

import time
import logging
import threading
import uuid
from typing import Optional, Callable, Dict, Any
from abc import ABC, abstractmethod

from core.contracts.runtime_events import TransportState, PROTOCOL_VERSION, MessageType
from core.ipc.frame_reader import FrameReader, FrameReadError
from core.ipc.frame_writer import FrameWriter, FrameWriteError

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 15.0


class TransportError(Exception):
    pass


class BinaryTransport(ABC):
    def __init__(self, role: str = "KERNEL"):
        self.role = role
        self.state = TransportState.DISCONNECTED
        self.session_id = str(uuid.uuid4())
        
        self._reader: Optional[FrameReader] = None
        self._writer: Optional[FrameWriter] = None
        
        self._out_seq = 0
        self._in_seq_expected = 0
        
        # Watchdogs
        self._last_heartbeat_rx_time = 0.0
        self._last_heartbeat_tx_time = 0.0
        self._last_heartbeat_seq = -1
        
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        
        self.on_message_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    @abstractmethod
    def _connect_impl(self) -> None:
        pass

    @abstractmethod
    def _disconnect_impl(self) -> None:
        pass

    @abstractmethod
    def _read_bytes(self, n: int, timeout: float) -> bytes:
        pass

    @abstractmethod
    def _write_bytes(self, data: bytes) -> None:
        pass

    @abstractmethod
    def _flush(self) -> None:
        pass

    def _transition(self, new_state: TransportState) -> None:
        logger.info(f"[Transport] State change: {self.state.value} -> {new_state.value}")
        self.state = new_state

    def start(self) -> None:
        with self._lock:
            if self.state != TransportState.DISCONNECTED:
                return
            self._transition(TransportState.CONNECTING)
            
        try:
            self._connect_impl()
        except Exception as e:
            logger.error(f"[Transport] Connection failed: {e}")
            self._transition(TransportState.DISCONNECTED)
            raise TransportError(f"Connection failed: {e}")

        self._reader = FrameReader(self._read_bytes)
        self._writer = FrameWriter(self._write_bytes, self._flush)
        
        self._transition(TransportState.HANDSHAKING)
        self._perform_handshake()
        
        self._transition(TransportState.ACTIVE)
        self._stop_event.clear()
        
        self._last_heartbeat_rx_time = time.time()
        self._last_heartbeat_tx_time = time.time()
        
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name=f"Transport_RX_{self.role}")
        self._rx_thread.start()
        
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name=f"Transport_WD_{self.role}")
        self._watchdog_thread.start()

    def stop(self) -> None:
        with self._lock:
            if self.state in (TransportState.DISCONNECTED, TransportState.QUIESCING, TransportState.TERMINATED):
                return
            self._transition(TransportState.QUIESCING)
            
        self._stop_event.set()
        
        try:
            self._disconnect_impl()
        except Exception as e:
            logger.warning(f"[Transport] Disconnect impl error: {e}")
            
        self._transition(TransportState.TERMINATED)

    def send_message(self, msg_type: str, event_type: str, payload: dict, correlation_id: str = "") -> None:
        if self.state not in (TransportState.ACTIVE, TransportState.DEGRADED):
            logger.warning(f"[Transport] Cannot send message, state is {self.state.value}")
            return
            
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
            
        with self._lock:
            seq = self._out_seq
            self._out_seq += 1
            
        try:
            payload["event_type"] = event_type  # Inject into payload for now to match old semantic
            self._writer.write_frame(
                msg_type=msg_type,
                sequence_id=seq,
                correlation_id=correlation_id,
                payload=payload
            )
            self._writer.flush()
        except FrameWriteError as e:
            logger.error(f"[Transport] Send failed: {e}")
            self._transition(TransportState.DEGRADED)

    def _perform_handshake(self) -> None:
        """
        Sends HELLO and expects HELLO in return to negotiate protocol capability.
        """
        # Send HELLO
        handshake_payload = {
            "event_type": "HELLO",
            "supported_protocols": [PROTOCOL_VERSION],
            "role": self.role,
            "session_id": self.session_id,
            "capabilities": ["binary_framing", "cbor_canonical"]
        }
        
        seq = self._out_seq
        self._out_seq += 1
        
        self._writer.write_frame(
            msg_type=MessageType.SYSTEM,
            sequence_id=seq,
            correlation_id=str(uuid.uuid4()),
            payload=handshake_payload
        )
        self._writer.flush()
        
        # Wait for HELLO response
        try:
            response = self._reader.read_frame(timeout=5.0)
            if not response:
                raise TransportError("EOF during handshake")
                
            payload = response["payload"]
            if payload.get("event_type") != "HELLO":
                raise TransportError(f"Expected HELLO, got {payload.get('event_type')}")
                
            logger.info(f"[Transport] Handshake successful with role {payload.get('role')}")
        except FrameReadError as e:
            raise TransportError(f"Handshake failed: {e}")

    def _rx_loop(self) -> None:
        while not self._stop_event.is_set() and self.state in (TransportState.ACTIVE, TransportState.DEGRADED):
            try:
                frame = self._reader.read_frame(timeout=1.0)
                if frame:
                    self._handle_frame(frame)
            except FrameReadError as e:
                if "timeout" in str(e).lower():
                    continue
                logger.error(f"[Transport] RX Error: {e}")
                self._transition(TransportState.DEGRADED)
                # Could trigger reconnect here if needed
                break
            except Exception as e:
                logger.error(f"[Transport] Unhandled RX Error: {e}")
                break

    def _handle_frame(self, frame: Dict[str, Any]) -> None:
        seq = frame["sequence_id"]
        msg_type = frame["message_type"]
        
        if msg_type == MessageType.HEARTBEAT:
            # Stale heartbeat detection
            if seq <= self._last_heartbeat_seq and seq != 0:
                logger.warning(f"[Transport] Stale heartbeat received. Expected > {self._last_heartbeat_seq}, got {seq}")
                return
            self._last_heartbeat_seq = seq
            self._last_heartbeat_rx_time = time.time()
            return
            
        # Dispatch to callback
        if self.on_message_callback:
            # Reconstruct the old dictionary structure to bridge to existing logic easily
            full_msg = {
                "protocol_version": frame["protocol_version"],
                "message_type": msg_type,
                "event_type": frame["payload"].get("event_type", "UNKNOWN"),
                "sequence_id": seq,
                "causal_parent_id": None,  # Not strictly tracked in header right now
                "payload": frame["payload"],
                "timestamp": frame["timestamp_ns"] / 1e9,
                "msg_id": frame["correlation_id"],
                "correlation_id": frame["correlation_id"]
            }
            try:
                self.on_message_callback(full_msg)
            except Exception as e:
                logger.error(f"[Transport] Callback error: {e}")

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set() and self.state in (TransportState.ACTIVE, TransportState.DEGRADED):
            now = time.time()
            
            # Send heartbeat
            if now - self._last_heartbeat_tx_time > HEARTBEAT_INTERVAL:
                try:
                    self.send_message(MessageType.HEARTBEAT, "PING", {"time": now})
                    self._last_heartbeat_tx_time = now
                except Exception:
                    pass
            
            # Check receive timeout
            if now - self._last_heartbeat_rx_time > HEARTBEAT_TIMEOUT:
                logger.error(f"[Transport] Watchdog: Heartbeat timeout! No data for {now - self._last_heartbeat_rx_time:.1f}s")
                if self.state == TransportState.ACTIVE:
                    self._transition(TransportState.DEGRADED)
            
            time.sleep(1.0)
