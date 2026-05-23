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
    """
    The sole authority for executing side-effects.
    Wraps subprocess and file operations, enforcing Capabilities and ResourceBudgets.
    """
    def __init__(self, broker: CapabilityBroker, governor: ResourceGovernor):
        self.broker = broker
        self.governor = governor

    def _verify_lease(self, lease_id: str, required_cap: Capability) -> ExecutionLease:
        lease = self.broker.validate_lease(lease_id)
        if not lease:
            raise SandboxViolation("Invalid, expired, or revoked ExecutionLease")
        if not lease.check_capability(required_cap):
            raise SandboxViolation(f"Lease does not grant capability: {required_cap.value}")
        return lease

    def run_subprocess(
        self,
        lease_id: str,
        command: List[str] | str,
        shell: bool = False,
        **kwargs
    ) -> subprocess.Popen:
        """
        Safe wrapper around subprocess.Popen.
        """
        lease = self._verify_lease(lease_id, Capability.PROCESS_SPAWN)

        cmd_str = command if isinstance(command, str) else " ".join(command)
        if not lease.check_command(cmd_str):
            raise SandboxViolation(f"Command not allowed by lease: {cmd_str}")

        logger.debug(f"Sandbox executing command: {cmd_str[:50]}")
        
        proc = subprocess.Popen(command, shell=shell, **kwargs)
        self.governor.register_process(proc.pid, lease.task_id, lease.resource_budget)
        return proc

    def read_file(self, lease_id: str, path: str, mode: str = "r") -> str | bytes:
        """Safe wrapper around open() for reading."""
        lease = self._verify_lease(lease_id, Capability.FILE_READ)
        if not lease.check_path(path):
            raise SandboxViolation(f"Path not allowed for read: {path}")

        logger.debug(f"Sandbox reading file: {path}")
        with open(path, mode) as f:
            return f.read()

    def write_file(self, lease_id: str, path: str, content: str | bytes, mode: str = "w"):
        """Safe wrapper around open() for writing."""
        lease = self._verify_lease(lease_id, Capability.FILE_WRITE)
        if not lease.check_path(path):
            raise SandboxViolation(f"Path not allowed for write: {path}")

        logger.debug(f"Sandbox writing file: {path}")
        with open(path, mode) as f:
            f.write(content)

    def delete_file(self, lease_id: str, path: str):
        """Safe wrapper around os.remove()"""
        lease = self._verify_lease(lease_id, Capability.FILE_DELETE)
        if not lease.check_path(path):
            raise SandboxViolation(f"Path not allowed for delete: {path}")

        logger.debug(f"Sandbox deleting file: {path}")
        os.remove(path)

    # In a full system, you would wrap network requests, registry operations, etc. here as well.