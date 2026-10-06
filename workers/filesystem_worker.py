"""
workers/filesystem_worker.py

R1: isolated filesystem execution worker.

Runs inside a Windows Job Object sandbox (see WorkerSupervisor/WorkerSandbox)
and speaks the WorkerBase frame protocol over stdin/stdout. It executes the
canonical FilesystemAdapter (atomic temp+fsync+os.replace writes) for
EXECUTE_REQUEST frames.

Security/authority properties:
- The worker re-validates the structural intent contract at the boundary
  before touching the filesystem — the sandboxed process does not trust the
  wire payload just because the kernel sent it.
- The adapter is resolved through ADAPTER_REGISTRY (canonical lane lookup),
  not by trusting an adapter name from the payload beyond registry lookup.
- The returned digest is computed by the adapter from the FINAL on-disk
  bytes; the kernel still verifies independently after dispatch.
"""

import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from workers.worker_base import WorkerBase

from core.adapters.adapter_registry import ADAPTER_REGISTRY
from core.contracts.intent_contracts import IntentContractRegistry
from core.execution.execution_intent import (
    ExecutionIntent,
    IntentPriority,
    IntentDeterminismLevel,
    VerificationMode,
    RollbackMode,
)

logger = logging.getLogger("FilesystemWorker")


class FilesystemWorker(WorkerBase):
    """Executes filesystem intents on behalf of the kernel dispatcher."""

    def _rebuild_intent(self, d: dict) -> ExecutionIntent:
        try:
            verification_mode = VerificationMode(d.get("verification_mode", ""))
        except ValueError:
            # Formal verification mode is enforced kernel-side (the dispatcher
            # observes and hashes independently); the adapter contract does
            # not consult it. Keep execution possible with a neutral default.
            verification_mode = VerificationMode.STRUCTURAL
        try:
            rollback_strategy = RollbackMode(d.get("rollback_strategy", ""))
        except ValueError:
            rollback_strategy = RollbackMode.NO_ROLLBACK
        # to_dict() stores priority as the member NAME (int-valued enum).
        try:
            priority = IntentPriority[d.get("priority", IntentPriority.STANDARD.name)]
        except KeyError:
            priority = IntentPriority.STANDARD
        try:
            determinism = IntentDeterminismLevel(d.get("determinism", ""))
        except ValueError:
            determinism = IntentDeterminismLevel.PROBABILISTIC

        return ExecutionIntent(
            adapter=d["adapter"],
            operation=d["operation"],
            idempotent=bool(d["idempotent"]),
            verification_mode=verification_mode,
            rollback_strategy=rollback_strategy,
            capability_scope=d.get("capability_scope", {}),
            payload=d["payload"],
            intent_id=d["intent_id"],
            agent_id=d.get("agent_id", "UNKNOWN"),
            priority=priority,
            determinism=determinism,
            timeout_ms=int(d.get("timeout_ms", 30000)),
            authority_origin=d.get("authority_origin", "legacy_bridge"),
        )

    def handle_request(self, payload: dict) -> dict:
        intent_dict = payload.get("intent")
        if not isinstance(intent_dict, dict):
            raise ValueError("EXECUTE_REQUEST payload missing 'intent' object")

        intent = self._rebuild_intent(intent_dict)

        # Boundary validation: the sandboxed worker refuses malformed or
        # unsafe-runtime intents even if the sender got it wrong.
        IntentContractRegistry.validate_intent(intent)

        adapter_cls = ADAPTER_REGISTRY.get_adapter_class(intent.adapter)
        adapter = adapter_cls()
        if not adapter.initialize():
            raise RuntimeError(f"Adapter {intent.adapter} failed to initialize")
        if not adapter.attach():
            raise RuntimeError(f"Adapter {intent.adapter} failed to attach")

        result = adapter.execute(intent)
        if isinstance(result, dict) and (
            result.get("success") is False or "error" in result
        ):
            raise RuntimeError(
                result.get("error") or f"adapter {intent.adapter} reported failure"
            )
        return result


if __name__ == "__main__":
    FilesystemWorker().run()
