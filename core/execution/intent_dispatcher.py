import logging
import time
from typing import Dict, Any

from core.execution.execution_intent import ExecutionIntent, IntentStatus
from core.adapters.adapter_supervisor import AdapterSupervisor
from core.contracts.intent_contracts import IntentContractRegistry
from core.execution.intent_result import IntentResult

logger = logging.getLogger("IntentDispatcher")

class IntentDispatcher:
    """
    Phase 13 Orchestration Layer.
    Strictly consumes validated intents, delegates to the AdapterSupervisor, 
    and returns canonical IntentResults.
    """
    def __init__(self, supervisor: AdapterSupervisor):
        self._supervisor = supervisor

    def dispatch_sync(self, intent: ExecutionIntent) -> IntentResult:
        """
        Synchronously dispatches the intent to the target adapter.
        Returns a canonical IntentResult.
        """
        start_time = time.monotonic()
        try:
            IntentContractRegistry.validate_intent(intent)
        except ValueError as e:
            logger.error(f"Intent Validation Failed: {e}")
            return IntentResult(
                intent_id=intent.intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=str(e),
                metrics={"duration_ms": int((time.monotonic() - start_time) * 1000)}
            )

        logger.debug(f"Dispatching Intent: {intent.operation} -> {intent.adapter}")
        
        try:
            # P13A-2: Dispatcher strictly consumes validated intents and delegates to the AdapterSupervisor
            result_payload = self._supervisor.execute_intent(intent)
            
            return IntentResult(
                intent_id=intent.intent_id,
                status=IntentStatus.COMPLETED,
                success=True,
                payload=result_payload if isinstance(result_payload, dict) else {"data": result_payload},
                metrics={"duration_ms": int((time.monotonic() - start_time) * 1000)}
            )
                
        except Exception as e:
            logger.error(f"Intent execution failed: {e}")
            return IntentResult(
                intent_id=intent.intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=str(e),
                metrics={"duration_ms": int((time.monotonic() - start_time) * 1000)}
            )