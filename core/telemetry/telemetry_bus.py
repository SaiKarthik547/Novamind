import logging
import queue
import threading
from enum import Enum
from typing import Callable, Optional

from core.telemetry.telemetry_event import TelemetryEvent, TelemetryClass

logger = logging.getLogger("TelemetryBus")

class TelemetryOverflowPolicy(Enum):
    DROP_EPHEMERAL = "DROP_EPHEMERAL"
    BLOCK_CRITICAL = "BLOCK_CRITICAL"
    ESCALATE_PANIC = "ESCALATE_PANIC"

class TelemetryBus:
    """
    Centralized, thread-safe telemetry stream.
    Enforces deterministic ordering, bounded queues, and backpressure policies.
    """
    def __init__(self, max_size: int = 1000):
        self._queue = queue.Queue(maxsize=max_size)
        self._lock = threading.Lock()
        
        # Subscriptions
        self._wal_forwarder: Optional[Callable[[TelemetryEvent], None]] = None
        self._sink_forwarder: Optional[Callable[[TelemetryEvent], None]] = None
        
        self._stop_event = threading.Event()
        self._dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True, name="TelemetryBus")
        
    def start(self):
        self._stop_event.clear()
        if not self._dispatch_thread.is_alive():
            self._dispatch_thread.start()
            
    def stop(self):
        self._stop_event.set()
        # Wake up queue if blocked
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._dispatch_thread.is_alive():
            self._dispatch_thread.join(timeout=2.0)

    def register_wal(self, callback: Callable[[TelemetryEvent], None]):
        with self._lock:
            self._wal_forwarder = callback
            
    def register_sink(self, callback: Callable[[TelemetryEvent], None]):
        with self._lock:
            self._sink_forwarder = callback

    def emit(self, event: TelemetryEvent) -> None:
        """Publish a telemetry event subject to overflow policies."""
        if event.telemetry_class == TelemetryClass.EPHEMERAL:
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                # DROP_EPHEMERAL policy
                pass 
                
        elif event.telemetry_class == TelemetryClass.REPLAY_CRITICAL:
            try:
                # BLOCK_CRITICAL policy: Wait up to 5 seconds
                self._queue.put(event, timeout=5.0)
            except queue.Full:
                # ESCALATE_PANIC policy
                logger.critical("Telemetry bus deadlocked on REPLAY_CRITICAL event!")
                raise RuntimeError("Telemetry bus deadlock - Panic escalated")
                
        else: # FORENSIC
            try:
                # Best effort block, drop if truly stuck to preserve system execution
                self._queue.put(event, timeout=0.1)
            except queue.Full:
                logger.warning("Dropped FORENSIC telemetry event due to backpressure")

    def _dispatch_loop(self):
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=1.0)
                if event is None:
                    continue
                    
                with self._lock:
                    wal_cb = self._wal_forwarder
                    sink_cb = self._sink_forwarder
                
                # REPLAY_CRITICAL strictly routes to WAL
                if event.telemetry_class == TelemetryClass.REPLAY_CRITICAL:
                    if wal_cb:
                        wal_cb(event)
                    else:
                        logger.error("REPLAY_CRITICAL event dropped: No WAL forwarder registered!")
                
                # FORENSIC routes to persistent JSONL Sink
                elif event.telemetry_class == TelemetryClass.FORENSIC:
                    if sink_cb:
                        sink_cb(event)
                        
                # EPHEMERAL routes nowhere right now (could go to live metrics aggregator)
                # But metrics aggregator can also just hook directly to the bus or sink.
                
                self._queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in TelemetryBus dispatch: {e}")
