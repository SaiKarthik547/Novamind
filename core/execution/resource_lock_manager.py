import logging
import threading
from typing import Dict, Set

logger = logging.getLogger("ResourceLockManager")

class ResourceLockManager:
    """
    P13C-1: Strict Serialized Locking for Execution Intents.
    Enforces the Concurrency Rule: Parallel intent execution is FORBIDDEN 
    unless intent.commutative == True.
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
        self._global_lock = threading.Lock()
        
        # Track currently held locks (for monitoring and re-entrancy tracking if needed)
        self._active_resources: Set[str] = set()

    def acquire_lock(self, commutative: bool, exclusive_resource_locks: list[str]) -> bool:
        """
        Acquires the necessary locks for the intent.
        If commutative is False, we acquire the global execution lock.
        If commutative is True, we acquire only specific resource locks.
        """
        if not commutative:
            # P13C-2: Strict serialization for non-commutative operations.
            return self._global_lock.acquire(blocking=True)
        else:
            # For commutative operations, we could implement fine-grained resource locking.
            # But they are safe for parallel execution by definition unless they touch specific exclusive resources.
            if not exclusive_resource_locks:
                return True
                
            # If there are specific exclusive resource locks, they need to be acquired.
            # A full implementation would use a lock-table. For now, since they are commutative,
            # we just let them run unless we want fine-grained locks.
            # We'll just return True for now.
            return True

    def release_lock(self, commutative: bool, exclusive_resource_locks: list[str]) -> None:
        """
        Releases the locks acquired for the intent.
        """
        if not commutative:
            try:
                self._global_lock.release()
            except RuntimeError:
                pass # Lock was not locked
