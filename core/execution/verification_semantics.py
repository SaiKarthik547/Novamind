"""
core/execution/verification_semantics.py

Phase 15A.5: Async Execution & Passive Verification Semantics.
Decouples execution dispatch success from actual runtime mutation success.
Replaces self-certifying execution with rigorous, independent observation.
"""

import time
import logging
import threading
from typing import Optional, Any, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod

from core.execution.intent_result import IntentResult
from core.execution.execution_intent import IntentStatus

logger = logging.getLogger("VerificationSemantics")

class VerificationError(Exception):
    """Raised when passive verification detects that expected state mutation did not occur."""
    pass

class PassiveVerifier(ABC):
    """
    Interface for independent verification domains.
    Implementations must NEVER mutate state, only observe it.
    """
    
    @abstractmethod
    def verify_mutation(self, target_hwnd: Optional[int], pre_state: Any, timeout: float) -> bool:
        """
        Polls or observes the runtime state until the expected mutation completes,
        or the timeout expires.
        """
        pass

@dataclass
class AsyncExecutionFuture:
    """
    Represents an intent that has been successfully dispatched to the OS layer,
    but whose actual side-effects (mutations) have not yet been observed.
    """
    intent_id: str
    target_hwnd: Optional[int]
    dispatch_success: bool
    dispatch_metrics: dict
    pre_state_snapshot: Any
    verifier: Optional[PassiveVerifier]
    
    _completion_event: threading.Event = threading.Event()
    _final_result: Optional[IntentResult] = None
    
    def resolve(self, result: IntentResult) -> None:
        """Called when verification successfully concludes."""
        self._final_result = result
        self._completion_event.set()
        
    def wait(self, timeout: float) -> IntentResult:
        """
        Blocks the execution caller until the passive verifier confirms the state mutation.
        """
        if not self._completion_event.wait(timeout=timeout):
            logger.warning(f"[AsyncFuture] Intent {self.intent_id} timed out during passive verification.")
            return IntentResult(
                intent_id=self.intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=f"Verification watchdog timeout ({timeout}s) exceeded.",
                metrics=self.dispatch_metrics
            )
        return self._final_result

class VerificationCoordinator:
    """
    Spawns background watchers to verify async execution futures.
    """
    _instance = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'VerificationCoordinator':
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
            
    def verify_future(self, future: AsyncExecutionFuture, timeout: float) -> None:
        """
        Spawns a thread to wait for the passive verifier.
        """
        if not future.dispatch_success or future.verifier is None:
            # If dispatch failed, or no verifier is provided, resolve immediately
            future.resolve(IntentResult(
                intent_id=future.intent_id,
                status=IntentStatus.COMPLETED if future.dispatch_success else IntentStatus.FAILED,
                success=future.dispatch_success,
                payload={},
                metrics=future.dispatch_metrics
            ))
            return

        def _watchdog():
            start = time.monotonic()
            try:
                success = future.verifier.verify_mutation(future.target_hwnd, future.pre_state_snapshot, timeout)
                duration = time.monotonic() - start
                
                metrics = dict(future.dispatch_metrics)
                metrics["verification_duration_ms"] = int(duration * 1000)
                
                if success:
                    future.resolve(IntentResult(
                        intent_id=future.intent_id,
                        status=IntentStatus.COMPLETED,
                        success=True,
                        payload={},
                        metrics=metrics
                    ))
                else:
                    future.resolve(IntentResult(
                        intent_id=future.intent_id,
                        status=IntentStatus.FAILED,
                        success=False,
                        payload={},
                        error="Passive verification failed. State did not mutate as expected.",
                        metrics=metrics
                    ))
            except Exception as e:
                logger.error(f"[VerificationCoordinator] Verifier crashed for {future.intent_id}: {e}", exc_info=True)
                future.resolve(IntentResult(
                    intent_id=future.intent_id,
                    status=IntentStatus.FAILED,
                    success=False,
                    payload={},
                    error=f"Verifier crash: {e}",
                    metrics=future.dispatch_metrics
                ))

        threading.Thread(target=_watchdog, daemon=True, name=f"Verifier_{future.intent_id[:8]}").start()
