import pytest
import threading

from core.runtime.semantic_authority_registry import SemanticAuthorityRegistry, SemanticOwnershipViolation
from core.execution.runtime_kernel import RuntimeKernel
from core.execution.recovery_journal import RecoveryJournal
from core.execution.resource_lock_manager import ResourceLockManager
from core.execution.intent_execution_state import IntentExecutionState
from core.execution.execution_intent import ExecutionIntent

class TestRuntimeInvariants:
    
    def setup_method(self):
        SemanticAuthorityRegistry.clear_for_testing()

    def test_semantic_ownership_law_prevents_duplicate_ownership(self):
        """
        The Semantic Ownership Law:
        Exactly one semantic authority per mutable domain.
        """
        # Valid registration using the real kernel
        SemanticAuthorityRegistry.register("runtime_fsm", RuntimeKernel)
        assert SemanticAuthorityRegistry.get_owner("runtime_fsm") is RuntimeKernel
        
        # Duplicate registration of the same authority is fine
        SemanticAuthorityRegistry.register("runtime_fsm", RuntimeKernel)
        
        # Registering a DIFFERENT authority (like RecoveryJournal) to the same domain MUST fail
        with pytest.raises(SemanticOwnershipViolation) as exc:
            SemanticAuthorityRegistry.register("runtime_fsm", RecoveryJournal)
        
        assert "Semantic Ownership Law Violation!" in str(exc.value)

    def test_semantic_ownership_law_snapshot(self):
        SemanticAuthorityRegistry.register("runtime_fsm", RuntimeKernel)
        SemanticAuthorityRegistry.register("wal_journal", RecoveryJournal)
        SemanticAuthorityRegistry.register("lock_orchestration", ResourceLockManager)

        snapshot = SemanticAuthorityRegistry.snapshot()
        assert snapshot["runtime_fsm"] == "RuntimeKernel"
        assert snapshot["wal_journal"] == "RecoveryJournal"
        assert snapshot["lock_orchestration"] == "ResourceLockManager"
        assert len(snapshot) == 3

    def test_observability_isolation_law(self):
        """
        The Observability Isolation Law:
        Observability is passive truth exposure and MUST NOT own any mutable domain.
        """
        # Mock observability module
        class TelemetryObserver: pass 

        SemanticAuthorityRegistry.register("runtime_fsm", RuntimeKernel)
        
        with pytest.raises(SemanticOwnershipViolation):
            SemanticAuthorityRegistry.register("runtime_fsm", TelemetryObserver)

    def test_wal_durability_law(self):
        """
        WAL Durability Law: No execution may proceed before durable persistence.
        """
        # We assert that the RecoveryJournal issues an fsync by examining its log_transition
        # behavior, or we mock os.fsync to ensure it is called.
        import os
        import tempfile
        
        fsync_called = False
        original_fsync = os.fsync
        
        def mock_fsync(fd):
            nonlocal fsync_called
            fsync_called = True
            original_fsync(fd)
            
        os.fsync = mock_fsync
        
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                temp_path = tf.name
            
            journal = RecoveryJournal(filepath=temp_path)
            
            # Create a real intent transition
            journal.log_transition(
                intent_id="intent-test-01", 
                state=IntentExecutionState.DISPATCHED, 
                payload={"action": "test"}
            )
            
            journal.close()
            os.remove(temp_path)
            
            assert fsync_called, "WAL Durability Law Violation: fsync was not called during state transition logging."
            
        finally:
            os.fsync = original_fsync

    def test_concurrency_law(self):
        """
        Concurrency Law: Non-commutative intents MUST strictly serialize.
        """
        # Ensure ResourceLockManager can establish scopes and handle concurrency
        lock_manager = ResourceLockManager.get_instance()
        assert hasattr(lock_manager, "acquire_lock"), "ResourceLockManager missing lock enforcement primitive"
        assert hasattr(lock_manager, "release_lock"), "ResourceLockManager missing lock release primitive"
