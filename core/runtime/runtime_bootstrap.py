import logging
from enum import Enum
import warnings
import threading

from core.runtime.lifecycle_authority import LifecycleAuthority
from core.runtime.kernel_supervisor import KernelSupervisor
from core.adapters.adapter_supervisor import AdapterSupervisor

logger = logging.getLogger("RuntimeBootstrap")

class BootstrapPhase(Enum):
    TRANSITIONAL = "TRANSITIONAL"
    STRICT = "STRICT"

class RuntimeBootstrap:
    """
    Phase 15A: The ONLY legal runtime construction boundary.
    """
    _phase = BootstrapPhase.TRANSITIONAL
    _instance = None
    _lock = threading.RLock()
    
    @classmethod
    def set_phase(cls, phase: BootstrapPhase):
        cls._phase = phase
        
    @classmethod
    def get_phase(cls) -> BootstrapPhase:
        return cls._phase

    def __init__(self):
        if RuntimeBootstrap._phase == BootstrapPhase.STRICT:
            from core.runtime.semantic_authority_registry import SemanticAuthorityRegistry
            SemanticAuthorityRegistry.freeze_topology()
            warnings.warn(
                "Runtime is in STRICT bootstrap mode. Legacy topology is disabled.",
                DeprecationWarning,
                stacklevel=2
            )
            logger.info("Bootstrapping Runtime in STRICT mode")
        else:
            logger.warning("Bootstrapping Runtime in TRANSITIONAL mode")
            
        self.lifecycle_authority = LifecycleAuthority()
        self.os_supervisor = KernelSupervisor() 
        self.adapter_supervisor = AdapterSupervisor(self.os_supervisor)
        
        # Inject lifecycle authority into panic manager for delegation
        self.os_supervisor.panic_manager.lifecycle_authority = self.lifecycle_authority
        
        # Circular import protection for execution layer
        from core.execution.runtime_kernel import RuntimeKernel
        from core.execution.intent_governance import IntentGovernanceLayer
        
        self.intent_governance = IntentGovernanceLayer()
        
        # Inject all immutable dependencies into RuntimeKernel
        self.kernel = RuntimeKernel(
            lifecycle_authority=self.lifecycle_authority,
            adapter_supervisor=self.adapter_supervisor,
            os_supervisor=self.os_supervisor,
            intent_governance=self.intent_governance
        )
        
        # Phase 15: Initialize UI Boundary Layer
        from core.runtime.runtime_event_stream import RuntimeEventStream
        from core.runtime.runtime_snapshot_provider import RuntimeSnapshotProvider
        
        self.event_stream = RuntimeEventStream()
        
        # In a real system, the snapshot provider would read from a deterministic source like the kernel facade.
        # For now we supply an empty dict lambda to represent the boundary correctly.
        self.snapshot_provider = RuntimeSnapshotProvider(state_supplier=lambda: {})
        
        # Phase 15A: Topology Freeze (Unconditional after boot)
        from core.runtime.semantic_authority_registry import SemanticAuthorityRegistry
        SemanticAuthorityRegistry.freeze_topology()
        
        # Transition to ready
        self.lifecycle_authority.transition_to_ready()

    @classmethod
    def boot(cls) -> "RuntimeBootstrap":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
