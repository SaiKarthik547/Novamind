import pytest
from core.observability.runtime_metrics import RuntimeMetrics
from core.observability.intent_trace import IntentTrace
from core.execution.intent_result import IntentResult
from core.runtime.semantic_authority_registry import SemanticAuthorityRegistry, SemanticOwnershipViolation

class TestRuntimeObservability:

    def test_metrics_collection_isolation(self):
        """
        Validate that RuntimeMetrics passively records telemetry 
        and does not leak or assert authority.
        """
        metrics = RuntimeMetrics.get_instance()
        metrics.record_replay_divergence()
        metrics.record_orphan()
        metrics.record_recovery_success()
        metrics.record_lock_contention()
        
        snapshot = metrics.dump_metrics()
        assert snapshot["replay_divergence_count"] >= 1
        assert snapshot["orphan_count"] >= 1
        assert snapshot["recovery_success_count"] >= 1
        assert snapshot["lock_contention_count"] >= 1

    def test_intent_trace_isolation(self):
        """
        Validate that IntentTrace builds a causal lineage passively.
        """
        trace = IntentTrace("intent-test-01")
        trace.add_event("DISPATCHED", {"metadata": "test"})
        
        result = IntentResult(
            intent_id="intent-test-01",
            success=True,
            status="COMPLETED",
            error=None,
            payload={"output": 1},
            metrics={"duration_ms": 10, "authority_origin": "test"}
        )
        
        trace.finalize(result)
        
        payload = trace.get_trace()
        assert payload["intent_id"] == "intent-test-01"
        assert len(payload["events"]) == 2
        assert payload["events"][0]["event_type"] == "DISPATCHED"
        assert payload["events"][1]["event_type"] == "COMPLETED"

    def test_observability_registry_isolation(self):
        """
        Observability components MUST NOT be registered as owners of mutable domains.
        """
        from core.execution.runtime_kernel import RuntimeKernel
        SemanticAuthorityRegistry.register("runtime_fsm", RuntimeKernel)
        
        with pytest.raises(SemanticOwnershipViolation):
            SemanticAuthorityRegistry.register("runtime_fsm", RuntimeMetrics)
            
        with pytest.raises(SemanticOwnershipViolation):
            SemanticAuthorityRegistry.register("runtime_fsm", IntentTrace)
