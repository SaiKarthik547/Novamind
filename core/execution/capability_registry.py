"""
core/execution/capability_registry.py
L1-A: CapabilityRegistry — Authoritative mapping of every permitted execution capability.

Every capability the kernel is willing to dispatch must appear here.
If a capability is not registered, KernelExecutionFacade MUST reject it.

Design rules:
- NO dynamic registration at runtime. All capabilities are declared statically at module load.
- requires_user_focus=True means the action CANNOT run in a background thread or headless session.
- allows_background_execution=False enforces foreground-only scheduling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class DeterminismClass(str, Enum):
    """Classifies how predictable/reproducible an execution outcome is."""
    DETERMINISTIC = "DETERMINISTIC"
    SEMI_DETERMINISTIC = "SEMI_DETERMINISTIC"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"


class ReplayPolicy(str, Enum):
    """How the WAL treats this capability during replay."""
    STRICT = "STRICT"          # Must reproduce bit-identical outcome
    STRUCTURAL = "STRUCTURAL"  # Structural equivalence is sufficient
    OBSERVATIONAL = "OBSERVATIONAL"  # Record only; no replay assertion
    SKIP = "SKIP"              # Do not replay (NON_DETERMINISTIC actions)


class RollbackPolicy(str, Enum):
    """What the kernel does on failure."""
    COMPENSATE = "COMPENSATE"  # Execute a compensating action
    IDEMPOTENT_RETRY = "IDEMPOTENT_RETRY"  # Safe to retry directly
    NO_ROLLBACK = "NO_ROLLBACK"  # No rollback possible
    HUMAN_REQUIRED = "HUMAN_REQUIRED"  # Escalate to human


class AuthorityLevel(str, Enum):
    """Who is allowed to invoke this capability."""
    KERNEL_ONLY = "KERNEL_ONLY"  # Kernel internals only
    ADAPTER = "ADAPTER"          # Registered adapters may use
    LEGACY_BRIDGE = "LEGACY_BRIDGE"  # Transitional: legacy code using facade
    UNSAFE_RUNTIME = "UNSAFE_RUNTIME"  # Direct agent call — FORBIDDEN in converged state


class CapabilityTrustLevel(str, Enum):
    """How much the runtime trusts this capability to influence state."""
    HIGH_AUTHORITY = "HIGH_AUTHORITY" # Kernel primitives, filesystem, etc.
    OBSERVATIONAL = "OBSERVATIONAL"   # UI adapters, read-only scripts, browser interaction.


# ─────────────────────────────────────────────────────────────────────────────
#  Capability Definition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapabilityDefinition:
    """Complete declaration of a single kernel-managed capability."""
    capability_name: str
    determinism_class: DeterminismClass
    replay_policy: ReplayPolicy
    rollback_policy: RollbackPolicy
    authority_level: AuthorityLevel
    trust_level: CapabilityTrustLevel  # Phase 14D: Prevents authority escalation
    requires_user_focus: bool     # Must the user session be in foreground?
    allows_background_execution: bool  # Can this run headlessly?
    side_effect_permanent: bool   # Can the side effect ever be undone?
    verification_mode: str        # References VerificationTaxonomy value


# ─────────────────────────────────────────────────────────────────────────────
#  Static Capability Table — THE AUTHORITATIVE TRUTH
# ─────────────────────────────────────────────────────────────────────────────

_CAPABILITIES: Dict[str, CapabilityDefinition] = {

    # ── Filesystem ───────────────────────────────────────────────────────────
    "filesystem.read": CapabilityDefinition(
        capability_name="filesystem.read",
        determinism_class=DeterminismClass.DETERMINISTIC,
        replay_policy=ReplayPolicy.STRICT,
        rollback_policy=RollbackPolicy.IDEMPOTENT_RETRY,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.HIGH_AUTHORITY,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=False,
        verification_mode="STRICT_STATE_VERIFICATION",
    ),
    "filesystem.write": CapabilityDefinition(
        capability_name="filesystem.write",
        determinism_class=DeterminismClass.DETERMINISTIC,
        replay_policy=ReplayPolicy.STRUCTURAL,
        rollback_policy=RollbackPolicy.COMPENSATE,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.HIGH_AUTHORITY,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=True,
        verification_mode="SIDE_EFFECT_VERIFICATION",
    ),
    "filesystem.delete": CapabilityDefinition(
        capability_name="filesystem.delete",
        determinism_class=DeterminismClass.DETERMINISTIC,
        replay_policy=ReplayPolicy.STRUCTURAL,
        rollback_policy=RollbackPolicy.NO_ROLLBACK,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.HIGH_AUTHORITY,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=True,
        verification_mode="SIDE_EFFECT_VERIFICATION",
    ),
    "filesystem.mkdir": CapabilityDefinition(
        capability_name="filesystem.mkdir",
        determinism_class=DeterminismClass.DETERMINISTIC,
        replay_policy=ReplayPolicy.STRUCTURAL,
        rollback_policy=RollbackPolicy.IDEMPOTENT_RETRY,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.HIGH_AUTHORITY,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=False,
        verification_mode="STRICT_STATE_VERIFICATION",
    ),

    # ── Process ──────────────────────────────────────────────────────────────
    "process.spawn": CapabilityDefinition(
        capability_name="process.spawn",
        determinism_class=DeterminismClass.SEMI_DETERMINISTIC,
        replay_policy=ReplayPolicy.STRUCTURAL,
        rollback_policy=RollbackPolicy.COMPENSATE,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.HIGH_AUTHORITY,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=True,
        verification_mode="SIDE_EFFECT_VERIFICATION",
    ),
    "process.kill": CapabilityDefinition(
        capability_name="process.kill",
        determinism_class=DeterminismClass.SEMI_DETERMINISTIC,
        replay_policy=ReplayPolicy.STRUCTURAL,
        rollback_policy=RollbackPolicy.NO_ROLLBACK,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.HIGH_AUTHORITY,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=True,
        verification_mode="SIDE_EFFECT_VERIFICATION",
    ),

    # ── Network ──────────────────────────────────────────────────────────────
    "network.http_request": CapabilityDefinition(
        capability_name="network.http_request",
        determinism_class=DeterminismClass.SEMI_DETERMINISTIC,
        replay_policy=ReplayPolicy.OBSERVATIONAL,
        rollback_policy=RollbackPolicy.NO_ROLLBACK,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.OBSERVATIONAL,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=True,
        verification_mode="OBSERVATIONAL_VERIFICATION",
    ),

    # ── UI Automation (NON_DETERMINISTIC — legacy bridge only) ───────────────
    "ui.mouse_click": CapabilityDefinition(
        capability_name="ui.mouse_click",
        determinism_class=DeterminismClass.NON_DETERMINISTIC,
        replay_policy=ReplayPolicy.SKIP,
        rollback_policy=RollbackPolicy.HUMAN_REQUIRED,
        authority_level=AuthorityLevel.LEGACY_BRIDGE,
        trust_level=CapabilityTrustLevel.OBSERVATIONAL,
        requires_user_focus=True,
        allows_background_execution=False,
        side_effect_permanent=True,
        verification_mode="OBSERVATIONAL_VERIFICATION",
    ),
    "ui.keyboard_type": CapabilityDefinition(
        capability_name="ui.keyboard_type",
        determinism_class=DeterminismClass.NON_DETERMINISTIC,
        replay_policy=ReplayPolicy.SKIP,
        rollback_policy=RollbackPolicy.HUMAN_REQUIRED,
        authority_level=AuthorityLevel.LEGACY_BRIDGE,
        trust_level=CapabilityTrustLevel.OBSERVATIONAL,
        requires_user_focus=True,
        allows_background_execution=False,
        side_effect_permanent=True,
        verification_mode="OBSERVATIONAL_VERIFICATION",
    ),
    "ui.hotkey": CapabilityDefinition(
        capability_name="ui.hotkey",
        determinism_class=DeterminismClass.NON_DETERMINISTIC,
        replay_policy=ReplayPolicy.SKIP,
        rollback_policy=RollbackPolicy.HUMAN_REQUIRED,
        authority_level=AuthorityLevel.LEGACY_BRIDGE,
        trust_level=CapabilityTrustLevel.OBSERVATIONAL,
        requires_user_focus=True,
        allows_background_execution=False,
        side_effect_permanent=True,
        verification_mode="OBSERVATIONAL_VERIFICATION",
    ),
    "ui.screenshot": CapabilityDefinition(
        capability_name="ui.screenshot",
        determinism_class=DeterminismClass.NON_DETERMINISTIC,
        replay_policy=ReplayPolicy.SKIP,
        rollback_policy=RollbackPolicy.NO_ROLLBACK,
        authority_level=AuthorityLevel.LEGACY_BRIDGE,
        trust_level=CapabilityTrustLevel.OBSERVATIONAL,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=False,
        verification_mode="OBSERVATIONAL_VERIFICATION",
    ),

    # ── Shell Worker ─────────────────────────────────────────────────────────
    "shell.execute": CapabilityDefinition(
        capability_name="shell.execute",
        determinism_class=DeterminismClass.SEMI_DETERMINISTIC,
        replay_policy=ReplayPolicy.OBSERVATIONAL,
        rollback_policy=RollbackPolicy.NO_ROLLBACK,
        authority_level=AuthorityLevel.ADAPTER,
        trust_level=CapabilityTrustLevel.HIGH_AUTHORITY,
        requires_user_focus=False,
        allows_background_execution=True,
        side_effect_permanent=True,
        verification_mode="SIDE_EFFECT_VERIFICATION",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
#  Registry Interface
# ─────────────────────────────────────────────────────────────────────────────

class CapabilityRegistry:
    """
    Singleton read-only registry of all declared kernel capabilities.
    Lookup is O(1). No runtime registration allowed.
    """

    _instance: "CapabilityRegistry | None" = None

    def __new__(cls) -> "CapabilityRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get(self, capability_name: str) -> CapabilityDefinition | None:
        """Return the CapabilityDefinition, or None if not registered."""
        return _CAPABILITIES.get(capability_name)

    def require(self, capability_name: str) -> CapabilityDefinition:
        """Return the CapabilityDefinition or raise if not registered.
        Used by KernelExecutionFacade to hard-reject unknown capabilities."""
        defn = _CAPABILITIES.get(capability_name)
        if defn is None:
            raise PermissionError(
                f"Capability '{capability_name}' is not registered in the CapabilityRegistry. "
                f"All capabilities must be declared statically. This is an authority violation."
            )
        return defn

    def all_capabilities(self) -> List[str]:
        return list(_CAPABILITIES.keys())

    def requires_foreground(self, capability_name: str) -> bool:
        defn = self.get(capability_name)
        return defn.requires_user_focus if defn else False

    def determinism_class(self, capability_name: str) -> DeterminismClass | None:
        defn = self.get(capability_name)
        return defn.determinism_class if defn else None


# Singleton instance
CAPABILITY_REGISTRY = CapabilityRegistry()
