import unittest
import time
import sys
from core.adapters.process_adapter import ProcessAdapter
from core.execution.execution_intent import ExecutionIntent, VerificationMode, RollbackMode
from core.adapters.adapter_contract import AdapterState

class TestProcessAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = ProcessAdapter()
        self.adapter.initialize()
        self.adapter.attach()

    def test_spawn_success(self):
        intent = ExecutionIntent(
            adapter="process",
            operation="spawn",
            idempotent=False,
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={
                "cmd": [sys.executable, "-c", "print('hello world')"],
                "capture_output": True
            }
        )
        
        result = self.adapter.execute(intent)
        
        self.assertEqual(result["returncode"], 0)
        self.assertIn("hello world", result["stdout"])
        self.assertNotIn("error", result)

    def test_spawn_timeout(self):
        intent = ExecutionIntent(
            adapter="process",
            operation="spawn",
            idempotent=False,
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={
                "cmd": [sys.executable, "-c", "import time; time.sleep(2)"],
                "timeout": 0.1,
                "capture_output": True
            }
        )
        
        result = self.adapter.execute(intent)
        
        self.assertEqual(result["error"], "TIMEOUT")
        self.assertEqual(result["returncode"], -1)

    def test_unknown_operation(self):
        intent = ExecutionIntent(
            adapter="process",
            operation="hack",
            idempotent=False,
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={}
        )
        
        with self.assertRaises(ValueError):
            self.adapter.execute(intent)

if __name__ == '__main__':
    unittest.main()
