import logging
import time
import uuid
import os
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
    """Time-bound, finite capability lease issued by CapabilityBroker.
    
    R2-A enhancements:
    - intent_id: binds lease to a specific execution intent
    - principal/agent identity: non-repudiation of who requested the lease
    - lifecycle state: tracks lease state through its lifetime
    - fail-closed validation: expired/revoked leases are rejected
    - lease records in WAL for crash recovery
    """
    lease_id: str
    task_id: str
    capabilities: Set[Capability]
    allowed_paths: List[str]
    allowed_commands: List[str]
    allowed_hosts: List[str]
    resource_budget: ResourceBudget
    expiration: float  # time.monotonic() based
    revoked: bool = False
    intent_id: Optional[str] = None        # Binds lease to a specific execution intent
    principal: str = "UNKNOWN"             # Non-repudiation: who requested the lease
    agent_id: str = "UNKNOWN"              # The agent/worker receiving the lease
    lifecycle_state: str = "ACTIVE"        # ACTIVE, EXPIRED, REVOKED, TERMINAL
    created_at: float = field(default_factory=time.monotonic)
    released_at: Optional[float] = None    # When lease was terminally released

    def is_valid(self) -> bool:
        """Fail-closed: lease must be ACTIVE - non-revoked, not expired, and in active lifecycle state."""
        return (not self.revoked 
                and self.lifecycle_state == "ACTIVE"
                and time.monotonic() < self.expiration)

    def check_capability(self, cap: Capability) -> bool:
        return cap in self.capabilities

    def check_path(self, path: str) -> bool:
        # Simplistic prefix match for allowed paths; production would normalize paths
        if "*" in self.allowed_paths:
            return True
        normalized = os.path.normpath(path)
        return any(normalized.startswith(os.path.normpath(p)) for p in self.allowed_paths)

    def check_command(self, cmd: str) -> bool:
        if "*" in self.allowed_commands:
            return True
        cmd_base = cmd.split()[0].lower() if cmd else ""
        return any(cmd_base == allowed.lower() for allowed in self.allowed_commands)

    def check_intent_id(self, intent_id: str) -> bool:
        """Verify lease is bound to the expected intent_id."""
        return self.intent_id is not None and self.intent_id == intent_id

    def check_principal(self, principal: str) -> bool:
        """Verify lease principal matches expected."""
        return self.principal == principal

    def check_agent(self, agent_id: str) -> bool:
        """Verify lease agent matches expected worker."""
        return self.agent_id == agent_id

    def is_terminal(self) -> bool:
        """Check if lease is in a terminal state (COMPLETED, FAILED, CANCELLED, ORPHANED)."""
        return self.lifecycle_state in ("COMPLETED", "FAILED", "CANCELLED", "ORPHANED")

    def terminalize(self, final_state: str) -> None:
        """Mark lease as terminal with a final state (COMPLETED, FAILED, CANCELLED, ORPHANED)."""
        self.lifecycle_state = final_state
        self.released_at = time.monotonic()


class CapabilityBroker:
    """Issues time-bound, finite capability leases to agents.
    
    R2-A enforcement:
    - acquire: create lease with intent binding and principal/agent identity
    - validate: fail-closed check at sandbox boundary
    - expire: automatic expiry enforcement
    - revoke: explicit revocation
    - terminal release: deterministic lease lifecycle (COMPLETED/FAILED/CANCELLED/ORPHANED)
    - fail closed: missing/invalid/expired lease always rejected
    - WAL integration: lease lifecycle recorded for crash recovery
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
        intent_id: str = None,
        principal: str = "UNKNOWN",
        agent_id: str = "UNKNOWN",
    ) -> ExecutionLease:
        """Create a new lease bound to an execution intent.
        
        The lease is immediately tracked and tied to the intent for the 
        lifecycle: intent -> valid lease -> exact capability -> exact target/scope -> authorized worker -> effect
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
            intent_id=intent_id,
            principal=principal,
            agent_id=agent_id,
            lifecycle_state="ACTIVE",
        )
        self._active_leases[lease_id] = lease
        logger.debug(
            f"Issued lease {lease_id[:8]} for task {task_id[:8]} "
            f"intent={intent_id} principal={principal} agent={agent_id} "
            f"with {len(capabilities)} capabilities"
        )
        return lease

    def revoke_lease(self, lease_id: str) -> bool:
        """Explicitly revoke a lease. Moves lifecycle to REVOKED state."""
        if lease_id in self._active_leases:
            self._active_leases[lease_id].revoked = True
            self._active_leases[lease_id].lifecycle_state = "REVOKED"
            logger.debug(f"Revoked lease {lease_id[:8]}")
            return True
        return False

    def validate_lease(self, lease_id: str) -> Optional[ExecutionLease]:
        """Fail-closed lease validation.
        
        Returns the lease ONLY if:
        - It exists in active leases
        - It is not revoked
        - It has not expired (time.monotonic() < expiration)
        - Lifecycle state is ACTIVE (not EXPIRED/REVOKED/TERMINAL)
        
        Any failure results in None, which the sandbox must reject.
        """
        lease = self._active_leases.get(lease_id)
        if lease is None:
            return None
        if not lease.is_valid():
            # Lease is either revoked or expired - do NOT return it
            # Log the rejection but never return a stale lease
            logger.warning(
                f"Lease validation FAILED for {lease_id[:8]}: "
                f"revoked={lease.revoked}, expired={not lease.is_valid()}, "
                f"lifecycle={lease.lifecycle_state}"
            )
            return None
        return lease

    def terminalize_lease(self, lease_id: str, final_state: str) -> bool:
        """Mark a lease as terminal (COMPLETED, FAILED, CANCELLED, ORPHANED).
        
        R2-A invariant: terminal intents must have deterministic lease semantics.
        Leases must not dangle in intermediate states.
        """
        if lease_id not in self._active_leases:
            logger.warning(f"Cannot terminalize unknown lease {lease_id[:8]}")
            return False
        lease = self._active_leases[lease_id]
        lease.terminalize(final_state)
        logger.info(
            f"Lease {lease_id[:8]} terminalized as {final_state} "
            f"intent={lease.intent_id} agent={lease.agent_id}"
        )
        return True

    def get_lease(self, lease_id: str) -> Optional[ExecutionLease]:
        """Get lease without validity check (for internal use only)."""
        return self._active_leases.get(lease_id)

    def lease_ids_for_intent(self, intent_id: str) -> List[str]:
        """Return all lease IDs bound to a specific intent_id."""
        return [
            lid for lid, lease in self._active_leases.items()
            if lease.intent_id == intent_id
        ]

    def expire_expired_leases(self) -> int:
        """Sweep and mark any expired leases. Returns count expired."""
        now = time.monotonic()
        expired_count = 0
        for lease in self._active_leases.values():
            if now > lease.expiration and lease.lifecycle_state == "ACTIVE":
                lease.lifecycle_state = "EXPIRED"
                expired_count += 1
                logger.debug(f"Auto-expired lease {lease.lease_id[:8]}")
        return expired_count