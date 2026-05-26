"""
core/execution/kernel_facade.py
L1-B: KernelExecutionFacade — The ONLY allowed execution surface for all agents.

This is the transitional authority bridge. It routes ExecutionIntent payloads
to either:
  (a) A registered Adapter (deterministic/semi-deterministic path), or
  (b) A LegacyExecutor (non-deterministic legacy fallback, strictly quarantined).

Architecture rules enforced here:
- No caller may spawn processes, write files, or click UI elements directly.
- All intents MUST be registered in the CapabilityRegistry.
- authority_origin is ALWAYS stamped on outgoing intents.
- NON_DETERMINISTIC capabilities are routed ONLY through the legacy bridge.
- Parallel execution is FORBIDDEN unless intent.commutative == True.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

from core.execution.capability_registry import (
    CAPABILITY_REGISTRY,
    AuthorityLevel,
    DeterminismClass,
)
from core.execution.intent_execution_state import (
    IntentStateMachine,
    IntentExecutionState,
    IntentStateError,
)
from core.execution.intent_result import IntentResult
from core.execution.execution_intent import IntentStatus

logger = logging.getLogger("KernelExecutionFacade")

# ─────────────────────────────────────────────────────────────────────────────
#  Internal constants
# ─────────────────────────────────────────────────────────────────────────────

_AUTHORITY_ORIGIN_ADAPTER = "kernel"
_AUTHORITY_ORIGIN_LEGACY  = "legacy_bridge"
_AUTHORITY_ORIGIN_UNSAFE  = "unsafe_runtime"   # Should NEVER appear in converged state


def _sm_advance(sm: "IntentStateMachine", state: "IntentExecutionState") -> None:
    """
    Advance the intent state machine without crashing the kernel on error.
    State machine transitions are authoritative lifecycle tracking \u2014 but a
    tracking failure must NEVER prevent actual execution.
    """
    try:
        sm.transition(state)
    except IntentStateError as e:
        logger.warning(f"[KernelFacade] State machine transition error (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  Facade
# ─────────────────────────────────────────────────────────────────────────────

class KernelExecutionFacade:
    """
    Transitional authority bridge.

    Agents do NOT call subprocess, os, pyautogui, or any adapter directly.
    They produce an intent dict and pass it here. The Facade decides the route.

    Usage:
        facade = KernelExecutionFacade()
        result = facade.dispatch(
            capability="filesystem.write",
            payload={"path": "...", "content": "..."},
            idempotent=False,
        )
    """

    def __init__(self, dispatcher=None):
        self._registry = CAPABILITY_REGISTRY
        self._active_intents: Dict[str, float] = {}  # intent_id -> start_time
        
        if dispatcher is None:
            # Transitional fallback until callers explicitly inject RuntimeKernel
            from core.execution.runtime_kernel import RuntimeKernel
            dispatcher = RuntimeKernel.get_instance().dispatcher
        self._dispatcher = dispatcher

    # ── Public API ───────────────────────────────────────────────────────────

    def dispatch(
        self,
        capability: str,
        payload: Dict[str, Any],
        *,
        idempotent: bool = False,
        commutative: bool = False,
        parent_intent_id: Optional[str] = None,
        causation_chain: Optional[list] = None,
        exclusive_resource_locks: Optional[list] = None,
        timeout: float = 30.0,
    ) -> IntentResult:
        """
        Route a capability request through the kernel.

        Raises PermissionError if the capability is not registered.
        Returns an IntentResult.
        """
        intent_id = str(uuid.uuid4())
        start = time.monotonic()

        # L2.5-C: Intent state machine — every intent is lifecycle-tracked
        sm = IntentStateMachine(intent_id)

        # ── Step 1: Capability gate ───────────────────────────────────────
        try:
            defn = self._registry.require(capability)
        except PermissionError as e:
            logger.error(f"[KernelFacade] BLOCKED: {e}")
            try:
                sm.transition(IntentExecutionState.REJECTED)
            except IntentStateError as sme:
                logger.warning(f"[KernelFacade] State machine error on REJECTED: {sme}")
            return self._error_result(intent_id, str(e), capability, _AUTHORITY_ORIGIN_UNSAFE, start)

        # ── Step 2: Authority classification ─────────────────────────────
        authority_origin = (
            _AUTHORITY_ORIGIN_LEGACY
            if defn.determinism_class == DeterminismClass.NON_DETERMINISTIC
            else _AUTHORITY_ORIGIN_ADAPTER
        )

        logger.info(
            f"[KernelFacade] Dispatching intent {intent_id[:8]} | "
            f"capability={capability} | authority={authority_origin} | "
            f"determinism={defn.determinism_class.value} | idempotent={idempotent}"
        )

        # ── Step 3: Build augmented intent record ─────────────────────────
        intent_meta = {
            "intent_id": intent_id,
            "parent_intent_id": parent_intent_id,
            "causation_chain": (causation_chain or []) + [intent_id],
            "capability": capability,
            "determinism_class": defn.determinism_class.value,
            "replay_policy": defn.replay_policy.value,
            "trust_level": defn.trust_level.value,
            "authority_origin": authority_origin,
            "idempotent": idempotent,
            "commutative": commutative,
            "exclusive_resource_locks": exclusive_resource_locks or [],
            "requires_user_focus": defn.requires_user_focus,
        }

        # CONCURRENCY RULE: Parallel intent execution is FORBIDDEN unless intent.commutative == True.
        # The kernel is single-authority. Non-commutative intents must be serialized.
        # Violation of this rule causes WAL lineage nondeterminism.
        # See: core/execution/verification_taxonomy.py for determinism-mode cross-validation.

        # ── Step 4: Route to correct execution path ───────────────────────
        self._active_intents[intent_id] = start
        
        from core.execution.resource_lock_manager import ResourceLockManager
        lock_manager = ResourceLockManager.get_instance()
        lock_manager.acquire_lock(commutative, exclusive_resource_locks)
        
        try:
            _sm_advance(sm, IntentExecutionState.QUEUED)
            
            # P13B-1: Enforce WAL Persistence Barrier before DISPATCHED
            from core.execution.recovery_journal import RecoveryJournal
            journal = RecoveryJournal.get_instance()
            journal.log_transition(intent_id, IntentExecutionState.QUEUED, intent_meta)
            
            _sm_advance(sm, IntentExecutionState.DISPATCHED)
            journal.log_transition(intent_id, IntentExecutionState.DISPATCHED)
            
            _sm_advance(sm, IntentExecutionState.RUNNING)
            journal.log_transition(intent_id, IntentExecutionState.RUNNING)

            if defn.determinism_class == DeterminismClass.NON_DETERMINISTIC:
                result = self._route_legacy(capability, payload, intent_meta)
            else:
                result = self._route_adapter(capability, payload, intent_meta, timeout)

            _sm_advance(sm, IntentExecutionState.VERIFYING)
            journal.log_transition(intent_id, IntentExecutionState.VERIFYING)
            
            _sm_advance(sm, IntentExecutionState.COMPLETED)
            journal.log_transition(intent_id, IntentExecutionState.COMPLETED)

        except Exception as exc:
            logger.error(f"[KernelFacade] Intent {intent_id[:8]} FAILED with exception: {exc}", exc_info=True)
            
            # P13D-2: Adapter crash/orphan detection
            # Heuristic: Connection errors or specific runtime errors indicate the adapter process died
            is_adapter_crash = isinstance(exc, (ConnectionError, BrokenPipeError, EOFError))
            
            if is_adapter_crash:
                _sm_advance(sm, IntentExecutionState.ORPHANED)
                # P13D-3: Integrate PanicManager
                try:
                    from core.transaction.panic_manager import PanicManager, PanicLevel
                    pm = PanicManager()
                    pm.invoke_panic(PanicLevel.RECOVERABLE, f"Adapter crashed during intent {intent_id}", "adapter_worker")
                except Exception as pm_exc:
                    logger.error(f"Failed to invoke PanicManager: {pm_exc}")
                    
                try:
                    from core.execution.recovery_journal import RecoveryJournal
                    RecoveryJournal.get_instance().log_transition(intent_id, IntentExecutionState.ORPHANED)
                except Exception:
                    pass
            else:
                _sm_advance(sm, IntentExecutionState.FAILED)
                try:
                    from core.execution.recovery_journal import RecoveryJournal
                    RecoveryJournal.get_instance().log_transition(intent_id, IntentExecutionState.FAILED)
                except Exception:
                    pass
            
            return self._error_result(intent_id, str(exc), capability, authority_origin, start)
        finally:
            self._active_intents.pop(intent_id, None)
            lock_manager.release_lock(commutative, exclusive_resource_locks)

        # ── Step 5: Stamp authority metadata on result ────────────────────
        duration_ms = int((time.monotonic() - start) * 1000)
        
        # Result is now an immutable IntentResult, we must return a new one with updated metrics
        final_metrics = dict(result.metrics)
        final_metrics.update({
            "authority_origin": authority_origin,
            "determinism_class": defn.determinism_class.value,
            "duration_ms": duration_ms
        })
        
        final_result = IntentResult(
            intent_id=intent_id,
            status=result.status,
            success=result.success,
            payload=result.payload,
            error=result.error,
            metrics=final_metrics
        )

        try:
            from core.observability.runtime_metrics import RuntimeMetrics
            RuntimeMetrics.get_instance().record_intent_completion(final_result)
        except Exception as e:
            logger.warning(f"Failed to record runtime metrics: {e}")

        logger.info(
            f"[KernelFacade] Intent {intent_id[:8]} completed in {duration_ms}ms | "
            f"success={final_result.success}"
        )
        return final_result

    # ── Routing paths ────────────────────────────────────────────────────────

    def _route_adapter(
        self,
        capability: str,
        payload: Dict[str, Any],
        intent_meta: Dict[str, Any],
        timeout: float,
    ) -> IntentResult:
        """
        Route to registered kernel Adapter.
        Adapter name is the first segment of the capability (e.g. "filesystem" from "filesystem.write").
        """
        from core.execution.execution_intent import ExecutionIntent, VerificationMode, RollbackMode
        from core.execution.intent_dispatcher import IntentDispatcher

        adapter_name, operation = capability.split(".", 1)

        intent = ExecutionIntent(
            adapter=adapter_name,
            operation=operation,
            idempotent=intent_meta["idempotent"],
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={"capability": capability},
            payload=payload,
            intent_id=intent_meta["intent_id"]
        )

        return self._dispatcher.dispatch_sync(intent)

    def _route_legacy(
        self,
        capability: str,
        payload: Dict[str, Any],
        intent_meta: Dict[str, Any],
    ) -> IntentResult:
        """
        Route to the quarantined LegacyUIAdapter.
        Only NON_DETERMINISTIC capabilities reach here.
        This path is NOT replayed. It is observational only.
        """
        try:
            from core.legacy.legacy_ui_adapter import LegacyUIAdapter
            adapter = LegacyUIAdapter()
            result_dict = adapter.execute_capability(capability, payload)
            return IntentResult(
                intent_id=intent_meta["intent_id"],
                status=IntentStatus.COMPLETED if result_dict.get("success", False) else IntentStatus.FAILED,
                success=result_dict.get("success", False),
                payload=result_dict
            )
        except ImportError:
            return IntentResult(
                intent_id=intent_meta["intent_id"],
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error="LegacyUIAdapter not available. Cannot execute NON_DETERMINISTIC capability."
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _error_result(
        self,
        intent_id: str,
        error: str,
        capability: str,
        authority_origin: str,
        start: float,
    ) -> IntentResult:
        return IntentResult(
            intent_id=intent_id,
            status=IntentStatus.FAILED,
            success=False,
            payload={},
            error=error,
            metrics={
                "capability": capability,
                "authority_origin": authority_origin,
                "duration_ms": int((time.monotonic() - start) * 1000)
            }
        )
