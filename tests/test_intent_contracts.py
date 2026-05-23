import unittest
from core.execution.execution_intent import ExecutionIntent, VerificationMode, RollbackMode
from core.contracts.intent_contracts import IntentContractRegistry

class TestIntentContracts(unittest.TestCase):
    def setUp(self):
        # Register a test contract
        IntentContractRegistry.register("test_adapter", "valid_op", ["req_key"], ["opt_key"], idempotent=True)

    def test_valid_intent(self):
        intent = ExecutionIntent(
            adapter="test_adapter",
            operation="valid_op",
            idempotent=True,
            verification_mode=VerificationMode.SEMANTIC,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"req_key": "val1", "opt_key": "val2"}
        )
        self.assertTrue(IntentContractRegistry.validate_intent(intent))

    def test_missing_required_key(self):
        intent = ExecutionIntent(
            adapter="test_adapter",
            operation="valid_op",
            idempotent=True,
            verification_mode=VerificationMode.SEMANTIC,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"opt_key": "val2"}
        )
        with self.assertRaisesRegex(ValueError, "missing required key"):
            IntentContractRegistry.validate_intent(intent)

    def test_unauthorized_key(self):
        intent = ExecutionIntent(
            adapter="test_adapter",
            operation="valid_op",
            idempotent=True,
            verification_mode=VerificationMode.SEMANTIC,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"req_key": "val1", "bad_key": "hack"}
        )
        with self.assertRaisesRegex(ValueError, "unauthorized key"):
            IntentContractRegistry.validate_intent(intent)

    def test_idempotency_mismatch(self):
        intent = ExecutionIntent(
            adapter="test_adapter",
            operation="valid_op",
            idempotent=False,  # Contract requires True
            verification_mode=VerificationMode.SEMANTIC,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"req_key": "val1"}
        )
        with self.assertRaisesRegex(ValueError, "idempotency"):
            IntentContractRegistry.validate_intent(intent)

if __name__ == '__main__':
    unittest.main()
