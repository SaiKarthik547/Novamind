import logging
from enum import Enum
import threading
from typing import Callable, List

logger = logging.getLogger("LifecycleAuthority")

class RuntimeLifecycleState(str, Enum):
    INITIALIZING = "INITIALIZING"
    RECONCILING = "RECONCILING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    HALTING = "HALTING"
    HALTED = "HALTED"
    PANIC = "PANIC"

class LifecycleAuthority:
    """
    Phase 15B: Sole owner of runtime lifecycle state.
    Execution components must request transitions from this authority.
    """
    def __init__(self):
        self._state = RuntimeLifecycleState.INITIALIZING
        self._lock = threading.RLock()
        self._shutdown_callbacks: List[Callable] = []
        logger.info("LifecycleAuthority: INITIALIZING")
        
    def get_state(self) -> RuntimeLifecycleState:
        with self._lock:
            return self._state
            
    def transition_to_reconciling(self):
        with self._lock:
            if self._state != RuntimeLifecycleState.INITIALIZING:
                raise RuntimeError(f"Cannot transition to RECONCILING from {self._state}")
            self._state = RuntimeLifecycleState.RECONCILING
            logger.info("LifecycleAuthority: RECONCILING")
            
    def transition_to_ready(self):
        with self._lock:
            if self._state not in (RuntimeLifecycleState.RECONCILING, RuntimeLifecycleState.INITIALIZING, RuntimeLifecycleState.DEGRADED):
                raise RuntimeError(f"Cannot transition to READY from {self._state}")
            self._state = RuntimeLifecycleState.READY
            logger.info("LifecycleAuthority: READY")
            
    def transition_to_degraded(self, reason: str):
        with self._lock:
            if self._state not in (RuntimeLifecycleState.READY, RuntimeLifecycleState.RECONCILING):
                raise RuntimeError(f"Cannot transition to DEGRADED from {self._state}")
            self._state = RuntimeLifecycleState.DEGRADED
            logger.warning(f"LifecycleAuthority: DEGRADED. Reason: {reason}")
            
    def register_shutdown_callback(self, callback: Callable):
        with self._lock:
            if callback not in self._shutdown_callbacks:
                self._shutdown_callbacks.append(callback)

    def trigger_shutdown(self, reason: str):
        with self._lock:
            if self._state in (RuntimeLifecycleState.HALTING, RuntimeLifecycleState.HALTED, RuntimeLifecycleState.PANIC):
                return
            self._state = RuntimeLifecycleState.HALTING
            logger.info(f"LifecycleAuthority: HALTING. Reason: {reason}")
            
            for cb in self._shutdown_callbacks:
                try:
                    cb()
                except Exception as e:
                    logger.error(f"Error during shutdown callback: {e}")
                    
            self._state = RuntimeLifecycleState.HALTED
            logger.info("LifecycleAuthority: HALTED")
            
    def trigger_panic(self, reason: str):
        with self._lock:
            if self._state == RuntimeLifecycleState.PANIC:
                return
            self._state = RuntimeLifecycleState.PANIC
            logger.critical(f"LifecycleAuthority: PANIC! Reason: {reason}")
            
            for cb in self._shutdown_callbacks:
                try:
                    cb()
                except Exception as e:
                    logger.error(f"Error during panic callback: {e}")
