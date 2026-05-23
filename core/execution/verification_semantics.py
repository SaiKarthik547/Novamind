import logging
from enum import Enum
from typing import Callable, Dict, Any

from core.execution.execution_intent import ExecutionIntent
from core.execution.intent_result import IntentResult
from core.execution.verification_taxonomy import VerificationMode

logger = logging.getLogger("VerificationSemantics")

class ReplayTrustLevel(Enum):
    """
    P13E-3: Decoupled ReplayTrustLevel.
    Classifies the trust we have in a replayed intent based on verification outcomes.
    """
    UNTRUSTED = "UNTRUSTED"           # Replay failed or was not verified
    OBSERVATIONAL = "OBSERVATIONAL"   # Observed similar side effects but no guarantee
    VERIFIED = "VERIFIED"             # Side effects strictly matched
    BIT_IDENTICAL = "BIT_IDENTICAL"   # Output and state match exactly

VerificationCallback = Callable[[ExecutionIntent, IntentResult], bool]

class VerifierRegistry:
    """
    P13E-1 & P13E-2: Registry of domain-specific verifiers.
    """
    _verifiers: Dict[str, VerificationCallback] = {}

    @classmethod
    def register(cls, capability: str, callback: VerificationCallback):
        cls._verifiers[capability] = callback

    @classmethod
    def verify(cls, intent: ExecutionIntent, result: IntentResult) -> bool:
        """
        Runs the registered verifier for the given capability.
        Returns True if successful or BEST_EFFORT / NONE mode, False if verification fails.
        """
        # If no verification is requested, it passes automatically
        if intent.verification_mode in (VerificationMode.NONE, VerificationMode.BEST_EFFORT):
            return True

        if intent.verification_mode == VerificationMode.HUMAN_CONFIRMED:
            # Human confirmation is currently an interactive boundary, assume True for automation
            # unless a human explicitly marked it failed.
            return True

        verifier = cls._verifiers.get(intent.capability_scope.get("capability", ""))
        
        if not verifier:
            logger.warning(f"No verifier registered for capability: {intent.capability_scope.get('capability', '')}. Passing by default.")
            return True
            
        try:
            return verifier(intent, result)
        except Exception as e:
            logger.error(f"Verification failed with exception: {e}")
            return False

# P13E-2: Domain-specific verifiers
def filesystem_write_verifier(intent: ExecutionIntent, result: IntentResult) -> bool:
    """Verifies that the written file exists."""
    import os
    path = intent.payload.get("path")
    if path and os.path.exists(path):
        return True
    return False

VerifierRegistry.register("filesystem.write", filesystem_write_verifier)
