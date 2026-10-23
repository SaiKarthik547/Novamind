#!/usr/bin/env python3
import sys
import json
import logging
import os

from typing import Optional

from core.contracts.intent_contracts import IntentContractRegistry
from core.adapters.adapter_supervisor import ADAPTER_REGISTRY
from core.execution.execution_intent import ExecutionIntent
from core.ipc.worker_protocol import FrameType, WorkerIdentity
from workers.worker_base import WorkerBase

# Ensure it can find the core module when run as a script
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FilesystemWorker")


class FilesystemWorker(WorkerBase):
    """Worker process that executes filesystem intents with lease validation."""

    def __init__(self, supervisor=None):
        super().__init__()
        # R2-A: No independent broker - lease validation uses data from EXECUTE_REQUEST frame
        # The kernel is the authoritative body for lease state; the worker validates
        # using lease metadata included in the execution frame.
        self._supervisor = supervisor

    def _rebuild_intent(self, intent_dict: dict) -> ExecutionIntent:
        """Rebuild an ExecutionIntent from the dict sent in the EXECUTE_REQUEST frame.

        This is the canonical deserialization path: the dispatcher sends
        intent.to_dict() and the worker rebuilds the dataclass.
        """
        from core.execution.execution_intent import (
            ExecutionIntent,
            VerificationMode,
            RollbackMode,
            IntentPriority,
            IntentDeterminismLevel,
        )

        # Extract known fields; unknown fields are ignored.
        kwargs = {}
        for field_name in ExecutionIntent.__dataclass_fields__:
            if field_name in intent_dict:
                value = intent_dict[field_name]
                # Convert enum-like fields from serialized strings back to instances.
                # Enum fields are serialized by NAME (e.g. "STRICT"), so use name lookup via []
                # to avoid ValueError on name/value mismatch.
                if field_name == "verification_mode" and isinstance(value, str):
                    try:
                        value = VerificationMode[value]
                    except (ValueError, KeyError):
                        raise ValueError(f"Invalid enum name for VerificationMode: {value}")
                elif field_name == "rollback_strategy" and isinstance(value, str):
                    try:
                        value = RollbackMode[value]
                    except (ValueError, KeyError):
                        raise ValueError(f"Invalid enum name for RollbackMode: {value}")
                elif field_name == "priority" and isinstance(value, str):
                    try:
                        # Serialized form uses enum NAME (e.g. "STANDARD"), not value (1).
                        # Use name lookup via [] to avoid ValueError on name/value mismatch.
                        value = IntentPriority[value]
                    except (ValueError, KeyError):
                        raise ValueError(f"Invalid enum name for IntentPriority: {value}")
                elif field_name == "determinism" and isinstance(value, str):
                    try:
                        value = IntentDeterminismLevel[value]
                    except (ValueError, KeyError):
                        raise ValueError(f"Invalid enum name for IntentDeterminismLevel: {value}")
                kwargs[field_name] = value

        # Ensure agent_id and lease_id have proper types
        kwargs.setdefault("agent_id", "UNKNOWN")
        kwargs.setdefault("lease_id", None)

        return ExecutionIntent(**kwargs)

    def _validate_lease_at_boundary(self, intent: ExecutionIntent, lease_data: dict) -> None:
        """Validate the lease at the worker boundary.

        R2-A policy: lease is MANDATORY for canonical worker lane.
        - lease_data must contain all required fields
        - lifecycle_state must be ACTIVE
        - lease must not be revoked
        - intent must be bound to the lease (intent_id match)
        - principal and agent_id must be non-UNKNOWN for non-legacy intents

        Raises RuntimeError if validation fails (fail-closed).
        """
        # Check required lease_data fields
        required_fields = [
            "lease_intent_id",
            "lease_principal",
            "lease_agent_id",
            "lease_capabilities",
            "lease_allowed_paths",
            "lease_expiration",
            "lease_revoked",
            "lease_lifecycle_state",
        ]
        missing = [f for f in required_fields if f not in lease_data]
        if missing:
            raise RuntimeError(
                f"Lease validation data missing required fields: {missing}"
            )

        # Check lifecycle state - must be ACTIVE (fail-closed)
        lifecycle_state = lease_data.get("lease_lifecycle_state", "")
        if lifecycle_state != "ACTIVE":
            raise RuntimeError(
                f"Lease lifecycle state is '{lifecycle_state}', expected 'ACTIVE'. "
                f"Lease is not in a valid state for execution."
            )

        # Check revoked flag - must be False (fail-closed)
        if lease_data.get("lease_revoked", False) is True:
            raise RuntimeError("Lease has been revoked. Rejecting execution.")

        # Check expiry - lease must not be expired
        import time
        expiration = lease_data.get("lease_expiration", 0)
        if time.monotonic() > expiration:
            raise RuntimeError("Lease has expired. Rejecting execution.")

        # Check intent binding - lease must be bound to this intent
        lease_intent_id = lease_data.get("lease_intent_id")
        if lease_intent_id is None:
            raise RuntimeError("Lease is not bound to an intent_id. Rejecting execution.")
        if intent.intent_id != lease_intent_id:
            raise RuntimeError(
                f"Lease intent_id '{lease_intent_id}' does not match execution intent_id '{intent.intent_id}'. "
                f"Lease is not bound to this execution."
            )

        # Check principal - for non-legacy intents, principal must be known
        authority_origin = getattr(intent, "authority_origin", None)
        lease_principal = lease_data.get("lease_principal", "")
        if authority_origin != "legacy_bridge" and lease_principal == "UNKNOWN":
            raise RuntimeError(
                f"Lease principal is 'UNKNOWN' for non-legacy intent "
                f"(authority_origin={authority_origin}). "
                f"Cannot authorize unknown principal."
            )

        # Check agent_id - for non-legacy intents, agent_id must be known
        lease_agent_id = lease_data.get("lease_agent_id", "")
        if authority_origin != "legacy_bridge" and lease_agent_id == "UNKNOWN":
            raise RuntimeError(
                f"Lease agent_id is 'UNKNOWN' for non-legacy intent "
                f"(authority_origin={authority_origin}). "
                f"Cannot authorize unknown worker."
            )

        # Check capabilities - must include FILE_WRITE for filesystem.write
        lease_capabilities = set(lease_data.get("lease_capabilities", []))
        required_caps = {"FILE_WRITE"}
        if not required_caps.issubset(lease_capabilities):
            raise RuntimeError(
                f"Lease missing required capabilities {required_caps - lease_capabilities}. "
                f"Required: {required_caps}"
            )

        # Check target path - the lease must allow the target path
        target_path = getattr(intent, "payload", {}).get("path", "")
        allowed_paths = lease_data.get("lease_allowed_paths", [])
        path_ok = False
        for allowed in allowed_paths:
            norm_allowed = os.path.normpath(allowed)
            norm_target = os.path.normpath(target_path)
            if norm_target == norm_allowed or norm_target.startswith(norm_allowed + os.sep):
                path_ok = True
                break

        if not path_ok:
            raise RuntimeError(
                f"Lease does not allow target path '{target_path}'. "
                f"Allowed paths: {allowed_paths}"
            )

    def handle_request(self, payload: dict) -> dict:
        """Handle an EXECUTE_REQUEST frame from the supervisor.

        R2-A: lease validation is performed before adapter execution.
        The lease data is extracted from the payload and validated authoritatively.
        """
        intent_dict = payload.get("intent")
        if not isinstance(intent_dict, dict):
            raise ValueError("EXECUTE_REQUEST payload missing 'intent' object")

        intent = self._rebuild_intent(intent_dict)

        # R2-A: Extract lease validation data from the payload.
        # The data is included in the EXECUTE_REQUEST frame by the dispatcher
        # so the worker can validate the lease without needing shared broker state.
        lease_data = payload.get("intent", {}).get("lease_validation_data")

        # &R2-A / R1 Authorization Policy ─────────────────────────────────
        # Canonical worker lane (filesystem.write, etc.): lease is MANDATORY.
        #   Missing lease_data → REJECTED (fail-closed, no silent fallback).
        #   Present but invalid → REJECTED.
        #   This is the ONLY path for permanent OS effects.
        #
        # R1 legacy lane: intents explicitly opting into the legacy CapabilityRegistry
        # authority may omit lease_data. This mode is restricted, tested, and
        # documented for temporary removal. It does NOT silently bypass the new
        # lease requirement for the canonical lane.
        #
        # The decision is based solely on whether we are in the canonical worker lane
        # or the R1 legacy lane, not on whether lease_id happens to be present.
        #
        if lease_data is not None:
            # Canonical R2-A path: lease_data present → validate it (fail-closed)
            try:
                self._validate_lease_at_boundary(intent, lease_data)
            except RuntimeError as e:
                # Fail closed: reject if lease data is present but invalid
                raise RuntimeError(str(e))
        else:
            # R1 legacy path: no lease_data → require explicit legacy mode
            # Check if this intent is authorized for R1 legacy execution
            # by verifying it has a CapabilityRegistry authority.
            # Only 'legacy_bridge' explicitly opts into the pre-R2-A regime.
            # `authority_origin="kernel"` does NOT grant a lease-free bypass —
            # the canonical worker lane always requires a valid lease.
            legacy_origin = getattr(intent, "authority_origin", None)
            if legacy_origin != "legacy_bridge":
                # Not explicitly marked as legacy → reject missing lease
                # This enforces the canonical R2-A policy: all permanent effects
                # must go through the lease boundary, regardless of origin.
                # `authority_origin="kernel"` is not a legacy exemption.
                raise RuntimeError(
                    "Missing ExecutionLease validation data at worker boundary: "
                    "no lease_data present and intent not marked as legacy-authorized"
                )
            # Legacy-authorized intent: skip broker validation, rely on
            # CapabilityRegistry authority as before.
            logger.warning(
                f"R1 legacy intent without lease_data: intent_id={intent.intent_id[:8]} "
                f"authority_origin={legacy_origin}. Skipping lease validation, "
                f"relying on CapabilityRegistry authority."
            )

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
    worker = FilesystemWorker()
    worker.run()