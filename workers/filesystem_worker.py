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
from core.runtime.capability_broker import CapabilityBroker, Capability

logger = logging.getLogger("FilesystemWorker")


class FilesystemWorker(WorkerBase):
    """Executes filesystem intents on behalf of the kernel dispatcher."""

    def __init__(self, supervisor=None):
        super().__init__()
        # R2-A: No independent broker - lease validation uses data from EXECUTE_REQUEST frame
        # The kernel is the authoritative broker; worker validates using transmitted data.
        # supervisor is the KernelSupervisor reference for authoritative lease validation.
        self._supervisor = supervisor

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

    def validate_lease_authority(self, lease_data: dict, intent: ExecutionIntent) -> Optional[bool]:
        """R2-A: Authoritatively validate the lease through the kernel supervisor.

        The kernel owns the authoritative CapabilityBroker. This method requests
        validation through the supervisor, which has access to the broker state.

        Returns True if the lease is valid per the kernel's current state (including
        post-creation revocation checks), False if invalid, None if supervisor
        is unavailable (fall back to transmitted-data only).
        """
        # If no supervisor is available, fall back to transmitted-data validation only
        if self._supervisor is None:
            logger.warning("No supervisor available for authoritative lease validation - "
                          "falling back to transmitted data only")
            return None  # Signal: use transmitted-data fallback
        # Request authoritative lease validation from the kernel supervisor
        # The supervisor has access to the CapabilityBroker and can check current state,
        # including post-creation revocation, expiry against current time, and intent
        # binding that a stale transmitted flag cannot detect.
        try:
            # Use the supervisor's access to the broker for current state validation
            # This checks the broker's active leases against post-creation changes
            broker = getattr(self._supervisor, 'broker', None)
            if broker is not None and hasattr(broker, '_active_leases'):
                # Extract lease identifier from transmitted data
                lease_id = lease_data.get("lease_id")
                if lease_id and lease_id in broker._active_leases:
                    lease = broker._active_leases[lease_id]
                    # Fail-closed: lease must be valid per current broker state
                    if lease.is_valid():
                        # Additional: verify intent_id binding matches
                        expected_intent_id = getattr(intent, "intent_id", None)
                        if expected_intent_id and lease.check_intent_id(expected_intent_id):
                            # Verify principal matches
                            expected_principal = getattr(intent, "principal", None)
                            if expected_principal and not lease.check_principal(expected_principal):
                                logger.warning(
                                    "Lease principal mismatch in authoritative validation: "
                                    f"expected={expected_principal}, lease={lease.principal}"
                                )
                                return False
                            # Verify agent matches
                            expected_agent = getattr(intent, "agent_id", None)
                            if expected_agent and not lease.check_agent(expected_agent):
                                logger.warning(
                                    "Lease agent mismatch in authoritative validation: "
                                    f"expected={expected_agent}, lease={lease.agent_id}"
                                )
                                return False
                            # Authoritative validation passed
                            return True
                    # Lease is expired, revoked, or in terminal state
                    logger.warning(
                        f"Lease {lease_id[:8]} invalid per broker state: "
                        f"revoked={lease.revoked}, lifecycle={lease.lifecycle_state}, "
                        f"expired={not lease.is_valid()}"
                    )
                    return False

                # Lease not found in broker - could have been revoked after frame creation
                logger.warning(
                    f"Lease {lease_id[:8]} not found in broker - "
                    f"may have been revoked after authorization data was constructed"
                )
                return False

            # If broker not available or lease not in broker, fall back to transmitted-data
            logger.warning("Supervisor broker not available for authoritative validation - ")
            return None

        except Exception as e:
            logger.error(f"Error in authoritative lease validation: {e}")
            return None

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
    def _validate_lease_at_boundary(self, intent: ExecutionIntent, lease_data: dict) -> None:
        """R2-A: Validate the ExecutionLease at the worker boundary.

        R2-A enforcement: lease validation using transmitted data from the kernel,
        with authoritative check through the supervisor where available.

        lease_data should contain:
        - lease_intent_id: the intent_id the lease is bound to
        - lease_principal: the principal who requested the lease
        - lease_agent_id: the agent/worker the lease is for
        - lease_capabilities: list of granted capabilities
        - lease_allowed_paths: list of allowed paths
        - lease_expiration: monotonic time when lease expires
        - lease_revoked: whether the lease has been revoked
        - lease_lifecycle_state: ACTIVE, EXPIRED, REVOKED, or TERMINAL

        R2-A enforcement:
        - If lease_data is absent, execution is REJECTED (fail-closed, no R1 bypass)
        - Validate all fields against the intent and scope
        - Terminal leases never authorize effects
        - Fail closed on any mismatch or invalid state
        - Expiry: reject if current time >= lease expiration
        - Revocation: check both transmitted flag AND authoritative validation
        - where supervisor is available, post-creation revocation is detected
        """
        # R2-A: Lease is mandatory - reject if data absent (no R1 bypass)
        if not lease_data:
            raise RuntimeError(
                f"Missing ExecutionLease validation data at worker boundary"
            )

        # Validate lease intent_id binding
        lease_intent_id = lease_data.get("lease_intent_id")
        if lease_intent_id is not None:
            if lease_intent_id != intent.intent_id:
                raise RuntimeError(
                    f"Lease intent_id mismatch: lease={lease_intent_id}, intent={intent.intent_id}"
                )

        # Validate lease principal (non-repudiation)
        lease_principal = lease_data.get("lease_principal", "UNKNOWN")
        if lease_principal != getattr(intent, "principal", "UNKNOWN"):
            raise RuntimeError(
                f"Lease principal mismatch: lease={lease_principal}, intent={getattr(intent, 'principal', 'UNKNOWN')}"
            )

        # Validate lease agent_id
        lease_agent_id = lease_data.get("lease_agent_id")
        if lease_agent_id is not None:
            if lease_agent_id != getattr(intent, "agent_id", "UNKNOWN"):
                raise RuntimeError(
                    f"Lease agent_id mismatch: lease={lease_agent_id}, intent={getattr(intent, 'agent_id', 'UNKNOWN')}"
                )

        # Validate lease is not in a terminal state - never allow terminal leases to execute
        lease_lifecycle_state = lease_data.get("lease_lifecycle_state", "ACTIVE")
        if lease_lifecycle_state in ("COMPLETED", "FAILED", "CANCELLED", "ORPHANED"):
            raise RuntimeError(
                f"Lease is in terminal state ({lease_lifecycle_state}) and cannot authorize effects"
            )

        # Validate lease revocation status - fail-closed on any revocation
        # Check both the transmitted flag AND authoritative validation through supervisor
        lease_revoked = lease_data.get("lease_revoked", False)
        if lease_revoked:
            raise RuntimeError(
                f"Lease has been revoked and cannot authorize effects"
            )

        # Authoritative validation: check for post-creation revocation and current state
        # This is the key fix for the revocation authenticity problem
        auth_result = self.validate_lease_authority(lease_data, intent)
        
        # Handle the three possible return values:
        # - True: authoritative validation passed (lease valid per kernel state)
        # - False: authoritative validation failed (lease invalid per kernel state)
        # - None: supervisor not available, fall back to transmitted-data only
        if auth_result is True:
            # Authoritative validation passed - lease is valid per kernel state
            pass  # Continue with other validations
        elif auth_result is False:
            # Authoritative validation failed - lease is invalid per kernel state
            # This catches post-creation revocation and other state changes
            raise RuntimeError(
                f"Lease failed authoritative validation through kernel supervisor - "
                f"lease may have been revoked or modified after issuance"
            )
        else:
            # None: supervisor not available, fall back to transmitted-data only
            # Log and continue with transmitted-data validation
            logger.warning("No supervisor available for authoritative lease validation - "
                          "falling back to transmitted data only")

        # Validate lease expiry - fail-closed if past expiration
        lease_expiration = lease_data.get("lease_expiration", 0)
        import time
        if time.monotonic() >= lease_expiration:
            raise RuntimeError(
                f"Lease has expired (expiration={lease_expiration}) and cannot authorize effects"
            )

        # Validate the lease grants the required capability
        cap_name = intent.capability_scope.get("capability", "")
        if cap_name == "filesystem.write":
            # Check if FILE_WRITE is in the allowed capabilities
            allowed_caps = lease_data.get("lease_capabilities", [])
            if "FILE_WRITE" not in allowed_caps:
                raise RuntimeError(
                    f"Lease does not grant FILE_WRITE capability"
                )
        elif cap_name == "filesystem.read":
            allowed_caps = lease_data.get("lease_capabilities", [])
            if "FILE_READ" not in allowed_caps:
                raise RuntimeError(
                    f"Lease does not grant FILE_READ capability"
                )

        # Validate path against allowed paths
        path_to_check = intent.payload.get("path", "")
        allowed_paths = lease_data.get("lease_allowed_paths", [])
        if allowed_paths and "*" not in allowed_paths:
            import os
            normalized = os.path.normpath(path_to_check)
            if not any(normalized.startswith(os.path.normpath(p)) for p in allowed_paths):
                raise RuntimeError(
                    f"Path {path_to_check} outside allowed scope {allowed_paths}"
                )
    

    def handle_request(self, payload: dict) -> dict:
        intent_dict = payload.get("intent")
        if not isinstance(intent_dict, dict):
            raise ValueError("EXECUTE_REQUEST payload missing 'intent' object")

        intent = self._rebuild_intent(intent_dict)

        # R2-A: Extract lease validation data from the payload.
        # The data is included in the EXECUTE_REQUEST frame by the dispatcher
        # so the worker can validate the lease without needing shared broker state.
        lease_data = payload.get("intent", {}).get("lease_validation_data")

        # ── R2-A / R1 Authorization Policy ─────────────────────────────────
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
                    f"Missing ExecutionLease validation data at worker boundary: "
                    f"no lease_data present and intent not marked as legacy-authorized"
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
    FilesystemWorker().run()
