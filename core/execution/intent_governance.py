import logging
from typing import Dict, Any

from core.execution.execution_intent import ExecutionIntent
from core.contracts.intent_contracts import IntentContractRegistry

logger = logging.getLogger("IntentGovernanceLayer")

class IntentGovernanceLayer:
    """
    Phase 15C Semantic Governance Layer.
    Strictly responsible for:
    - Contract validation
    - Capability legality
    
    It MUST NEVER dispatch, schedule, mutate lifecycle, mutate WAL, or invoke adapters.
    """
    def __init__(self):
        pass

    def validate_intent(self, intent: ExecutionIntent) -> None:
        """
        Validates the intent against capability constraints and structural contracts.
        Raises ValueError or PermissionError on policy violation.
        """
        logger.debug(f"Governance Check: Validating Intent {intent.intent_id} ({intent.operation} -> {intent.adapter})")
        
        # 1. Structural Validation
        IntentContractRegistry.validate_intent(intent)
        
        # 2. Replay Legality Stub
        # Replay legality is an execution/determinism concern owned by ReplayCoordinator.
        # But if an intent structurally asks for a replay that is unsupported, we reject it here.
        if getattr(intent, 'replay_mode', False):
            raise NotImplementedError("ReplayClassificationPending: Replay policy not yet isolated.")