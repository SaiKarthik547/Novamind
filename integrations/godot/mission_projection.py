

from integrations.godot.godot_bridge_protocol import GodotTelemetryMessage, GodotMessageType, GodotMessagePriority
from core.execution.execution_intent import IntentStatus

class MissionProjection:
    """
    Translates raw Kernel Telemetry into UI-consumable data for Godot.
    Architecture Enforcement:
    - This class is READ-ONLY.
    - It projects truth, it never mutates truth.
    - It strips away heavy payloads that the Godot UI doesn't need to render.
    """
    
    @staticmethod
    def project_intent_status(intent_id: str, status: IntentStatus) -> GodotTelemetryMessage:
        return GodotTelemetryMessage(
            msg_type=GodotMessageType.TELEMETRY_UPDATE,
            priority=GodotMessagePriority.UI_PRIORITY,
            payload={
                "component": "IntentLifecycle",
                "intent_id": intent_id,
                "status": status.value
            }
        )
        
    @staticmethod
    def project_worker_panic(worker_id: str, reason: str) -> GodotTelemetryMessage:
        return GodotTelemetryMessage(
            msg_type=GodotMessageType.WORKER_PANIC,
            priority=GodotMessagePriority.CRITICAL_PRIORITY,
            payload={
                "worker_id": worker_id,
                "reason": reason
            }
        )
