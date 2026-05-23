import logging
from typing import Any, Dict, List
from dataclasses import dataclass, field

# Phase 13: All capability execution delegates to the KernelExecutionFacade
from core.execution.runtime_kernel import RuntimeKernel
from core.execution.intent_result import IntentResult

logger = logging.getLogger("AgentContext")


@dataclass
class AgentContext:
    """
    Provides agents with a scoped, capability-checked execution environment.
    Agents MUST use this context to perform any real-world side effects by emitting intents.
    """
    task_id: str
    step_number: int
    agent_id: str
    action: str
    parameters: Dict[str, Any]
    
    # Phase 13: KernelSupervisor delegate (optional for backwards compatibility)
    kernel_supervisor: Any = None 

    # Telemetry data that the agent might want to read, 
    # but not modify.
    telemetry_tags: Dict[str, str] = field(default_factory=dict)
    
    def emit_intent(self, capability: str, payload: Dict[str, Any], **kwargs) -> IntentResult:
        """
        Emits an ExecutionIntent to the RuntimeKernel.
        Replaces direct subprocess execution and transaction management.
        """
        facade = RuntimeKernel.get_instance().facade
        return facade.dispatch(
            capability=capability,
            payload=payload,
            **kwargs
        )

