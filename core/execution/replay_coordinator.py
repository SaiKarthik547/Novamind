import logging
from typing import List, Dict, Any

from core.execution.recovery_journal import RecoveryJournal
from core.execution.intent_execution_state import IntentExecutionState
from core.execution.capability_registry import CAPABILITY_REGISTRY, ReplayPolicy

logger = logging.getLogger("ReplayCoordinator")

class ReplayCoordinator:
    """
    Phase 15: Replay Equivalence Hardening.
    Owns the semantics of historic intent replay, ensuring 1:1 mapping
    of WAL logs to capability invocations during recovery boot.
    """
    
    def __init__(self, journal: RecoveryJournal):
        self.journal = journal

    def orchestrate_replay(self) -> None:
        """
        Reads the RecoveryJournal and sequences historic intents for execution.
        Applies ReplayPolicy constraints statically.
        """
        logger.info("Initializing historic WAL replay sequence.")
        
        # Read the raw lines from the WAL (RecoveryJournal is currently append-only)
        try:
            with open(self.journal.filepath, "r") as f:
                lines = f.readlines()
        except FileNotFoundError:
            logger.info("No WAL found. Skipping replay.")
            return

        import json
        intents_state: Dict[str, Dict[str, Any]] = {}
        
        # Reconstruct the last known state of each intent
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                intent_id = record["intent_id"]
                
                if intent_id not in intents_state:
                    intents_state[intent_id] = record
                else:
                    # Update with latest state transition
                    intents_state[intent_id].update(record)
            except json.JSONDecodeError:
                logger.warning("Corrupted WAL record found during replay parsing.")
                continue

        # Filter and sequence intents based on their ReplayPolicy
        # and ExecutionState.
        for intent_id, record in intents_state.items():
            state = record.get("state")
            payload = record.get("payload", {})
            capability_name = payload.get("capability")
            
            if not capability_name:
                continue

            cap = CAPABILITY_REGISTRY.get(capability_name)
            if not cap:
                logger.warning(f"Skipping replay for unknown capability: {capability_name}")
                continue

            if cap.replay_policy in (ReplayPolicy.NON_REPLAYABLE, ReplayPolicy.OBSERVATIONAL):
                logger.info(f"Skipping intent {intent_id} (Policy: {cap.replay_policy.value})")
                continue
                
            # If the intent was DISPATCHED but never COMPLETED, it needs salvage/replay
            if state in (IntentExecutionState.DISPATCHED.value, IntentExecutionState.RECEIVED.value):
                logger.info(f"Sequencing intent {intent_id} for deterministic replay.")
                # Sequence logic goes here
