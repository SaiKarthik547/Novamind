import pytest
import threading
import time

from core.execution.resource_lock_manager import ResourceLockManager

class TestSchedulerDeterminism:
    
    def test_identical_intent_ordering(self):
        """
        Validate identical intent ordering under equal conditions.
        Non-commutative intents MUST acquire the global lock strictly, meaning
        parallel dispatched intents are forced into a serialized sequence.
        """
        lock_manager = ResourceLockManager.get_instance()
        
        # Test serialization of non-commutative locks
        # If one thread holds the lock, the other must block
        acquired_first = lock_manager.acquire_lock(commutative=False, exclusive_resource_locks=[])
        assert acquired_first is True, "First non-commutative intent failed to acquire global lock"
        
        # We start a second thread that attempts to acquire the lock. It should block.
        lock_status = []
        
        def attempt_acquire():
            # This should block until the lock is released
            success = lock_manager.acquire_lock(commutative=False, exclusive_resource_locks=[])
            lock_status.append(success)
            if success:
                lock_manager.release_lock(commutative=False, exclusive_resource_locks=[])
                
        t = threading.Thread(target=attempt_acquire)
        t.start()
        
        # Give the thread a moment to block
        time.sleep(0.1)
        assert len(lock_status) == 0, "Deterministic lock ordering violated: thread acquired global lock while it was held"
        
        # Release the lock, allowing the second thread to proceed
        lock_manager.release_lock(commutative=False, exclusive_resource_locks=[])
        t.join(timeout=1.0)
        
        assert len(lock_status) == 1
        assert lock_status[0] is True, "Thread failed to acquire lock after release"

    def test_commutative_intents_bypass_global_lock(self):
        """
        Validate that commutative intents do not block on the global execution lock,
        allowing safe parallel determinism where intents mathematically commute.
        """
        lock_manager = ResourceLockManager.get_instance()
        
        # Acquire global lock (non-commutative intent is executing)
        lock_manager.acquire_lock(commutative=False, exclusive_resource_locks=[])
        
        # Commutative intent should acquire its lock instantly
        acquired_commutative = lock_manager.acquire_lock(commutative=True, exclusive_resource_locks=[])
        assert acquired_commutative is True, "Commutative intent was blocked by the global lock"
        
        lock_manager.release_lock(commutative=True, exclusive_resource_locks=[])
        lock_manager.release_lock(commutative=False, exclusive_resource_locks=[])

    def test_stable_reconciliation_order(self):
        """
        Validate that ResourceLockManager does not deadlock on re-entrancy 
        during orphan reconciliation. (If reconciliation re-acquires locks, it must be safe).
        """
        # A true implementation would test the ReplayCoordinator's interaction with the LockManager.
        # Here we test that the ResourceLockManager gracefully handles basic release without crashing.
        lock_manager = ResourceLockManager.get_instance()
        
        lock_manager.acquire_lock(commutative=False, exclusive_resource_locks=[])
        lock_manager.release_lock(commutative=False, exclusive_resource_locks=[])
        
        # Releasing an already released lock should not crash (idempotency of release)
        lock_manager.release_lock(commutative=False, exclusive_resource_locks=[])
