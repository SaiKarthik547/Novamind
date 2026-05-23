import unittest

from integrations.godot.godot_bridge_protocol import GodotTelemetryMessage, GodotMessageType, GodotMessagePriority
from integrations.godot.godot_transport import GodotTransport
from integrations.godot.mission_projection import MissionProjection
from core.execution.execution_intent import IntentStatus

class TestGodotBridge(unittest.TestCase):
    def test_mission_projection_formatting(self):
        msg = MissionProjection.project_intent_status("test-intent-123", IntentStatus.EXECUTING)
        self.assertEqual(msg.msg_type, GodotMessageType.TELEMETRY_UPDATE)
        self.assertEqual(msg.priority, GodotMessagePriority.UI_PRIORITY)
        self.assertEqual(msg.payload["intent_id"], "test-intent-123")
        self.assertEqual(msg.payload["status"], "EXECUTING")

        msg2 = MissionProjection.project_worker_panic("worker-99", "OOM")
        self.assertEqual(msg2.msg_type, GodotMessageType.WORKER_PANIC)
        self.assertEqual(msg2.priority, GodotMessagePriority.CRITICAL_PRIORITY)
        self.assertEqual(msg2.payload["worker_id"], "worker-99")

    def test_godot_transport_backpressure(self):
        # Extremely small queue for testing
        transport = GodotTransport(max_queue_size=4)
        
        bg_msg = GodotTelemetryMessage(GodotMessageType.TELEMETRY_UPDATE, GodotMessagePriority.BACKGROUND_PRIORITY, {})
        ui_msg = GodotTelemetryMessage(GodotMessageType.TELEMETRY_UPDATE, GodotMessagePriority.UI_PRIORITY, {})
        crit_msg = GodotTelemetryMessage(GodotMessageType.WORKER_PANIC, GodotMessagePriority.CRITICAL_PRIORITY, {})

        # Fill 50%
        transport.dispatch(ui_msg)
        transport.dispatch(ui_msg)
        self.assertEqual(transport._queue.qsize(), 2)
        
        # Background should instantly drop because qsize > maxsize / 2 (2 > 2 is False, 3 > 2 is True)
        # Wait, maxsize/2 = 2.0. If qsize() is 3, bg drops.
        transport.dispatch(bg_msg)
        self.assertEqual(transport._queue.qsize(), 3)
        
        # Now > 50% full (3 > 2)
        transport.dispatch(bg_msg)
        # Background should be dropped silently
        self.assertEqual(transport._queue.qsize(), 3)
        
        # UI can still fill up to 4
        transport.dispatch(ui_msg)
        self.assertEqual(transport._queue.qsize(), 4)
        
        # Queue full. Next UI drops silently.
        transport.dispatch(ui_msg)
        self.assertEqual(transport._queue.qsize(), 4)

        # Critical will wait 50ms then drop silently
        import time
        start = time.time()
        transport.dispatch(crit_msg)
        end = time.time()
        self.assertTrue(end - start >= 0.04) # at least 40-50ms blocked
        self.assertEqual(transport._queue.qsize(), 4)

if __name__ == '__main__':
    unittest.main()
