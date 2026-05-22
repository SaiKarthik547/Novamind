"""
shared/protocol/events.py
Protocol 1.0.0 — NovaMind IPC contract.

Two ID systems:
  - sequence_id:      transport-layer monotonic counter per connection (ordering, replay chronology)
  - causal_parent_id: semantic parent chain (null for root events, e.g. user commands)

Ordering policy (from user feedback):
  - VALIDATION MODE  → strict fail-fast on sequence gap
  - PRODUCTION MODE  → bounded reconciliation queue, not hard disconnect
"""

import logging

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0.0"


class MessageType:
    COMMAND      = "COMMAND"
    EVENT        = "EVENT"
    STATE_UPDATE = "STATE_UPDATE"
    ERROR        = "ERROR"
    HEARTBEAT    = "HEARTBEAT"
    SYSTEM       = "SYSTEM"

    _ALL = {COMMAND, EVENT, STATE_UPDATE, ERROR, HEARTBEAT, SYSTEM}


class EventType:
    USER_COMMAND_ISSUED    = "USER_COMMAND_ISSUED"
    AGENT_TOOL_CALL        = "AGENT_TOOL_CALL"
    AGENT_TASK_STARTED     = "AGENT_TASK_STARTED"
    AGENT_TASK_COMPLETED   = "AGENT_TASK_COMPLETED"
    AGENT_TASK_FAILED      = "AGENT_TASK_FAILED"
    AGENT_LIFECYCLE_CREATED   = "AGENT_LIFECYCLE_CREATED"
    AGENT_LIFECYCLE_DESTROYED = "AGENT_LIFECYCLE_DESTROYED"
    SYSTEM_HEARTBEAT       = "SYSTEM_HEARTBEAT"
    SCENE_LOAD             = "SCENE_LOAD"
    INVARIANT_VIOLATION    = "INVARIANT_VIOLATION"
    STATE_DIVERGENCE       = "STATE_DIVERGENCE"
    RECONCILIATION_REQUEST = "RECONCILIATION_REQUEST"
    RECONCILIATION_RESPONSE= "RECONCILIATION_RESPONSE"
    REPLAY_SYNC            = "REPLAY_SYNC"

    _ALL = {
        USER_COMMAND_ISSUED, AGENT_TOOL_CALL, AGENT_TASK_STARTED,
        AGENT_TASK_COMPLETED, AGENT_TASK_FAILED, AGENT_LIFECYCLE_CREATED,
        AGENT_LIFECYCLE_DESTROYED, SYSTEM_HEARTBEAT, SCENE_LOAD,
        INVARIANT_VIOLATION, STATE_DIVERGENCE, RECONCILIATION_REQUEST,
        RECONCILIATION_RESPONSE, REPLAY_SYNC
    }


_REQUIRED_KEYS = frozenset({
    "protocol_version", "message_type", "event_type",
    "sequence_id", "causal_parent_id",
    "payload", "timestamp", "msg_id", "correlation_id",
})


def validate_message(msg: dict) -> bool:
    """
    Validate an IPC message against Protocol 1.0.0.
    Returns True if valid, False otherwise (caller decides policy).
    """
    missing = _REQUIRED_KEYS - msg.keys()
    if missing:
        logger.error(f"[Protocol] Missing required keys: {missing}")
        return False

    if msg["protocol_version"] != PROTOCOL_VERSION:
        logger.error(
            f"[Protocol] Version mismatch: got '{msg['protocol_version']}', "
            f"expected '{PROTOCOL_VERSION}'"
        )
        return False

    if msg["message_type"] not in MessageType._ALL:
        logger.error(f"[Protocol] Unknown message_type: '{msg['message_type']}'")
        return False

    if msg["event_type"] not in EventType._ALL:
        logger.error(f"[Protocol] Unknown event_type: '{msg['event_type']}'")
        return False

    if not isinstance(msg["sequence_id"], int) or msg["sequence_id"] < 0:
        logger.error(f"[Protocol] Invalid sequence_id: {msg['sequence_id']!r}")
        return False

    # causal_parent_id may be None (root event) or a string UUID
    if msg["causal_parent_id"] is not None and not isinstance(msg["causal_parent_id"], str):
        logger.error(f"[Protocol] Invalid causal_parent_id type: {type(msg['causal_parent_id'])}")
        return False

    if not isinstance(msg["payload"], dict):
        logger.error(f"[Protocol] payload must be a dict, got {type(msg['payload'])}")
        return False

    return True
