import logging
import time
from typing import Dict, Any

from core.execution.execution_intent import ExecutionIntent, IntentStatus
from core.adapters.adapter_supervisor import AdapterSupervisor
from core.contracts.intent_contracts import IntentContractRegistry

logger = logging.getLogger("IntentDispatcher")

class IntentDispatcher:
    """
    Stage 1 Migration Facade.
    Allows legacy synchronous agents to emit ExecutionIntents and wait for results,
    stripping them of direct OS execution authority while preserving their runtime assumptions.
    """
    def __init__(self, supervisor: AdapterSupervisor):
        self._supervisor = supervisor

    def execute_sync(self, intent: ExecutionIntent) -> Dict[str, Any]:
        """
        Synchronously blocks until the intent is executed by the adapter.
        Returns a dictionary mimicking a CompletedProcess or expected result.
        """
        try:
            IntentContractRegistry.validate_intent(intent)
        except ValueError as e:
            intent.status = IntentStatus.FAILED
            intent.error = str(e)
            logger.error(f"Intent Validation Failed: {e}")
            return {"returncode": 1, "stdout": "", "stderr": str(e), "error": str(e)}

        intent.status = IntentStatus.EXECUTING
        logger.debug(f"Dispatching Intent: {intent.operation} -> {intent.adapter}")
        
        # Determine the adapter
        adapter_name = intent.adapter
        worker_id = f"agent_worker_{adapter_name}" # Isolated per adapter type
        
        if worker_id not in self._supervisor._active_adapters:
            success = self._supervisor.assign_adapter(worker_id, adapter_name)
            if not success:
                intent.status = IntentStatus.FAILED
                intent.error = f"Failed to assign adapter {adapter_name}"
                return {"returncode": -1, "stdout": "", "stderr": intent.error, "error": intent.error}

        adapter = self._supervisor._active_adapters[worker_id]
        
        try:
            result = adapter.execute(intent)
            intent.result = result
            intent.status = IntentStatus.COMPLETED
            
            # Map adapter output back to legacy expectations (stdout, returncode)
            # This is specifically for Stage 1 backwards compatibility
            if isinstance(result, dict):
                if "stdout" not in result:
                    result["stdout"] = str(result.copy())
                if "returncode" not in result:
                    result["returncode"] = 0
                if "stderr" not in result:
                    result["stderr"] = ""
                return result
            else:
                return {"returncode": 0, "stdout": str(result), "stderr": ""}
                
        except Exception as e:
            intent.error = str(e)
            intent.status = IntentStatus.FAILED
            logger.error(f"Intent execution failed: {e}")
            return {"returncode": 1, "stdout": "", "stderr": str(e), "error": str(e)}

# Singleton for Stage 1 easy replacement
_GLOBAL_DISPATCHER = None

def get_global_dispatcher() -> IntentDispatcher:
    global _GLOBAL_DISPATCHER
    if _GLOBAL_DISPATCHER is None:
        from core.adapters.adapter_supervisor import AdapterSupervisor
        class DummyKernel: """Implementation stub"""
        _GLOBAL_DISPATCHER = IntentDispatcher(AdapterSupervisor(DummyKernel()))
    return _GLOBAL_DISPATCHER