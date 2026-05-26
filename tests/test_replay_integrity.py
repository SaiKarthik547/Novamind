import pytest
import os
import tempfile
import json

from core.execution.recovery_journal import RecoveryJournal
from core.execution.intent_execution_state import IntentExecutionState

class TestReplayIntegrity:

    def test_replay_interruption_recovery(self):
        """
        Simulate a runtime crash during dispatch, and validate that
        the WAL retains the exact orphaned state correctly for continuation.
        """
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
            
        try:
            journal = RecoveryJournal(filepath=temp_path)
            # Intent starts dispatching but crashes before VERIFYING or COMPLETED
            journal.log_transition("intent-003", IntentExecutionState.DISPATCHED, {"args": "some_data"})
            
            # Simulate hard crash by closing fd and re-opening the journal
            journal.close()
            
            # Reboot Simulation
            journal_reboot = RecoveryJournal(filepath=temp_path)
            
            with open(temp_path, "r") as f:
                lines = f.readlines()
            
            assert len(lines) == 1
            state = json.loads(lines[0])
            
            # State must reflect exactly where it died so ReplayCoordinator can orphan it
            assert state["intent_id"] == "intent-003"
            assert state["state"] == IntentExecutionState.DISPATCHED.value
            
            journal_reboot.close()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_observational_replay_enforcement(self):
        """
        Observational capabilities MUST NOT claim high-trust deterministic replay levels.
        (Conceptual test of the Capability Escalation Law)
        """
        # Testing that ReplayTrustLevel (from capability registry) doesn't leak.
        # This will be fully implemented when CapabilityRegistry is integrated in Phase 14D.
        pass
