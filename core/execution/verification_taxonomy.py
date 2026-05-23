"""
core/execution/verification_taxonomy.py
L2.5-B: Formal verification mode taxonomy.

Every ExecutionIntent must declare which verification mode applies.
Verification mode determines HOW the kernel validates that an action
produced the expected outcome.

Without this taxonomy, verification semantics are inconsistent across adapters,
and replay correctness cannot be guaranteed.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict


# ─────────────────────────────────────────────────────────────────────────────
#  Taxonomy
# ─────────────────────────────────────────────────────────────────────────────

class VerificationMode(str, Enum):
    """
    Formal taxonomy of post-execution verification strategies.

    Use the WEAKEST mode that is still meaningful for the capability type.
    Escalate only when required by the capability's determinism class.
    """

    STRICT_STATE_VERIFICATION = "STRICT_STATE_VERIFICATION"
    """
    The kernel reads back the authoritative system state and asserts
    it matches the intended outcome precisely.
    Use for: filesystem reads, registry reads, deterministic queries.
    Determinism requirement: DETERMINISTIC
    Replay guarantee: Full bit-identical reproduction
    """

    SIDE_EFFECT_VERIFICATION = "SIDE_EFFECT_VERIFICATION"
    """
    The kernel confirms the side effect exists but does NOT assert
    bit-identical output (e.g., file was written, process was started).
    Use for: filesystem writes, process spawns, network mutations.
    Determinism requirement: DETERMINISTIC or SEMI_DETERMINISTIC
    Replay guarantee: Structural equivalence
    """

    OBSERVATIONAL_VERIFICATION = "OBSERVATIONAL_VERIFICATION"
    """
    The kernel records what happened (screenshot, log, status code) but
    does NOT assert equivalence. Suitable for inherently variable outcomes.
    Use for: HTTP requests, UI automation, browser interactions.
    Determinism requirement: SEMI_DETERMINISTIC or NON_DETERMINISTIC
    Replay guarantee: Observational record only; no assertion
    """

    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    """
    A human must confirm the outcome. Used only when automated verification
    is impossible or dangerous.
    Use for: destructive actions, user-visible state changes requiring sign-off.
    Determinism requirement: Any
    Replay guarantee: None (human-dependent)
    """

    BEST_EFFORT = "BEST_EFFORT"
    """
    Verification is attempted but failure does NOT prevent COMPLETED transition.
    Use ONLY for non-critical cleanup operations or telemetry writes.
    Determinism requirement: Any
    Replay guarantee: None
    """

    NONE = "NONE"
    """
    No verification performed. FORBIDDEN for any capability with side_effect_permanent=True.
    Allowed ONLY for: pure read operations, no-op adapters.
    """


# ─────────────────────────────────────────────────────────────────────────────
#  Compatibility rules — enforced by KernelExecutionFacade
# ─────────────────────────────────────────────────────────────────────────────

# Maps DeterminismClass -> allowed VerificationModes (weakest to strongest)
DETERMINISM_TO_ALLOWED_MODES: Dict[str, frozenset] = {
    "DETERMINISTIC": frozenset({
        VerificationMode.STRICT_STATE_VERIFICATION,
        VerificationMode.SIDE_EFFECT_VERIFICATION,
        VerificationMode.BEST_EFFORT,
        VerificationMode.NONE,
    }),
    "SEMI_DETERMINISTIC": frozenset({
        VerificationMode.SIDE_EFFECT_VERIFICATION,
        VerificationMode.OBSERVATIONAL_VERIFICATION,
        VerificationMode.BEST_EFFORT,
    }),
    "NON_DETERMINISTIC": frozenset({
        VerificationMode.OBSERVATIONAL_VERIFICATION,
        VerificationMode.HUMAN_CONFIRMED,
        VerificationMode.BEST_EFFORT,
    }),
}


def validate_verification_mode(
    determinism_class: str,
    verification_mode: "VerificationMode",
) -> None:
    """
    Assert that the verification mode is compatible with the determinism class.
    Raises ValueError if incompatible — called by KernelExecutionFacade.
    """
    allowed = DETERMINISM_TO_ALLOWED_MODES.get(determinism_class, frozenset())
    if verification_mode not in allowed:
        raise ValueError(
            f"VerificationMode.{verification_mode.value} is incompatible with "
            f"DeterminismClass.{determinism_class}. "
            f"Allowed modes: {[m.value for m in allowed]}"
        )
