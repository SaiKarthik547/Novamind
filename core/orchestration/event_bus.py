"""
EventBus — Async publish/subscribe for agent decoupling.
Mirrors OpenHands event-stream architecture.
Agents communicate ONLY through events — no direct calls.
"""
import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("EventBus")

REQUIRED_EVENTS = frozenset({
    "task_started", "task_completed", "task_failed", "task_retrying",
    "tool_call_start", "tool_call_end", "tool_call_error",
    "llm_call_start", "llm_call_end",
    "agent_handoff", "agent_spawned", "agent_terminated",
    "memory_read", "memory_write",
    "safety_check_passed", "safety_check_blocked",
    "human_escalation_required",
    "session_started", "session_ended",
})


class EventBus:
    """
    Thread-safe async publish/subscribe event bus.
    Stores complete event log for session replay (replay_session feature).
    """

    def __init__(self, memory_system=None):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_log: List[Dict] = []
        self._memory = memory_system
        self._lock = threading.Lock()

    async def emit(self, event_type: str, data: Dict) -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            if len(self._event_log) > 5000:
                self._event_log.pop(0)  # audit: backpressure cap
            self._event_log.append(event)

        if self._memory:
            try:
                self._memory.log_system_event(
                    event_type,
                    details=json.dumps(data, default=str)[:2000],
                    severity="info",
                )
            except Exception as exc:
                logger.debug(f"EventBus persist: {exc}")

        handlers = self._subscribers.get(event_type, [])
        if handlers:
            await asyncio.gather(
                *[_safe_call(h, event) for h in handlers],
                return_exceptions=True,
            )
        logger.debug(f"[EventBus] {event_type} — {len(handlers)} handler(s)")

    def emit_sync(self, event_type: str, data: Dict) -> None:
        """Sync wrapper for non-async callers."""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            if len(self._event_log) > 5000:
                self._event_log.pop(0)  # audit: backpressure cap
            self._event_log.append(event)

        if self._memory:
            try:
                self._memory.log_system_event(
                    event_type,
                    details=json.dumps(data, default=str)[:2000],
                )
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                pass

        for handler in self._subscribers.get(event_type, []):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(result)
                        else:
                            loop.run_until_complete(result)
                    except RuntimeError:
                        pass
            except Exception as exc:
                logger.warning(f"EventBus sync handler error: {exc}")

    def subscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def subscribe_many(self, events: List[str], handler: Callable) -> None:
        for ev in events:
            self.subscribe(ev, handler)

    def get_session_log(self) -> List[Dict]:
        with self._lock:
            return self._event_log.copy()

    def get_events_by_type(self, event_type: str) -> List[Dict]:
        with self._lock:
            return [e for e in self._event_log if e["type"] == event_type]

    def replay_session(self, session_id: str = None) -> List[Dict]:
        """Return full chronological event log for debugging/replay."""
        with self._lock:
            events = self._event_log.copy()
        if session_id:
            events = [e for e in events
                      if e.get("data", {}).get("session_id") == session_id]
        return sorted(events, key=lambda e: e["timestamp"])

    def clear_log(self) -> None:
        with self._lock:
            self._event_log.clear()


async def _safe_call(handler: Callable, event: Dict) -> None:
    try:
        result = handler(event)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.warning(f"EventBus handler raised: {exc}")


_bus: Optional[EventBus] = None


def get_event_bus(memory_system=None) -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus(memory_system=memory_system)
    elif memory_system and _bus._memory is None:
        _bus._memory = memory_system
    return _bus