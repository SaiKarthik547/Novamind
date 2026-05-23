import unittest

from core.execution.execution_intent import ExecutionIntent, IntentStatus
from core.execution.intent_dispatcher import IntentDispatcher
from core.adapters.adapter_supervisor import AdapterSupervisor
from core.adapters.adapter_registry import ADAPTER_REGISTRY, AdapterCapabilityManifest
from adapters.shell.pty_adapter import PTYAdapter
from core.telemetry.telemetry_event import DeterminismLevel

class DummyKernel:
    pass

class TestIntentDispatcher(unittest.TestCase):
    def setUp(self):
        self.kernel = DummyKernel()
        self.supervisor = AdapterSupervisor(self.kernel)
        self.dispatcher = IntentDispatcher(self.supervisor)
        
        # Ensure PTY is registered
        if "pty" not in ADAPTER_REGISTRY._adapters:
            ADAPTER_REGISTRY.register(
                "pty", PTYAdapter,
                AdapterCapabilityManifest(["shell"], "STRUCTURAL", "BACKGROUND", False, DeterminismLevel.STRICT)
            )

    def test_execute_sync_success(self):
        intent = ExecutionIntent(
            target_adapter="pty",
            action="run_command",
            payload={"cmd": "echo hello"}
        )
        
        result = self.dispatcher.execute_sync(intent)
        
        self.assertEqual(intent.status, IntentStatus.COMPLETED)
        self.assertIn("session_id", result)
        self.assertIn("command_epoch", result)

    def test_execute_sync_unknown_adapter_fails(self):
        intent = ExecutionIntent(
            target_adapter="nonexistent",
            action="run_command",
            payload={"cmd": "echo hello"}
        )
        
        result = self.dispatcher.execute_sync(intent)
        
        self.assertEqual(intent.status, IntentStatus.FAILED)
        self.assertIn("Failed to assign adapter", intent.error)
        self.assertEqual(result["returncode"], -1)
        
if __name__ == '__main__':
    unittest.main()
