import logging
import threading
from typing import Dict, Set

logger = logging.getLogger("ResourceLockManager")

class ResourceLockManager:
    """
    Phase 15A: Pure Lock Ownership.
    Reduced strictly to mutex semantics and resource coordination.
    
    WARNING: This manager no longer dictates execution ordering, 
    dispatch sequencing, or scheduler decisions. Those domains 
    belong exclusively to ExecutionScheduler.
    """
    _instance = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'ResourceLockManager':
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        # Track currently held locks for specific resources (e.g. file paths)
        # Execution ordering is strictly managed by ExecutionScheduler
        self._active_resources: Set[str] = set()
        self._resource_lock = threading.Lock()

    def acquire_lock(self, exclusive_resource_locks: list[str]) -> bool:
        """
        Acquires fine-grained resource locks purely for mutex isolation.
        Does not imply or dictate queue priority or execution sequencing.
        """
        if not exclusive_resource_locks:
            return True
            
        with self._resource_lock:
            for res in exclusive_resource_locks:
                if res in self._active_resources:
                    return False # Resource currently locked
            for res in exclusive_resource_locks:
                self._active_resources.add(res)
        return True

    def release_lock(self, exclusive_resource_locks: list[str]) -> None:
        """
        Releases fine-grained resource locks.
        """
        if not exclusive_resource_locks:
            return
            
        with self._resource_lock:
            for res in exclusive_resource_locks:
                self._active_resources.discard(res)
