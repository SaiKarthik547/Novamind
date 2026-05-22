import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Set, Optional

logger = logging.getLogger("CapabilityBroker")


class Capability(Enum):
    PROCESS_SPAWN      = "PROCESS_SPAWN"
    PROCESS_SIGNAL     = "PROCESS_SIGNAL"
    FILE_READ          = "FILE_READ"
    FILE_WRITE         = "FILE_WRITE"
    FILE_DELETE        = "FILE_DELETE"
    FILE_MOVE          = "FILE_MOVE"
    DIRECTORY_LIST     = "DIRECTORY_LIST"
    NETWORK_CONNECT    = "NETWORK_CONNECT"
    NETWORK_BIND       = "NETWORK_BIND"
    POWERSHELL_EXECUTE = "POWERSHELL_EXECUTE"
    GUI_INPUT          = "GUI_INPUT"
    REGISTRY_WRITE     = "REGISTRY_WRITE"


@dataclass
class ResourceBudget:
    max_cpu_seconds: float = 30.0
    max_memory_mb: float = 512.0
    max_subprocesses: int = 5
    max_threads: int = 10
    max_duration_seconds: float = 60.0
    max_file_descriptors: int = 20


@dataclass
class ExecutionLease:
    lease_id: str
    task_id: str
    capabilities: Set[Capability]
    allowed_paths: List[str]
    allowed_commands: List[str]
    allowed_hosts: List[str]
    resource_budget: ResourceBudget
    expiration: float  # time.monotonic() based
    revoked: bool = False

    def is_valid(self) -> bool:
        return not self.revoked and time.monotonic() < self.expiration

    def check_capability(self, cap: Capability) -> bool:
        return cap in self.capabilities

    def check_path(self, path: str) -> bool:
        # Simplistic prefix match for allowed paths; production would normalize paths
        if "*" in self.allowed_paths:
            return True
        import os
        normalized = os.path.normpath(path)
        return any(normalized.startswith(os.path.normpath(p)) for p in self.allowed_paths)

    def check_command(self, cmd: str) -> bool:
        if "*" in self.allowed_commands:
            return True
        cmd_base = cmd.split()[0].lower() if cmd else ""
        return any(cmd_base == allowed.lower() for allowed in self.allowed_commands)


class CapabilityBroker:
    """
    Issues time-bound, finite capability leases to agents.
    Agents MUST present a valid lease to the ExecutionSandbox.
    """
    def __init__(self):
        self._active_leases: Dict[str, ExecutionLease] = {}

    def request_lease(
        self,
        task_id: str,
        capabilities: List[Capability],
        allowed_paths: List[str] = None,
        allowed_commands: List[str] = None,
        allowed_hosts: List[str] = None,
        budget: ResourceBudget = None,
        duration_seconds: float = 60.0,
    ) -> ExecutionLease:
        """
        In a full system, this would evaluate the request against global policies.
        For now, it grants the requested capabilities if valid.
        """
        lease_id = str(uuid.uuid4())
        lease = ExecutionLease(
            lease_id=lease_id,
            task_id=task_id,
            capabilities=set(capabilities),
            allowed_paths=allowed_paths or [],
            allowed_commands=allowed_commands or [],
            allowed_hosts=allowed_hosts or [],
            resource_budget=budget or ResourceBudget(),
            expiration=time.monotonic() + duration_seconds,
        )
        self._active_leases[lease_id] = lease
        logger.debug(f"Issued lease {lease_id[:8]} for task {task_id[:8]} with {len(capabilities)} capabilities")
        return lease

    def revoke_lease(self, lease_id: str) -> bool:
        if lease_id in self._active_leases:
            self._active_leases[lease_id].revoked = True
            logger.debug(f"Revoked lease {lease_id[:8]}")
            return True
        return False

    def validate_lease(self, lease_id: str) -> Optional[ExecutionLease]:
        lease = self._active_leases.get(lease_id)
        if lease and lease.is_valid():
            return lease
        return None
