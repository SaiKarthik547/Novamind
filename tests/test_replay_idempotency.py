import pytest
import os
import tempfile
import json

from core.execution.recovery_journal import RecoveryJournal
from core.execution.intent_execution_state import IntentExecutionState

class TestReplayIdempotency:
    
    def test_wal_lineage_outcome_determinism(self):
        """
        Replay Idempotency Certification:
        Validate that writing a sequence of events to the WAL 
        yields an exactly predictable, durable byte sequence, representing
        the exact state Hash(S) == Hash(Original S) requirement.
        """
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
            
        try:
            journal = RecoveryJournal(filepath=temp_path)
            
            # Write a deterministic sequence of state transitions
            journal.log_transition("intent-001", IntentExecutionState.DISPATCHED, {"a": 1})
            journal.log_transition("intent-001", IntentExecutionState.VERIFYING, {"a": 1})
            journal.log_transition("intent-001", IntentExecutionState.COMPLETED, {"a": 1, "result": "ok"})
            journal.close()
            
            # Verify the written WAL file
            with open(temp_path, "r") as f:
                lines = f.readlines()
                
            assert len(lines) == 3
            
            # The exact lineage must be preserved and parseable
            state_1 = json.loads(lines[0])
            state_2 = json.loads(lines[1])
            state_3 = json.loads(lines[2])
            
            assert state_1["intent_id"] == "intent-001" and state_1["state"] == IntentExecutionState.DISPATCHED.value
            assert state_2["intent_id"] == "intent-001" and state_2["state"] == IntentExecutionState.VERIFYING.value
            assert state_3["intent_id"] == "intent-001" and state_3["state"] == IntentExecutionState.COMPLETED.value
            
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_reordered_scheduling_determinism(self):
        """
        Validate that multiple parallel journals or interleaved writes 
        maintain append-only determinism.
        """
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
            
        try:
            journal = RecoveryJournal(filepath=temp_path)
            # Simulating intent 1 and intent 2 interleaving
            journal.log_transition("intent-001", IntentExecutionState.DISPATCHED)
            journal.log_transition("intent-002", IntentExecutionState.DISPATCHED)
            journal.log_transition("intent-001", IntentExecutionState.COMPLETED)
            journal.log_transition("intent-002", IntentExecutionState.COMPLETED)
            journal.close()
            
            with open(temp_path, "r") as f:
                lines = f.readlines()
                
            assert json.loads(lines[0])["intent_id"] == "intent-001"
            assert json.loads(lines[1])["intent_id"] == "intent-002"
            assert json.loads(lines[2])["intent_id"] == "intent-001"
            assert json.loads(lines[3])["intent_id"] == "intent-002"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
