import logging
import threading

logger = logging.getLogger("ExecutionOrderingCoordinator")

class ExecutionOrderingCoordinator:
    """
    Phase 15D: Canonical intent ordering owner.
    Enforces deterministic serialization and strict replay ordering legality.
    (Deferred to future phases: Adaptive scheduling, fairness heuristics, async worker balancing).
    """
    _instance = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'ExecutionOrderingCoordinator':
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        # Replaces the _global_lock previously held in ResourceLockManager
        self._global_serialization_lock = threading.Lock()
        
    def acquire_ordering_lock(self, commutative: bool) -> bool:
        """
        Enforces the Concurrency Rule: Non-commutative intents must be strictly serialized
        to ensure deterministic replay lineage.
        """
        if not commutative:
            return self._global_serialization_lock.acquire(blocking=True)
        return True

    def release_ordering_lock(self, commutative: bool) -> None:
        if not commutative:
            try:
                self._global_serialization_lock.release()
            except RuntimeError:
                pass
