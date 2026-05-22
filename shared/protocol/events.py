import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0.0"

class MessageType:
    COMMAND = "COMMAND"
    EVENT = "EVENT"
    STATE_UPDATE = "STATE_UPDATE"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    SYSTEM = "SYSTEM"

class EventType:
    USER_COMMAND_ISSUED = "USER_COMMAND_ISSUED"
    AGENT_TOOL_CALL = "AGENT_TOOL_CALL"
    AGENT_TASK_STARTED = "AGENT_TASK_STARTED"
    AGENT_TASK_COMPLETED = "AGENT_TASK_COMPLETED"
    AGENT_TASK_FAILED = "AGENT_TASK_FAILED"
    AGENT_LIFECYCLE_CREATED = "AGENT_LIFECYCLE_CREATED"
    AGENT_LIFECYCLE_DESTROYED = "AGENT_LIFECYCLE_DESTROYED"
    SYSTEM_HEARTBEAT = "SYSTEM_HEARTBEAT"
    SCENE_LOAD = "SCENE_LOAD"

def validate_message(msg: dict) -> bool:
    """
    Validates an outgoing or incoming message against the schema.
    Returns True if valid, False if invalid.
    """
    required_keys = {"protocol_version", "message_type", "event_type", "payload", "timestamp", "msg_id", "correlation_id"}
    if not required_keys.issubset(msg.keys()):
        missing = required_keys - msg.keys()
        logger.error(f"Message missing required keys: {missing}")
        return False
        
    if msg["protocol_version"] != PROTOCOL_VERSION:
        logger.error(f"Protocol mismatch: got {msg['protocol_version']}, expected {PROTOCOL_VERSION}")
        return False
        
    valid_msg_types = {getattr(MessageType, attr) for attr in dir(MessageType) if not attr.startswith("__")}
    valid_event_types = {getattr(EventType, attr) for attr in dir(EventType) if not attr.startswith("__")}
    
    if msg["message_type"] not in valid_msg_types:
        logger.error(f"Invalid message_type: {msg['message_type']}")
        return False
        
    if msg["event_type"] not in valid_event_types:
        logger.error(f"Invalid event_type: {msg['event_type']}")
        return False
        
    return True
