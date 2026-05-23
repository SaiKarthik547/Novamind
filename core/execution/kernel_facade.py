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

    def __init__(self):
        self._registry = CAPABILITY_REGISTRY
        # Adapter registry is imported lazily to avoid circular imports at module load
        self._active_intents: Dict[str, float] = {}  # intent_id -> start_time

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
    ) -> Dict[str, Any]:
        """
        Route a capability request through the kernel.

        Raises PermissionError if the capability is not registered.
        Returns a result dict with keys: success, data, error, authority_origin,
        determinism_class, duration_ms.
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
        try:
            _sm_advance(sm, IntentExecutionState.QUEUED)
            _sm_advance(sm, IntentExecutionState.DISPATCHED)
            _sm_advance(sm, IntentExecutionState.RUNNING)

            if defn.determinism_class == DeterminismClass.NON_DETERMINISTIC:
                result = self._route_legacy(capability, payload, intent_meta)
            else:
                result = self._route_adapter(capability, payload, intent_meta, timeout)

            _sm_advance(sm, IntentExecutionState.VERIFYING)
            _sm_advance(sm, IntentExecutionState.COMPLETED)

        except Exception as exc:
            logger.error(f"[KernelFacade] Intent {intent_id[:8]} FAILED with exception: {exc}", exc_info=True)
            _sm_advance(sm, IntentExecutionState.FAILED)
            return self._error_result(intent_id, str(exc), capability, authority_origin, start)
        finally:
            self._active_intents.pop(intent_id, None)

        # ── Step 5: Stamp authority metadata on result ────────────────────
        duration_ms = int((time.monotonic() - start) * 1000)
        result["intent_id"] = intent_id
        result["authority_origin"] = authority_origin
        result["determinism_class"] = defn.determinism_class.value
        result["duration_ms"] = duration_ms

        logger.info(
            f"[KernelFacade] Intent {intent_id[:8]} completed in {duration_ms}ms | "
            f"success={result.get('success', False)}"
        )
        return result

    # ── Routing paths ────────────────────────────────────────────────────────

    def _route_adapter(
        self,
        capability: str,
        payload: Dict[str, Any],
        intent_meta: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
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
        )

        dispatcher = IntentDispatcher()
        return dispatcher.dispatch_sync(intent)

    def _route_legacy(
        self,
        capability: str,
        payload: Dict[str, Any],
        intent_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Route to the quarantined LegacyUIAdapter.
        Only NON_DETERMINISTIC capabilities reach here.
        This path is NOT replayed. It is observational only.
        """
        try:
            from core.legacy.legacy_ui_adapter import LegacyUIAdapter
            adapter = LegacyUIAdapter()
            return adapter.execute_capability(capability, payload)
        except ImportError:
            return {
                "success": False,
                "error": "LegacyUIAdapter not available. Cannot execute NON_DETERMINISTIC capability.",
                "capability": capability,
            }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _error_result(
        self,
        intent_id: str,
        error: str,
        capability: str,
        authority_origin: str,
        start: float,
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "error": error,
            "intent_id": intent_id,
            "capability": capability,
            "authority_origin": authority_origin,
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
