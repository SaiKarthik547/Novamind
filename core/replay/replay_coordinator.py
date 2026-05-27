import os
import json
import logging
from typing import List, Dict, Any

from core.execution.recovery_journal import RecoveryJournal
from core.execution.capability_registry import ReplayPolicy, CAPABILITY_REGISTRY
from core.execution.intent_execution_state import IntentExecutionState

logger = logging.getLogger("ReplayCoordinator")

class ReplayCoordinator:
    """
    Phase 15C: Owns replay sequencing, intent reconstruction, and divergence classification.
    Reads from RecoveryJournal (durability owner).
    Coordinates with LifecycleAuthority to gate replay completion.
    """
    def __init__(self, journal: RecoveryJournal):
        self.journal = journal
        self._reconstructed_intents = {}
        
    def analyze_lineage(self) -> Dict[str, Any]:
        """
        Reads the RecoveryJournal and reconstructs the causal graph and state of all intents.
        """
        logger.info("ReplayCoordinator: Analyzing journal lineage.")
        
        self._reconstructed_intents.clear()
        divergences = 0
        
        filepath = self.journal.filepath
        if not os.path.exists(filepath):
            return {"reconstructed_intents": 0, "divergences_detected": 0}

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        intent_id = record.get("intent_id")
                        state_val = record.get("state")
                        payload = record.get("payload", {})
                        
                        if not intent_id:
                            continue
                            
                        if intent_id not in self._reconstructed_intents:
                            self._reconstructed_intents[intent_id] = {
                                "id": intent_id,
                                "state": state_val,
                                "payload": payload,
                                "history": []
                            }
                            
                        self._reconstructed_intents[intent_id]["history"].append(record)
                        
                        # Detect illegal state transitions as divergences
                        current_state = self._reconstructed_intents[intent_id]["state"]
                        
                        # Validate state machine invariants
                        try:
                            from core.execution.intent_execution_state import IntentExecutionState
                            curr_enum = IntentExecutionState(current_state) if current_state else None
                            next_enum = IntentExecutionState(state_val) if state_val else None
                            
                            # Simple strict topology invariant: a TERMINATED intent cannot transition back to DISPATCHED
                            if curr_enum == IntentExecutionState.TERMINATED and next_enum == IntentExecutionState.DISPATCHED:
                                logger.error(f"Divergence detected: Intent {intent_id} attempted illegal transition {current_state} -> {state_val}")
                                divergences += 1
                        except ValueError:
                            # State value not in Enum, could be legacy WAL
                            pass
                            
                        # We just track the latest state
                        self._reconstructed_intents[intent_id]["state"] = state_val
                        
                    except json.JSONDecodeError:
                        logger.error("Failed to parse WAL record.")
                        divergences += 1
                        
        except IOError as e:
            logger.error(f"Failed to read recovery journal: {e}")
            divergences += 1

        return {
            "reconstructed_intents": len(self._reconstructed_intents),
            "divergences_detected": divergences,
            "intents": self._reconstructed_intents
        }
        
    def execute_replay_plan(self, kernel_dispatcher):
        """
        Dispatches intents via ExecutionOrderingCoordinator/RuntimeKernel
        according to the ReplayPolicy.
        """
        logger.info("ReplayCoordinator: Executing replay plan.")
        
        from core.execution.execution_intent import (
            ExecutionIntent, VerificationMode, RollbackMode, IntentPriority, IntentDeterminismLevel
        )
        
        dispatched_count = 0
        # Sort by chronological order of the WAL
        # (Since we parsed sequentially, we can sort by the minimum sequence or just iterate)
        # We will dispatch intents in the order they were first seen
        
        for intent_id, intent_data in self._reconstructed_intents.items():
            payload = intent_data.get("payload", {})
            # Attempt to extract properties from payload or history
            target = payload.get("target", "unknown")
            action = payload.get("action", "unknown")
            adapter = payload.get("adapter", "unknown")
            operation = payload.get("operation", action)
            
            # Fetch ReplayPolicy from capability registry
            policy = ReplayPolicy.NON_REPLAYABLE
            if target and action:
                try:
                    cap = CAPABILITY_REGISTRY.get_capability(target, action)
                    policy = cap.replay_policy
                except Exception:
                    pass
                    
            if policy in (ReplayPolicy.STRICT, ReplayPolicy.STRUCTURAL):
                try:
                    logger.info(f"Replaying intent {intent_id} (Policy: {policy.name})")
                    
                    # Real OS-level intent reconstruction
                    reconstructed_intent = ExecutionIntent(
                        adapter=adapter,
                        operation=operation,
                        idempotent=True,
                        verification_mode=VerificationMode.NONE,
                        rollback_strategy=RollbackMode.NO_ROLLBACK,
                        capability_scope={"target": target, "action": action},
                        payload=payload,
                        intent_id=intent_id,
                        priority=IntentPriority.BACKGROUND,
                        determinism=IntentDeterminismLevel.STRICT
                    )
                    
                    # Actually dispatch the intent to the kernel dispatcher
                    if hasattr(kernel_dispatcher, 'dispatch'):
                        kernel_dispatcher.dispatch(reconstructed_intent)
                    dispatched_count += 1
                except Exception as e:
                    logger.error(f"Failed to dispatch replay for intent {intent_id}: {e}")
                    
        return dispatched_count
