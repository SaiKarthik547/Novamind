import unittest

from core.adapters.adapter_contract import AdapterState, VerificationMode
from core.adapters.adapter_supervisor import AdapterSupervisor
from core.adapters.adapter_registry import ADAPTER_REGISTRY, AdapterCapabilityManifest
from adapters.browser.chrome_cdp_adapter import ChromeCDPAdapter
from adapters.shell.pty_adapter import PTYAdapter
from core.telemetry.telemetry_event import DeterminismLevel

class DummyKernel:
    pass

class TestAdapterLifecycle(unittest.TestCase):
    def setUp(self):
        self.kernel = DummyKernel()
        self.supervisor = AdapterSupervisor(self.kernel)
        
        # Register for test
        ADAPTER_REGISTRY.register(
            "chrome", ChromeCDPAdapter,
            AdapterCapabilityManifest(["web"], "HYBRID", "BACKGROUND", False, DeterminismLevel.RECONCILABLE)
        )
        ADAPTER_REGISTRY.register(
            "pty", PTYAdapter,
            AdapterCapabilityManifest(["shell"], "STRUCTURAL", "BACKGROUND", False, DeterminismLevel.STRICT)
        )

    def test_adapter_assignment_and_fsm(self):
        worker_id = "worker-100"
        success = self.supervisor.assign_adapter(worker_id, "chrome")
        self.assertTrue(success)
        
        adapter = self.supervisor._active_adapters[worker_id]
        self.assertEqual(adapter.get_state(), AdapterState.ATTACHED)
        
        from core.execution.execution_intent import ExecutionIntent, VerificationMode, RollbackMode
        intent = ExecutionIntent(
            adapter="chrome",
            operation="navigate",
            idempotent=True,
            verification_mode=VerificationMode.SEMANTIC,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={}
        )
    
        # Execute simulates state changes
        res = adapter.execute(intent)
        self.assertEqual(res["navigation_epoch"], 1)
        self.assertEqual(res["dom_epoch"], 0)
        self.assertEqual(adapter.get_state(), AdapterState.ATTACHED)
        
        adapter.verify(VerificationMode.STRUCTURAL)
        
        self.supervisor.teardown_worker_adapter(worker_id)
        self.assertEqual(adapter.get_state(), AdapterState.TERMINATED)
        self.assertNotIn(worker_id, self.supervisor._active_adapters)

if __name__ == '__main__':
    unittest.main()
