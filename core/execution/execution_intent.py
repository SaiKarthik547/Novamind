from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional

class IntentStatus(Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

class VerificationMode(Enum):
    EXACT = "EXACT"              # Byte-identical verification
    STRUCTURAL = "STRUCTURAL"    # Object shape/state verification
    SEMANTIC = "SEMANTIC"        # Intended OS outcome verification
    HEURISTIC = "HEURISTIC"      # Best-effort AI validation
    NONE = "NONE"                # Fire-and-forget

class RollbackMode(Enum):
    TERMINATE_TREE = "TERMINATE_TREE"
    REVERT_STATE = "REVERT_STATE"
    NO_ROLLBACK = "NO_ROLLBACK"

class IntentPriority(Enum):
    BACKGROUND = 0
    STANDARD = 1
    HIGH = 2
    CRITICAL = 3

class IntentDeterminismLevel(Enum):
    STRICT = "STRICT"
    PROBABILISTIC = "PROBABILISTIC"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"

@dataclass(frozen=True)
class ExecutionIntent:
    """
    The boundary between Agent Intelligence and Kernel Execution.
    Agents emit Intents. They DO NOT execute them.
    Intents are serializable, replayable, and schedulable.

    L2-A: Expanded with full kernel convergence fields.
    """
    adapter: str             # e.g., 'process', 'filesystem', 'registry'
    operation: str           # e.g., 'spawn', 'write_file', 'set_key'
    idempotent: bool         # Mandatory declaration for replay safety

    verification_mode: VerificationMode
    rollback_strategy: RollbackMode
    capability_scope: Dict[str, Any]
    payload: Dict[str, Any]

    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = "UNKNOWN"

    # Scheduling & Determinism
    priority: IntentPriority = IntentPriority.STANDARD
    determinism: IntentDeterminismLevel = IntentDeterminismLevel.PROBABILISTIC
    timeout_ms: int = 30000

    # ── L2-A: Kernel Convergence Fields ──────────────────────────────────────
    # Causation lineage — required for WAL replay integrity
    parent_intent_id: Optional[str] = None
    causation_chain: List[str] = field(default_factory=list)

    # Capability routing
    capability_domain: str = ""               # e.g. 'filesystem', 'process', 'ui'
    determinism_class: str = "SEMI_DETERMINISTIC"  # DETERMINISTIC | SEMI_DETERMINISTIC | NON_DETERMINISTIC
    replay_policy: str = "STRUCTURAL"         # STRICT | STRUCTURAL | OBSERVATIONAL | SKIP
    side_effect_level: str = "PERMANENT"      # PERMANENT | TRANSIENT | NONE

    # Authority tracking — audit trail for convergence migration
    authority_origin: str = "legacy_bridge"   # 'kernel' | 'legacy_bridge' | 'unsafe_runtime'

    # Concurrency safety
    commutative: bool = False                  # True = safe for parallel execution
    exclusive_resource_locks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "agent_id": self.agent_id,
            "adapter": self.adapter,
            "operation": self.operation,
            "idempotent": self.idempotent,
            "verification_mode": self.verification_mode.value,
            "rollback_strategy": self.rollback_strategy.value,
            "capability_scope": self.capability_scope,
            "payload": self.payload,
            "priority": self.priority.name,
            "determinism": self.determinism.value,
            "timeout_ms": self.timeout_ms,
            # L2-A: Kernel convergence fields
            "parent_intent_id": self.parent_intent_id,
            "causation_chain": self.causation_chain,
            "capability_domain": self.capability_domain,
            "determinism_class": self.determinism_class,
            "replay_policy": self.replay_policy,
            "side_effect_level": self.side_effect_level,
            "authority_origin": self.authority_origin,
            "commutative": self.commutative,
            "exclusive_resource_locks": self.exclusive_resource_locks,
        }
