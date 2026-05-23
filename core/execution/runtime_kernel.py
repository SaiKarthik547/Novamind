from core.runtime.kernel_supervisor import KernelSupervisor
from core.adapters.adapter_supervisor import AdapterSupervisor
from core.execution.intent_dispatcher import IntentDispatcher
# KernelExecutionFacade is imported lazily to prevent circular imports if needed

class RuntimeKernel:
    """
    Phase 13: Authoritative Runtime Kernel.
    Governs execution, lifecycle, replay, recovery, concurrency, and verification.
    Replaces all DummyKernels and transitional global singletons.
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "RuntimeKernel":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # 1. Base OS-level Authority
        self.supervisor = KernelSupervisor()
        
        # 2. Adapter Lifecycle Orchestration
        self.adapter_supervisor = AdapterSupervisor(self.supervisor)
        
        # 3. Intent Orchestration (Pure runtime layer)
        self.dispatcher = IntentDispatcher(self.adapter_supervisor)
