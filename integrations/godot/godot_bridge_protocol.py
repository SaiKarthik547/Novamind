from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any

class GodotMessageType(Enum):
    TASK_CREATED = "TASK_CREATED"
    WORKER_PANIC = "WORKER_PANIC"
    APPROVAL_REQUEST = "APPROVAL_REQUEST"
    TELEMETRY_UPDATE = "TELEMETRY_UPDATE"
    # Note: These are explicitly presentation/visualization events.
    # The Game engine NEVER dictates runtime truth.

class GodotMessagePriority(Enum):
    UI_PRIORITY = "UI_PRIORITY"                 # Drop if queue full
    BACKGROUND_PRIORITY = "BACKGROUND_PRIORITY" # Drop aggressively
    CRITICAL_PRIORITY = "CRITICAL_PRIORITY"     # Buffer and send reliably (e.g., APPROVAL_REQUEST)

@dataclass
class GodotTelemetryMessage:
    msg_type: GodotMessageType
    priority: GodotMessagePriority
    payload: Dict[str, Any]
