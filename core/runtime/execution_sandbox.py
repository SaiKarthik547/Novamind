import logging
import os
import subprocess
from typing import Any, Dict, List, Optional
from core.runtime.capability_broker import CapabilityBroker, Capability, ExecutionLease
from core.runtime.resource_governor import ResourceGovernor

logger = logging.getLogger("ExecutionSandbox")


class SandboxViolation(Exception):
    """Implementation stub"""


class ExecutionSandbox:
    """The sole authority for executing side-effects.
    Wraps subprocess and file operations, enforcing Capabilities and ResourceBudgets.
    R2-A: All execution goes through lease boundary validation with fail-closed semantics.
    Terminal leases (COMPLETED/FAILED/CANCELLED/ORPHANED) are never allowed to execute effects.
    """

    def __init__(self, broker: CapabilityBroker, governor: ResourceGovernor):
        self.broker = broker
        self.governor = governor

    def _is_terminal_state(self, lease: ExecutionLease) -> bool:
        """Check if lease is in a terminal state that cannot authorize effects."""
        return lease.lifecycle_state in ("COMPLETED", "FAILED", "CANCELLED", "ORPHANED")

    def _verify_lease(self, lease_id: str, required_cap: Capability, expected_intent_id: str = None,
                      expected_principal: str = None, expected_agent: str = None) -> Optional[ExecutionLease]:
        """Fail-closed lease verification at the worker boundary.

        R2-A enforcement:
        - Lease must exist and be valid (not revoked, not expired)
        - Lifecycle state must be ACTIVE (not EXPIRED/REVOKED/TERMINAL)
        - intent_id binding must match (if provided)
        - principal identity must match (if provided)
        - agent identity must match (if provided)
        - capability must be granted by the lease

        Returns the valid lease, or None if any check fails (never returns a stale lease).
        """
        lease = self.broker.validate_lease(lease_id)
        if not lease:
            logger.warning(f"Lease validation REJECTED: {lease_id[:8]} not found or invalid/expired/revoked")
            return None

        # R2-A: Check for terminal state - never allow terminal leases to execute
        if self._is_terminal_state(lease):
            logger.warning(
                f"Lease validation REJECTED: {lease_id[:8]} terminal state ({lease.lifecycle_state}) "
                f"cannot authorize effects"
            )
            return None

        # R2-A: intent_id binding check
        if expected_intent_id is not None:
            if not lease.check_intent_id(expected_intent_id):
                logger.warning(
                    f"Lease validation REJECTED: {lease_id[:8]} intent_id mismatch. "
                    f"expected={expected_intent_id}, lease={lease.intent_id}"
                )
                return None

        # R2-A: principal identity check
        if expected_principal is not None:
            if not lease.check_principal(expected_principal):
                logger.warning(
                    f"Lease validation REJECTED: {lease_id[:8]} principal mismatch. "
                    f"expected={expected_principal}, lease={lease.principal}"
                )
                return None

        # R2-A: agent identity check (worker boundary revalidation)
        if expected_agent is not None:
            if not lease.check_agent(expected_agent):
                logger.warning(
                    f"Lease validation REJECTED: {lease_id[:8]} agent mismatch. "
                    f"expected={expected_agent}, lease={lease.agent_id}"
                )
                return None

        # R2-A: capability grant check
        if not lease.check_capability(required_cap):
            raise SandboxViolation(f"Lease does not grant capability: {required_cap.value}")
        return lease

    def _verify_lease_strict(self, lease_id: str, required_cap: Capability, expected_intent_id: str = None,
                             expected_principal: str = None, expected_agent: str = None) -> ExecutionLease:
        """Strict version that raises on any failure (used when failure must be explicit)."""
        lease = self._verify_lease(lease_id, required_cap, expected_intent_id, expected_principal, expected_agent)
        if not lease:
            raise SandboxViolation(
                f"Invalid, expired, revoked, mismatched, or terminal ExecutionLease: {lease_id}"
            )
        return lease

    def run_subprocess(
        self,
        lease_id: str,
        command: List[str] | str,
        shell: bool = False,
        **kwargs
    ) -> subprocess.Popen:
        """Safe wrapper around subprocess.Popen with R2-A lease boundary validation."""
        lease = self._verify_lease_strict(
            lease_id, Capability.PROCESS_SPAWN,
            expected_intent_id=kwargs.get("_intent_id"),
            expected_principal=kwargs.get("_principal"),
            expected_agent=kwargs.get("_agent"),
        )

        cmd_str = command if isinstance(command, str) else " ".join(command)
        if not lease.check_command(cmd_str):
            raise SandboxViolation(f"Command not allowed by lease: {cmd_str}")

        logger.debug(f"Sandbox executing command: {cmd_str[:50]}")
        proc = subprocess.Popen(command, shell=shell, **kwargs)
        self.governor.register_process(proc.pid, lease.task_id, lease.resource_budget)
        return proc

    def read_file(self, lease_id: str, path: str, mode: str = "r") -> str | bytes:
        """Safe wrapper around open() for reading with R2-A lease boundary validation."""
        lease = self._verify_lease_strict(
            lease_id, Capability.FILE_READ,
            expected_intent_id=kwargs.get("_intent_id") if "kwargs" in dir() else None,
        )
        # Note: read_file doesn't take intent/principal/agent kwargs in original sig;
        # this is a strict override. For backward compatibility, we'll keep the
        # simpler check but still enforce capability and state.
        if not lease.check_path(path):
            raise SandboxViolation(f"Path not allowed for read: {path}")

        logger.debug(f"Sandbox reading file: {path}")
        with open(path, mode) as f:
            return f.read()

    def write_file(self, lease_id: str, path: str, content: str | bytes, mode: str = "w",
                   intent_id: str = None, principal: str = None, agent: str = None) -> None:
        """Safe wrapper around open() for writing with R2-A lease boundary validation and identity checks."""
        lease = self._verify_lease_strict(
            lease_id, Capability.FILE_WRITE,
            expected_intent_id=intent_id,
            expected_principal=principal,
            expected_agent=agent,
        )
        if not lease.check_path(path):
            raise SandboxViolation(f"Path not allowed for write: {path}")

        logger.debug(f"Sandbox writing file: {path}")
        with open(path, mode) as f:
            f.write(content)

    def delete_file(self, lease_id: str, path: str, intent_id: str = None, principal: str = None,
                    agent: str = None) -> None:
        """Safe wrapper around os.remove() with R2-A lease boundary validation."""
        lease = self._verify_lease_strict(
            lease_id, Capability.FILE_DELETE,
            expected_intent_id=intent_id,
            expected_principal=principal,
            expected_agent=agent,
        )
        if not lease.check_path(path):
            raise SandboxViolation(f"Path not allowed for delete: {path}")

        logger.debug(f"Sandbox deleting file: {path}")
        os.remove(path)

    # In a full system, you would wrap network requests, registry operations, etc. here as well.