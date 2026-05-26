import json
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SemanticSnapshot")

# Ensure core modules are available
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.runtime.semantic_authority_registry import SemanticAuthorityRegistry
from core.execution.capability_registry import CAPABILITY_REGISTRY
from core.observability.runtime_metrics import RuntimeMetrics

def take_semantic_snapshot() -> dict:
    """
    P14F-1: Freezes the topological and authority graph into a deterministic snapshot.
    This asserts that there is NO drift in the expected architecture between runs.
    """
    
    # 1. Authority Graph
    authority_snapshot = SemanticAuthorityRegistry.snapshot()
    
    # 2. Capability Topology
    capability_topology = {}
    for name in sorted(CAPABILITY_REGISTRY.all_capabilities()):
        cap = CAPABILITY_REGISTRY.get(name)
        capability_topology[name] = {
            "determinism_class": cap.determinism_class.value,
            "replay_policy": cap.replay_policy.value,
            "rollback_policy": cap.rollback_policy.value,
            "authority_level": cap.authority_level.value,
            "trust_level": cap.trust_level.value,
            "requires_user_focus": cap.requires_user_focus,
            "allows_background_execution": cap.allows_background_execution,
            "side_effect_permanent": cap.side_effect_permanent,
            "verification_mode": cap.verification_mode,
        }
        
    return {
        "authority_graph": authority_snapshot,
        "capability_topology": capability_topology
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate Runtime Semantic Snapshot")
    parser.add_argument("--output", "-o", type=str, required=True, help="Output JSON path")
    parser.add_argument("--verify-against", "-v", type=str, help="Verify snapshot against existing JSON path")
    args = parser.parse_args()
    
    # Force registration of essential authorities to ensure the graph is populated
    try:
        from core.execution.runtime_kernel import RuntimeKernel
        from core.execution.recovery_journal import RecoveryJournal
        from core.execution.resource_lock_manager import ResourceLockManager
        from core.runtime.semantic_authority_registry import SemanticOwnershipViolation
        
        try:
            SemanticAuthorityRegistry.register("runtime_fsm", RuntimeKernel)
        except SemanticOwnershipViolation: pass
        
        try:
            SemanticAuthorityRegistry.register("wal_journal", RecoveryJournal)
        except SemanticOwnershipViolation: pass
        
        try:
            SemanticAuthorityRegistry.register("lock_orchestration", ResourceLockManager)
        except SemanticOwnershipViolation: pass
            
    except Exception as e:
        logger.warning(f"Failed to prepopulate snapshot authority registry: {e}")
        
    current_snapshot = take_semantic_snapshot()
    
    if args.verify_against:
        if not os.path.exists(args.verify_against):
            print(f"Verification target {args.verify_against} not found.", file=sys.stderr)
            sys.exit(1)
            
        with open(args.verify_against, "r") as f:
            baseline = json.load(f)
            
        if current_snapshot != baseline:
            print("SEMANTIC DRIFT DETECTED!", file=sys.stderr)
            
            # Simple diff
            diffs = []
            for k in baseline["capability_topology"]:
                if k not in current_snapshot["capability_topology"]:
                    diffs.append(f"- Missing Capability: {k}")
                elif baseline["capability_topology"][k] != current_snapshot["capability_topology"][k]:
                    diffs.append(f"~ Changed Capability: {k}")
            
            for d in diffs:
                print(d, file=sys.stderr)
                
            sys.exit(1)
        else:
            print("Semantic Topological Audit: PASS (No Drift)")
            
    with open(args.output, "w") as f:
        json.dump(current_snapshot, f, indent=4)
        
    print(f"Snapshot written to {args.output}")

if __name__ == "__main__":
    main()
