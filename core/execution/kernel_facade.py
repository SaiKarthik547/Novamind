"""
core/execution/kernel_facade.py

Phase 15A: KernelExecutionFacade — Execution Gateway Only.

This module acts exclusively as the gateway to the Multi-Lane OS Interaction Layer.
It does NOT own execution ordering, replay coordination, lifecycle tracking, or queueing.
Those responsibilities have been strictly deferred to the ExecutionScheduler and 
IntentGovernance layers.

Execution Flow:
Agent -> ExecutionIntent -> IntentGovernance -> ExecutionScheduler -> KernelFacade -> Multi-Lane Adapter
"""

import logging
import time
from typing import Any, Dict

from core.execution.capability_registry import CAPABILITY_REGISTRY, DeterminismClass
from core.execution.intent_result import IntentResult
from core.execution.execution_intent import IntentStatus

logger = logging.getLogger("KernelExecutionFacade")

class KernelExecutionFacade:
    """
    Execution Gateway.
    Receives validated, scheduled execution intents from the ExecutionScheduler.
    Routes to the correct OS Interaction Lane (UIA, Win32, Browser, COM, HID fallback).
    """

    def __init__(self, dispatcher=None):
        self._registry = CAPABILITY_REGISTRY
        self._dispatcher = dispatcher

    def execute_gateway(
        self,
        capability: str,
        payload: Dict[str, Any],
        intent_meta: Dict[str, Any],
        timeout: float,
    ) -> IntentResult:
        """
        Final gateway to the multi-lane adapters.
        Called exclusively by the ExecutionScheduler after ordering/locks are secured.
        """
        start = time.monotonic()
        intent_id = intent_meta["intent_id"]
        
        logger.debug(f"[KernelFacade] Gateway executing {intent_id[:8]} -> {capability}")

        try:
            # Re-fetch capability definition (already validated by Governance, but needed for routing)
            defn = self._registry.require(capability)
            
            # Phase 15B Preview: Multi-Lane routing logic will be inserted here.
            # Currently routing to transitional handlers.
            if defn.determinism_class == DeterminismClass.NON_DETERMINISTIC:
                result = self._route_legacy(capability, payload, intent_meta)
            else:
                result = self._route_adapter(capability, payload, intent_meta, timeout)
                
            # Gateway metrics (No WAL or Replay logic here)
            duration_ms = int((time.monotonic() - start) * 1000)
            final_metrics = dict(result.metrics)
            final_metrics.update({
                "gateway_duration_ms": duration_ms
            })
            
            return IntentResult(
                intent_id=intent_id,
                status=result.status,
                success=result.success,
                payload=result.payload,
                error=result.error,
                metrics=final_metrics
            )

        except Exception as exc:
            logger.error(f"[KernelFacade] Gateway execution failed for {intent_id[:8]}: {exc}", exc_info=True)
            return IntentResult(
                intent_id=intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=str(exc),
                metrics={"gateway_duration_ms": int((time.monotonic() - start) * 1000)}
            )

    # ── Transitional Routing paths (To be replaced in 15B) ────────────────────

    def _route_adapter(
        self,
        capability: str,
        payload: Dict[str, Any],
        intent_meta: Dict[str, Any],
        timeout: float,
    ) -> IntentResult:
        from core.execution.execution_intent import ExecutionIntent, VerificationMode, RollbackMode
        adapter_name, operation = capability.split(".", 1)

        intent = ExecutionIntent(
            adapter=adapter_name,
            operation=operation,
            idempotent=intent_meta.get("idempotent", False),
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={"capability": capability},
            payload=payload,
            intent_id=intent_meta["intent_id"]
        )

        if self._dispatcher:
            return self._dispatcher.dispatch_sync(intent)
        else:
            raise RuntimeError("KernelExecutionFacade has no dispatcher injected for structural routing.")

    def _route_legacy(
        self,
        capability: str,
        payload: Dict[str, Any],
        intent_meta: Dict[str, Any],
    ) -> IntentResult:
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
