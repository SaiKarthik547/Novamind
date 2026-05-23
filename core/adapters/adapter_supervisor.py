import logging
from typing import Dict, Optional

from core.adapters.adapter_contract import ApplicationAdapter, AdapterState
from core.adapters.adapter_registry import ADAPTER_REGISTRY

logger = logging.getLogger("AdapterSupervisor")

class AdapterSupervisor:
    """
    Supervises adapter lifecycles, assigns workers, and reconciles failures.
    CRITICAL ARCHITECTURE NOTE:
    This class does NOT own lifecycle authority, runtime state, or scheduler authority.
    It is strictly a subordinate of the KernelSupervisor.
    """
    def __init__(self, kernel_supervisor):
        self._kernel = kernel_supervisor
        self._active_adapters: Dict[str, ApplicationAdapter] = {}

    def assign_adapter(self, worker_id: str, adapter_name: str) -> bool:
        """Instantiates and attaches an adapter for a given worker."""
        if adapter_name not in ADAPTER_REGISTRY._adapters:
            logger.error(f"Cannot assign unknown adapter: {adapter_name}")
            return False

        adapter_cls = ADAPTER_REGISTRY.get_adapter_class(adapter_name)
        adapter = adapter_cls()
        
        # State transition: CREATED -> INITIALIZING
        if not adapter.initialize():
            logger.error(f"Adapter {adapter_name} failed to initialize.")
            return False
            
        # State transition: INITIALIZING -> ATTACHED
        if not adapter.attach():
            logger.error(f"Adapter {adapter_name} failed to attach to target.")
            adapter.teardown()
            return False
            
        self._active_adapters[worker_id] = adapter
        logger.info(f"Successfully assigned {adapter_name} to {worker_id}")
        return True

    def reconcile_worker(self, worker_id: str) -> bool:
        """Delegated by Kernel to recover an adapter if a worker panics."""
        adapter = self._active_adapters.get(worker_id)
        if not adapter:
            return False
            
        if adapter.get_state() in (AdapterState.DEGRADED, AdapterState.EXECUTING):
            logger.warning(f"Reconciling adapter for worker {worker_id}")
            if adapter.reconcile():
                return True
            else:
                logger.error(f"Adapter reconciliation failed for {worker_id}, tearing down.")
                adapter.teardown()
                del self._active_adapters[worker_id]
                return False
        return True

    def teardown_worker_adapter(self, worker_id: str):
        """Cleanly destroys the adapter linked to a worker."""
        adapter = self._active_adapters.pop(worker_id, None)
        if adapter:
            adapter.teardown()

    def execute_intent(self, intent: 'ExecutionIntent') -> 'Any':
        """
        Lazily assigns an adapter if needed, and executes the intent.
        Replaces the dispatcher's direct management of adapter lifecycle.
        """
        adapter_name = intent.adapter
        worker_id = f"agent_worker_{adapter_name}" # Isolated per adapter type
        
        if worker_id not in self._active_adapters:
            success = self.assign_adapter(worker_id, adapter_name)
            if not success:
                raise RuntimeError(f"Failed to assign adapter {adapter_name} for worker {worker_id}")
                
        adapter = self._active_adapters[worker_id]
        return adapter.execute(intent)
