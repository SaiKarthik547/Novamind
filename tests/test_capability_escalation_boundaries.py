import pytest
from core.execution.capability_registry import CAPABILITY_REGISTRY, AuthorityLevel, ReplayPolicy, DeterminismClass

class TestCapabilityEscalationBoundaries:
    
    def test_observational_domains_cannot_trigger_replay(self):
        """
        Capability Escalation Law:
        UI and observational components operate under NON_DETERMINISTIC constraints.
        They must NEVER claim STRICT or STRUCTURAL replay trust.
        """
        for name in CAPABILITY_REGISTRY.all_capabilities():
            cap = CAPABILITY_REGISTRY.get(name)
            
            # If the capability is NON_DETERMINISTIC or LEGACY_BRIDGE
            # It mathematically cannot guarantee replay.
            if cap.determinism_class == DeterminismClass.NON_DETERMINISTIC or cap.authority_level == AuthorityLevel.LEGACY_BRIDGE:
                assert cap.replay_policy in (ReplayPolicy.SKIP, ReplayPolicy.OBSERVATIONAL), \
                    f"Capability '{name}' violates Escalation Law: It is {cap.determinism_class.value} but claims {cap.replay_policy.value} replay trust."

    def test_unsafe_runtime_is_quarantined(self):
        """
        AuthorityLevel.UNSAFE_RUNTIME is forbidden from being registered natively 
        by any adapter. It is exclusively reserved for un-sandboxed raw script execution,
        which must never interleave with strict WAL pipelines.
        """
        for name in CAPABILITY_REGISTRY.all_capabilities():
            cap = CAPABILITY_REGISTRY.get(name)
            
            # Currently NO capability in the registry should map to UNSAFE_RUNTIME natively.
            assert cap.authority_level != AuthorityLevel.UNSAFE_RUNTIME, \
                f"Capability '{name}' claims UNSAFE_RUNTIME authority, which is a Phase 14 breach."
