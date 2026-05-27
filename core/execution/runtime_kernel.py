from core.runtime.kernel_supervisor import KernelSupervisor
from core.adapters.adapter_supervisor import AdapterSupervisor
from core.execution.intent_governance import IntentGovernanceLayer
import warnings
import threading
from enum import Enum

class KernelBootState(Enum):
    UNINITIALIZED = "UNINITIALIZED"
    CONSTRUCTING = "CONSTRUCTING"
    INITIALIZING = "INITIALIZING"
    RECOVERING = "RECOVERING"
    RECONCILING = "RECONCILING"
    READY = "READY"
    PANIC = "PANIC"
    HALTED = "HALTED"

class RuntimeKernel:
    """
    Phase 15B: Authoritative Runtime Kernel (Execution Only).
    Governs execution routing, dispatch, execution locking, and adapter execution.
    Lifecycle, Replay, and Shutdown logic are extracted to respective authorities.
    """
    _instance = None
    _lock = threading.RLock()
    _boot_state = KernelBootState.UNINITIALIZED
    _boot_condition = threading.Condition(_lock)

    @classmethod
    def get_instance(cls) -> "RuntimeKernel":
        from core.runtime.runtime_bootstrap import BootstrapPhase, RuntimeBootstrap
        if RuntimeBootstrap.get_phase() == BootstrapPhase.STRICT:
            raise RuntimeError("RuntimeKernel.get_instance() is FORBIDDEN in STRICT mode. Use dependency injection.")
            
        warnings.warn("RuntimeKernel.get_instance() is deprecated. Transition to RuntimeBootstrap.", DeprecationWarning, stacklevel=2)
        
        with cls._lock:
            if cls._instance is None:
                cls._boot_state = KernelBootState.CONSTRUCTING
                cls._instance = cls()
                cls._boot_state = KernelBootState.READY
                cls._boot_condition.notify_all()
            
            while cls._boot_state in (KernelBootState.CONSTRUCTING, KernelBootState.INITIALIZING, 
                                      KernelBootState.RECOVERING, KernelBootState.RECONCILING):
                cls._boot_condition.wait()
                
            if cls._boot_state in (KernelBootState.PANIC, KernelBootState.HALTED):
                raise RuntimeError(f"Kernel authority is compromised: {cls._boot_state.name}")
                
            return cls._instance

    def __init__(self, lifecycle_authority=None, adapter_supervisor=None, os_supervisor=None, intent_governance=None):
        from core.runtime.runtime_bootstrap import BootstrapPhase, RuntimeBootstrap
        
        if RuntimeBootstrap.get_phase() == BootstrapPhase.STRICT:
            if None in (lifecycle_authority, adapter_supervisor, os_supervisor, intent_governance):
                raise ValueError("Strict Mode: All RuntimeKernel dependencies must be explicitly injected.")
                
        self.lifecycle_authority = lifecycle_authority
        
        # Legacy self-bootstrap (TRANSITIONAL only)
        if os_supervisor is None:
            warnings.warn("RuntimeKernel self-bootstrapping KernelSupervisor is deprecated.", DeprecationWarning, stacklevel=2)
            self.supervisor = KernelSupervisor()
        else:
            self.supervisor = os_supervisor
            
        if adapter_supervisor is None:
            self.adapter_supervisor = AdapterSupervisor(self.supervisor)
        else:
            self.adapter_supervisor = adapter_supervisor
            
        if intent_governance is None:
            self.intent_governance = IntentGovernanceLayer()
        else:
            self.intent_governance = intent_governance
